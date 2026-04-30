import json

import pytest

from app.core.settings import Settings
from app.llm.model_router import RoutingDecision
from app.schemas.debate import ParsedTransaction, SpecterBrief
from app.services.debate_orchestrator import DebateOrchestrator, _OrchestratorContext
from app.schemas.debate import AgentStructuredMessage
from app.services.debate_orchestrator import (
    _build_brief_verdict_reason,
    _is_repetitive_turn,
    _is_uninformative_reason,
    _parse_verdict,
    _safe_parse_structured,
)


def test_safe_parse_structured_valid_json():
    raw = json.dumps(
        {
            "stance": "approve",
            "claim": "AWS is a known cloud provider.",
            "evidence": "Specter confirms AWS is a global infrastructure brand.",
            "counterpoint": "Even Nemesis cannot deny AWS legitimacy.",
            "risk_tags": [],
            "confidence": 0.9,
            "text": "AWS is legitimate. Reference matches an invoice format. Amount is small. Approve.",
        }
    )
    msg = _safe_parse_structured(raw, "hermes", 1)
    assert isinstance(msg, AgentStructuredMessage)
    assert msg.stance == "approve"
    assert msg.confidence == 0.9
    assert msg.role == "hermes"


def test_safe_parse_structured_strips_code_fences():
    raw = "```json\n" + json.dumps(
        {
            "stance": "reject",
            "claim": "Unknown vendor.",
            "evidence": "Specter has no record.",
            "counterpoint": "Specter is the source of truth.",
            "risk_tags": ["unknown_vendor"],
            "confidence": 0.8,
            "text": "Vendor is not in Specter. Amount is high. Recommend rejection. No documentation supports it.",
        }
    ) + "\n```"
    msg = _safe_parse_structured(raw, "nemesis", 2)
    assert msg is not None
    assert msg.stance == "reject"
    assert "unknown_vendor" in msg.risk_tags


def test_safe_parse_structured_rejects_invalid():
    assert _safe_parse_structured("not json", "hermes", 1) is None
    assert _safe_parse_structured("{}", "hermes", 1) is None


def test_parse_verdict_explicit_format():
    decision = _parse_verdict("VERDICT: APPROVE\nREASON: Amount is small and vendor verified.")
    assert decision.outcome == "APPROVE"
    assert "vendor" in decision.reason.lower()


def test_parse_verdict_escalate_default():
    decision = _parse_verdict("Some unstructured noise without keywords.")
    assert decision.outcome == "ESCALATE TO HUMAN"


def test_parse_verdict_reject_inline():
    decision = _parse_verdict(
        "VERDICT: REJECT\nREASON: Unknown vendor with multiple anomalies."
    )
    assert decision.outcome == "REJECT"
    assert decision.reason.endswith(".")


def test_parse_verdict_contradictory_reason_defaults_to_escalate():
    decision = _parse_verdict(
        "VERDICT: APPROVE\n"
        "REASON: We cannot approve because evidence is unresolved and high risk."
    )
    assert decision.outcome == "ESCALATE TO HUMAN"
    assert "inconsistent" in decision.reason.lower()


def test_parse_verdict_missing_verdict_line_defaults_to_escalate():
    decision = _parse_verdict("REASON: Data is conflicting so this needs human review.")
    assert decision.outcome == "ESCALATE TO HUMAN"


def test_is_uninformative_reason_detects_placeholder_text():
    assert _is_uninformative_reason("VERDICT: APPROVE.")
    assert _is_uninformative_reason("")
    assert not _is_uninformative_reason("Evidence is mixed and unresolved so this needs review.")


def test_is_repetitive_turn_detects_near_duplicate():
    prev = AgentStructuredMessage(
        role="hermes",
        round=1,
        stance="approve",
        claim="AWS is legitimate and amount is normal.",
        evidence="Specter and invoice pattern support legitimacy.",
        counterpoint="Nemesis overstates risk.",
        risk_tags=["moderate_legitimacy"],
        confidence=0.72,
        text="AWS is legitimate and amount is normal for monthly cloud operations.",
        structured_available=True,
    )
    cur = AgentStructuredMessage(
        role="hermes",
        round=2,
        stance="approve",
        claim="AWS is legitimate and the amount is normal.",
        evidence="Specter and invoice pattern support legitimacy.",
        counterpoint="Nemesis still overstates risk.",
        risk_tags=["moderate_legitimacy"],
        confidence=0.73,
        text="AWS is legitimate and this amount is normal for monthly cloud operations.",
        structured_available=True,
    )
    assert _is_repetitive_turn(cur, prev)


def test_build_brief_verdict_reason_escalate():
    msg = AgentStructuredMessage(
        role="nemesis",
        round=1,
        stance="escalate",
        claim="Unresolved vendor evidence remains.",
        evidence="No firm proof of service delivery.",
        counterpoint="Hermes relies on assumptions.",
        risk_tags=["unknown_vendor"],
        confidence=0.64,
        text="Evidence remains unresolved.",
        structured_available=True,
    )
    reason = _build_brief_verdict_reason(
        outcome="ESCALATE TO HUMAN",
        transcript=[msg],
        brief=SpecterBrief(
            status="available",
            summary="x",
            vendor_found=True,
            red_flags=[],
        ),
    )
    assert "escalated" in reason.lower()


class _FakeOpenRouter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def complete(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return "{}"


def _ctx() -> _OrchestratorContext:
    return _OrchestratorContext(
        trace_id="t1",
        transaction=ParsedTransaction(raw="x", vendor="ACME"),
        brief=SpecterBrief(
            status="available",
            summary="ok",
            vendor_found=True,
            red_flags=[],
        ),
        routing=RoutingDecision(
            risk_level="low",
            hermes_model="m1",
            nemesis_model="m1",
            verdict_model="m2",
            rationale="test",
        ),
        transcript=[],
        escalation_email=None,
        memory={
            "agreed_facts": [],
            "disputed_points": [],
            "unresolved_checks": [],
            "current_risk_summary": "init",
        },
    )


@pytest.mark.asyncio
async def test_strict_retry_path_invalid_then_valid():
    valid = json.dumps(
        {
            "stance": "approve",
            "claim": "Valid claim.",
            "evidence": "transaction supports this.",
            "counterpoint": "direct reply.",
            "risk_tags": [],
            "confidence": 0.77,
            "text": "Short valid text. It is grounded. It responds. It concludes.",
        }
    )
    fake = _FakeOpenRouter(["not json", valid])
    settings = Settings(OPENROUTER_API_KEY="x", STRUCTURED_RETRY_ATTEMPTS=2)
    orch = DebateOrchestrator(settings=settings, openrouter=fake)
    msg = await orch._produce_agent_turn(_ctx(), "hermes", 1)
    assert msg.structured_available is True
    assert msg.stance == "approve"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_invalid_after_max_retries_falls_back_schema_failure():
    fake = _FakeOpenRouter(["not json", "still bad", "also bad"])
    settings = Settings(OPENROUTER_API_KEY="x", STRUCTURED_RETRY_ATTEMPTS=2)
    orch = DebateOrchestrator(settings=settings, openrouter=fake)
    msg = await orch._produce_agent_turn(_ctx(), "nemesis", 1)
    assert msg.stance == "escalate"
    assert msg.structured_available is False
    assert "schema_failure" in msg.risk_tags
    assert fake.calls == 3
