from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from app.core.settings import Settings
from app.core.transaction_parser import parse_transaction
from app.integrations.resend_client import ResendClient
from app.integrations.specter_client import SpecterClient
from app.llm.model_router import RoutingDecision, route_models
from app.llm.openrouter_client import OpenRouterClient, OpenRouterError
from app.llm.prompts import (
    build_agent_messages,
    build_novelty_retry_messages,
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
    escalation_email: Optional[str]
    memory: Dict[str, Any]


class DebateOrchestrator:
    def __init__(
        self,
        settings: Settings,
        openrouter: Optional[OpenRouterClient] = None,
        specter: Optional[SpecterClient] = None,
        resend: Optional[ResendClient] = None,
    ):
        self._settings = settings
        self._openrouter = openrouter or OpenRouterClient(settings)
        self._specter = specter or SpecterClient(settings)
        self._resend = resend or ResendClient(settings)

    async def run(
        self,
        raw_transaction: str,
        max_rounds: int,
        escalation_email: Optional[str] = None,
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
            escalation_email=(escalation_email or "").strip() or None,
            memory={
                "agreed_facts": [],
                "disputed_points": [],
                "unresolved_checks": [],
                "current_risk_summary": "Debate has not started yet.",
                "recent_claims": {"hermes": [], "nemesis": []},
            },
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
                _update_memory(ctx.memory, msg)
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
            role,
            ctx.transaction,
            ctx.brief,
            ctx.transcript,
            round_idx,
            memory=ctx.memory,
            history_turn_limit=2,
        )

        max_repairs = max(0, int(self._settings.structured_retry_attempts))
        raw_response = ""
        for attempt in range(0, max_repairs + 1):
            try:
                call_messages = messages
                if attempt > 0:
                    call_messages = build_repair_messages(
                        role,
                        ctx.transaction,
                        ctx.brief,
                        ctx.transcript,
                        round_idx,
                        raw_response,
                        memory=ctx.memory,
                        repair_round=attempt,
                    )
                raw_response = await self._openrouter.complete(
                    model=model,
                    messages=call_messages,
                    temperature=0.5 if attempt == 0 else 0.2,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
            except OpenRouterError as exc:
                logger.warning("OpenRouter call failed for %s (attempt %s): %s", role, attempt, exc)
                return self._fallback_message(role, round_idx, f"Model call failed: {exc}")

            parsed = _safe_parse_structured(raw_response, role, round_idx)
            if parsed is not None:
                previous_same_role = _latest_role_turn(ctx.transcript, role)
                if previous_same_role and _is_repetitive_turn(parsed, previous_same_role):
                    try:
                        novelty_messages = build_novelty_retry_messages(
                            role=role,
                            tx=ctx.transaction,
                            brief=ctx.brief,
                            transcript=ctx.transcript,
                            current_round=round_idx,
                            bad_response=raw_response,
                            previous_turn_text=previous_same_role.text,
                            memory=ctx.memory,
                        )
                        novelty_raw = await self._openrouter.complete(
                            model=model,
                            messages=novelty_messages,
                            temperature=0.35,
                            max_tokens=600,
                            response_format={"type": "json_object"},
                        )
                        novelty_parsed = _safe_parse_structured(
                            novelty_raw, role, round_idx
                        )
                        if novelty_parsed and not _is_repetitive_turn(
                            novelty_parsed, previous_same_role
                        ):
                            return novelty_parsed
                    except OpenRouterError as exc:
                        logger.warning(
                            "OpenRouter novelty retry failed for %s: %s", role, exc
                        )
                return parsed

        return self._schema_failure_message(role, round_idx, raw_response)

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

    def _schema_failure_message(
        self, role: AgentRole, round_idx: int, raw_text: str
    ) -> AgentStructuredMessage:
        text = (raw_text or "").strip() or "(no response)"
        if len(text) > 700:
            text = text[:700].rstrip() + "..."
        return AgentStructuredMessage(
            role=role,
            round=round_idx,
            stance="escalate",
            claim="Schema validation failed after bounded retries.",
            evidence="Model output remained invalid JSON schema-compliant content.",
            counterpoint="Unable to trust this turn output.",
            risk_tags=["schema_failure", "malformed_structured_output"],
            confidence=0.0,
            text=(
                "I could not provide a reliable structured argument this turn because "
                "output validation failed repeatedly, so this point should be escalated."
            ),
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
        if confidence_stable and confidence_floor:
            return True

        # Secondary stop: if both agents are largely repeating themselves across
        # two consecutive rounds, move to verdict instead of burning more rounds.
        repetition = (
            _text_similarity(a["hermes"].text, b["hermes"].text) >= 0.72
            and _text_similarity(a["nemesis"].text, b["nemesis"].text) >= 0.72
        )
        repetition_confidence = (
            a["hermes"].confidence >= 0.5
            and a["nemesis"].confidence >= 0.5
            and b["hermes"].confidence >= 0.5
            and b["nemesis"].confidence >= 0.5
        )
        return repetition and repetition_confidence

    async def _run_verdict(
        self, ctx: _OrchestratorContext
    ) -> AsyncIterator[SseEnvelope]:
        yield self._envelope(
            ctx.trace_id, "status", {"message": "Verdict deliberating"}
        )
        messages = build_verdict_messages(
            ctx.transaction, ctx.brief, ctx.transcript, memory=ctx.memory
        )
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
            escalation_packet = _build_escalation_packet(
                ctx.transaction, ctx.brief, ctx.transcript, decision.reason
            )
            decision = decision.model_copy(
                update={"escalation_packet": escalation_packet}
            )
            await self._notify_escalation(
                trace_id=ctx.trace_id,
                escalation_packet=escalation_packet,
                delivery_email=ctx.escalation_email,
            )
            yield self._envelope(
                ctx.trace_id,
                "verdict",
                {"verdict": decision.model_dump()},
            )
            return

        decision = _parse_verdict(raw)
        if _is_uninformative_reason(decision.reason):
            decision = decision.model_copy(
                update={
                    "reason": _build_brief_verdict_reason(
                        outcome=decision.outcome,
                        transcript=ctx.transcript,
                        brief=ctx.brief,
                    )
                }
            )
        if decision.outcome == "ESCALATE TO HUMAN":
            escalation_packet = _build_escalation_packet(
                ctx.transaction, ctx.brief, ctx.transcript, decision.reason
            )
            decision = decision.model_copy(
                update={"escalation_packet": escalation_packet}
            )
            await self._notify_escalation(
                trace_id=ctx.trace_id,
                escalation_packet=escalation_packet,
                delivery_email=ctx.escalation_email,
            )
        yield self._envelope(
            ctx.trace_id, "verdict", {"verdict": decision.model_dump()}
        )

    async def _notify_escalation(
        self,
        *,
        trace_id: str,
        escalation_packet: Dict[str, Any],
        delivery_email: Optional[str] = None,
    ) -> None:
        try:
            await self._resend.send_escalation_email(
                trace_id=trace_id,
                escalation_packet=escalation_packet,
                delivery_email=delivery_email,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Escalation email notification failed: %s", exc)

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
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    verdict_line = next(
        (line for line in lines if re.match(r"^VERDICT\s*:", line, re.IGNORECASE)),
        None,
    )
    if verdict_line:
        verdict_value = verdict_line.split(":", 1)[1].strip().upper()
        if verdict_value in ("APPROVE", "REJECT", "ESCALATE TO HUMAN"):
            outcome = verdict_value  # type: ignore[assignment]

    reason_match = re.search(r"REASON\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if reason_match:
        reason = reason_match.group(1).strip()
    else:
        # Fallback: take the last non-empty line.
        if lines:
            reason = lines[-1]

    if reason:
        reason = _clean_verdict_reason(reason)

    if _reason_contradicts_outcome(reason, outcome):
        outcome = "ESCALATE TO HUMAN"
        reason = (
            "Verdict output was internally inconsistent; escalating for human review."
        )

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


def _reason_contradicts_outcome(
    reason: str, outcome: Optional[VerdictOutcome]
) -> bool:
    if not reason or outcome is None:
        return False
    r = reason.lower()
    reject_markers = (
        "cannot approve",
        "can't approve",
        "insufficient evidence",
        "unresolved",
        "escalat",
        "fraud",
        "high risk",
    )
    approve_markers = (
        "approve",
        "low risk",
        "verified",
        "sufficient evidence",
    )
    if outcome == "APPROVE" and any(m in r for m in reject_markers):
        return True
    if outcome == "REJECT" and any(m in r for m in approve_markers):
        return True
    return False


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


def _update_memory(memory: Dict[str, Any], msg: AgentStructuredMessage) -> None:
    agreed = _memory_list(memory, "agreed_facts")
    disputed = _memory_list(memory, "disputed_points")
    unresolved = _memory_list(memory, "unresolved_checks")

    if msg.stance == "approve":
        _push_unique(agreed, _short(msg.evidence or msg.claim, 120), limit=6)
    elif msg.stance == "reject":
        _push_unique(disputed, _short(msg.claim, 120), limit=6)
    else:
        _push_unique(unresolved, _short(msg.claim or msg.evidence, 120), limit=6)

    for tag in msg.risk_tags:
        if any(k in tag for k in ("unknown", "missing", "unresolved", "high")):
            _push_unique(unresolved, _short(tag, 60), limit=6)

    recent_claims = memory.get("recent_claims")
    if not isinstance(recent_claims, dict):
        recent_claims = {"hermes": [], "nemesis": []}
        memory["recent_claims"] = recent_claims
    role_claims = recent_claims.get(msg.role)
    if not isinstance(role_claims, list):
        role_claims = []
        recent_claims[msg.role] = role_claims
    _push_unique(role_claims, _short(msg.claim, 120), limit=4)

    memory["current_risk_summary"] = _short(
        f"Latest {msg.role} stance={msg.stance}, confidence={msg.confidence:.2f}, "
        f"risk_tags={msg.risk_tags}",
        220,
    )


def _latest_role_turn(
    transcript: List[AgentStructuredMessage], role: AgentRole
) -> Optional[AgentStructuredMessage]:
    for msg in reversed(transcript):
        if msg.role == role:
            return msg
    return None


def _memory_list(memory: Dict[str, Any], key: str) -> List[str]:
    value = memory.get(key)
    if not isinstance(value, list):
        value = []
        memory[key] = value
    return value


def _push_unique(target: List[str], item: str, *, limit: int) -> None:
    i = item.strip()
    if not i:
        return
    if i in target:
        return
    target.append(i)
    if len(target) > limit:
        del target[0 : len(target) - limit]


def _short(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3].rstrip() + "..."


def _text_similarity(a: str, b: str) -> float:
    ta = _token_set(a)
    tb = _token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta.intersection(tb))
    union = len(ta.union(tb))
    if union == 0:
        return 0.0
    return inter / union


def _is_repetitive_turn(
    current: AgentStructuredMessage, previous: AgentStructuredMessage
) -> bool:
    if current.stance != previous.stance:
        return False
    text_sim = _text_similarity(current.text, previous.text)
    claim_sim = _text_similarity(
        f"{current.claim} {current.evidence}",
        f"{previous.claim} {previous.evidence}",
    )
    tags_same = sorted(current.risk_tags) == sorted(previous.risk_tags)
    return (text_sim >= 0.62 and claim_sim >= 0.52) or (
        text_sim >= 0.55 and tags_same and claim_sim >= 0.48
    )


def _token_set(text: str) -> Set[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "are",
        "was",
        "were",
        "but",
        "not",
        "you",
        "your",
        "they",
        "their",
        "will",
        "should",
    }
    return {t for t in tokens if len(t) > 2 and t not in stop}


def _is_uninformative_reason(reason: str) -> bool:
    r = (reason or "").strip()
    if not r:
        return True
    upper = r.upper()
    if upper in {"VERDICT: APPROVE.", "VERDICT: REJECT.", "VERDICT: ESCALATE TO HUMAN."}:
        return True
    if len(r) < 48:
        return True
    if len(re.findall(r"[A-Za-z0-9]+", r)) < 8:
        return True
    if r.endswith(":"):
        return True
    return False


def _clean_verdict_reason(reason: str) -> str:
    text = (reason or "").strip()
    if not text:
        return ""

    # Remove obvious markdown/code formatting artifacts from model output.
    text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Keep a concise but informative explanation: up to two sentences.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if sentences:
        text = " ".join(sentences[:2])

    text = text.strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _build_brief_verdict_reason(
    *,
    outcome: VerdictOutcome,
    transcript: List[AgentStructuredMessage],
    brief: SpecterBrief,
) -> str:
    latest = transcript[-1] if transcript else None
    tags: List[str] = []
    for m in transcript[-4:]:
        tags.extend(m.risk_tags)
    unique_tags = []
    for t in tags:
        if t not in unique_tags:
            unique_tags.append(t)
    tag_text = ", ".join(unique_tags[:2]) if unique_tags else "current debate evidence"

    if outcome == "APPROVE":
        return (
            "The debate supports approval because risk concerns were addressed with "
            "insufficient unresolved indicators in the final rounds."
        )
    if outcome == "REJECT":
        return (
            "The transaction is rejected because material risk indicators remained "
            f"unresolved, especially around {tag_text}."
        )
    source = (
        "conflicting arguments and unresolved checks"
        if latest is None
        else f"conflicting arguments and unresolved checks around {tag_text}"
    )
    if brief.status == "unavailable":
        source += ", with vendor intelligence unavailable"
    return f"The case is escalated due to {source}."
