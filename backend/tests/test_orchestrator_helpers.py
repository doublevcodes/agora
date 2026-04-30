import json

from app.schemas.debate import AgentStructuredMessage
from app.services.debate_orchestrator import (
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
