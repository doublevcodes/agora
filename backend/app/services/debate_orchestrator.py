from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.settings import Settings
from app.core.transaction_parser import parse_transaction
from app.integrations.specter_client import SpecterClient
from app.llm.model_router import RoutingDecision, route_models
from app.llm.openrouter_client import OpenRouterClient, OpenRouterError
from app.llm.prompts import (
    build_agent_messages,
    build_repair_messages,
    build_verdict_messages,
)
from app.schemas.debate import (
    AgentRole,
    AgentStructuredMessage,
    ParsedTransaction,
    SpecterBrief,
    SseEnvelope,
    VerdictDecision,
    VerdictOutcome,
)
from app.utils.confidence import confidence_to_label

logger = logging.getLogger(__name__)


@dataclass
class _OrchestratorContext:
    trace_id: str
    transaction: ParsedTransaction
    brief: SpecterBrief
    routing: RoutingDecision
    transcript: List[AgentStructuredMessage]


class DebateOrchestrator:
    def __init__(
        self,
        settings: Settings,
        openrouter: Optional[OpenRouterClient] = None,
        specter: Optional[SpecterClient] = None,
    ):
        self._settings = settings
        self._openrouter = openrouter or OpenRouterClient(settings)
        self._specter = specter or SpecterClient(settings)

    async def run(
        self, raw_transaction: str, max_rounds: int
    ) -> AsyncIterator[SseEnvelope]:
        trace_id = uuid.uuid4().hex
        max_rounds = max(1, min(self._settings.debate_max_rounds, max_rounds))

        yield self._envelope(trace_id, "status", {"message": "Parsing transaction"})

        try:
            tx = parse_transaction(raw_transaction)
        except ValueError as exc:
            yield self._envelope(trace_id, "error", {"message": str(exc)})
            yield self._envelope(trace_id, "done", {"trace_id": trace_id})
            return

        yield self._envelope(
            trace_id,
            "status",
            {"message": "Transaction parsed", "transaction": tx.model_dump()},
        )

        yield self._envelope(
            trace_id,
            "status",
            {"message": "Retrieving Specter intelligence"},
        )

        brief = await self._specter.lookup_vendor(tx.vendor)
        yield self._envelope(
            trace_id,
            "specter_brief",
            {
                "brief": brief.model_dump(exclude={"raw"}),
            },
        )

        routing = route_models(self._settings, tx, brief)
        yield self._envelope(
            trace_id,
            "status",
            {
                "message": "Model routing decided",
                "risk_level": routing.risk_level,
                "rationale": routing.rationale,
                "models": {
                    "hermes": routing.hermes_model,
                    "nemesis": routing.nemesis_model,
                    "verdict": routing.verdict_model,
                },
            },
        )

        ctx = _OrchestratorContext(
            trace_id=trace_id,
            transaction=tx,
            brief=brief,
            routing=routing,
            transcript=[],
        )

        async for envelope in self._run_debate_loop(ctx, max_rounds):
            yield envelope

        async for envelope in self._run_verdict(ctx):
            yield envelope

        yield self._envelope(trace_id, "done", {"trace_id": trace_id})

    async def _run_debate_loop(
        self, ctx: _OrchestratorContext, max_rounds: int
    ) -> AsyncIterator[SseEnvelope]:
        for round_idx in range(1, max_rounds + 1):
            yield self._envelope(
                ctx.trace_id,
                "round_state",
                {"round": round_idx, "phase": "start"},
            )

            for role in ("hermes", "nemesis"):
                msg = await self._produce_agent_turn(ctx, role, round_idx)  # type: ignore[arg-type]
                ctx.transcript.append(msg)
                yield self._envelope(
                    ctx.trace_id,
                    "agent_message",
                    {
                        "message": msg.model_dump(),
                        "confidence_label": confidence_to_label(msg.confidence),
                    },
                )

            yield self._envelope(
                ctx.trace_id,
                "round_state",
                {"round": round_idx, "phase": "end"},
            )

            if round_idx >= 2 and self._should_stop_early(ctx.transcript):
                yield self._envelope(
                    ctx.trace_id,
                    "status",
                    {
                        "message": "Adaptive stop triggered (convergence + stable confidence)",
                        "round": round_idx,
                    },
                )
                break

    async def _produce_agent_turn(
        self,
        ctx: _OrchestratorContext,
        role: AgentRole,
        round_idx: int,
    ) -> AgentStructuredMessage:
        model = (
            ctx.routing.hermes_model if role == "hermes" else ctx.routing.nemesis_model
        )
        messages = build_agent_messages(
            role, ctx.transaction, ctx.brief, ctx.transcript, round_idx
        )

        raw_response = ""
        try:
            raw_response = await self._openrouter.complete(
                model=model,
                messages=messages,
                temperature=0.5,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
        except OpenRouterError as exc:
            logger.warning("OpenRouter call failed for %s: %s", role, exc)
            return self._fallback_message(role, round_idx, f"Model call failed: {exc}")

        parsed = _safe_parse_structured(raw_response, role, round_idx)
        if parsed is not None:
            return parsed

        try:
            repair_messages = build_repair_messages(
                role,
                ctx.transaction,
                ctx.brief,
                ctx.transcript,
                round_idx,
                raw_response,
            )
            retry_response = await self._openrouter.complete(
                model=model,
                messages=repair_messages,
                temperature=0.2,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            parsed_retry = _safe_parse_structured(retry_response, role, round_idx)
            if parsed_retry is not None:
                return parsed_retry
            return self._text_fallback_message(role, round_idx, retry_response or raw_response)
        except OpenRouterError as exc:
            logger.warning("OpenRouter repair call failed for %s: %s", role, exc)
            return self._text_fallback_message(role, round_idx, raw_response)

    def _fallback_message(
        self, role: AgentRole, round_idx: int, reason: str
    ) -> AgentStructuredMessage:
        return AgentStructuredMessage(
            role=role,
            round=round_idx,
            stance="escalate",
            claim="Unable to produce a structured argument this turn.",
            evidence=reason,
            counterpoint="(no counterpoint available)",
            risk_tags=["model_unavailable"],
            confidence=0.0,
            text=(
                "I could not generate a structured argument due to a model "
                "availability issue. Please rely on the rest of the debate."
            ),
            structured_available=False,
        )

    def _text_fallback_message(
        self, role: AgentRole, round_idx: int, raw_text: str
    ) -> AgentStructuredMessage:
        text = (raw_text or "").strip() or "(no response)"
        if len(text) > 1200:
            text = text[:1200].rstrip() + "..."
        return AgentStructuredMessage(
            role=role,
            round=round_idx,
            stance="escalate",
            claim="Structured response unavailable; raw text preserved.",
            evidence="Model returned non-JSON output.",
            counterpoint="(no structured counterpoint available)",
            risk_tags=["malformed_structured_output"],
            confidence=0.3,
            text=text,
            structured_available=False,
        )

    def _should_stop_early(self, transcript: List[AgentStructuredMessage]) -> bool:
        """Stop when both agents repeat their stance with stable, non-low confidence
        in the latest two completed rounds."""
        by_round: Dict[int, Dict[str, AgentStructuredMessage]] = {}
        for m in transcript:
            by_round.setdefault(m.round, {})[m.role] = m
        complete_rounds = sorted(
            r for r, m in by_round.items() if "hermes" in m and "nemesis" in m
        )
        if len(complete_rounds) < 2:
            return False
        last_two = complete_rounds[-2:]
        a, b = by_round[last_two[0]], by_round[last_two[1]]
        same_stance = (
            a["hermes"].stance == b["hermes"].stance
            and a["nemesis"].stance == b["nemesis"].stance
        )
        if not same_stance:
            return False
        confidence_stable = (
            abs(a["hermes"].confidence - b["hermes"].confidence) <= 0.1
            and abs(a["nemesis"].confidence - b["nemesis"].confidence) <= 0.1
        )
        confidence_floor = (
            a["hermes"].confidence >= 0.6
            and a["nemesis"].confidence >= 0.6
            and b["hermes"].confidence >= 0.6
            and b["nemesis"].confidence >= 0.6
        )
        return confidence_stable and confidence_floor

    async def _run_verdict(
        self, ctx: _OrchestratorContext
    ) -> AsyncIterator[SseEnvelope]:
        yield self._envelope(
            ctx.trace_id, "status", {"message": "Verdict deliberating"}
        )
        messages = build_verdict_messages(ctx.transaction, ctx.brief, ctx.transcript)
        try:
            raw = await self._openrouter.complete(
                model=ctx.routing.verdict_model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
        except OpenRouterError as exc:
            logger.warning("Verdict model call failed: %s", exc)
            decision = VerdictDecision(
                outcome="ESCALATE TO HUMAN",
                reason=(
                    "Verdict model unavailable; defaulting to human review."
                ),
            )
            yield self._envelope(
                ctx.trace_id,
                "verdict",
                {"verdict": decision.model_dump()},
            )
            return

        decision = _parse_verdict(raw)
        if decision.outcome == "ESCALATE TO HUMAN":
            decision = decision.model_copy(
                update={
                    "escalation_packet": _build_escalation_packet(
                        ctx.transaction, ctx.brief, ctx.transcript, decision.reason
                    )
                }
            )
        yield self._envelope(
            ctx.trace_id, "verdict", {"verdict": decision.model_dump()}
        )

    def _envelope(
        self, trace_id: str, event_type: str, payload: Dict[str, Any]
    ) -> SseEnvelope:
        return SseEnvelope(
            event_id=uuid.uuid4().hex,
            trace_id=trace_id,
            event_type=event_type,  # type: ignore[arg-type]
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )


def _safe_parse_structured(
    raw: str, role: AgentRole, round_idx: int
) -> Optional[AgentStructuredMessage]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    payload = {
        "role": role,
        "round": round_idx,
        "stance": data.get("stance"),
        "claim": data.get("claim"),
        "evidence": data.get("evidence"),
        "counterpoint": data.get("counterpoint"),
        "risk_tags": data.get("risk_tags") or data.get("riskTags") or [],
        "confidence": data.get("confidence"),
        "text": data.get("text"),
        "structured_available": True,
    }
    if (
        not isinstance(payload["stance"], str)
        or payload["stance"] not in ("approve", "reject", "escalate")
    ):
        return None
    if not isinstance(payload["claim"], str) or not payload["claim"].strip():
        return None
    if not isinstance(payload["text"], str) or not payload["text"].strip():
        return None
    if payload["confidence"] is None:
        return None
    try:
        payload["confidence"] = float(payload["confidence"])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload["risk_tags"], list):
        payload["risk_tags"] = []
    if not isinstance(payload.get("evidence"), str):
        payload["evidence"] = ""
    if not isinstance(payload.get("counterpoint"), str):
        payload["counterpoint"] = ""
    try:
        return AgentStructuredMessage(**payload)
    except Exception as exc:
        logger.debug("Structured parse rejected: %s", exc)
        return None


def _parse_verdict(raw: str) -> VerdictDecision:
    text = (raw or "").strip()
    outcome: Optional[VerdictOutcome] = None
    reason = ""

    upper = text.upper()
    for candidate in ("ESCALATE TO HUMAN", "APPROVE", "REJECT"):
        if candidate in upper:
            outcome = candidate  # type: ignore[assignment]
            break

    reason_match = re.search(r"REASON\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if reason_match:
        reason = reason_match.group(1).strip()
    else:
        # Fallback: take the last non-empty line.
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            reason = lines[-1]

    if reason:
        first_sentence = re.split(r"(?<=[.!?])\s+", reason, maxsplit=1)[0]
        reason = first_sentence.strip().rstrip(".") + "."

    if outcome is None:
        outcome = "ESCALATE TO HUMAN"
        if not reason:
            reason = (
                "Could not determine a clear verdict from the deliberation; "
                "defaulting to human review."
            )

    if not reason:
        reason = "No reasoning provided by the verdict model."

    return VerdictDecision(outcome=outcome, reason=reason)


def _build_escalation_packet(
    tx: ParsedTransaction,
    brief: SpecterBrief,
    transcript: List[AgentStructuredMessage],
    reason: str,
) -> Dict[str, Any]:
    final_two = transcript[-2:] if len(transcript) >= 2 else transcript[:]
    return {
        "transaction": tx.model_dump(),
        "specter_brief": brief.model_dump(exclude={"raw"}),
        "final_turns": [m.model_dump() for m in final_two],
        "rationale": reason,
    }
