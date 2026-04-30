from app.llm.prompts import build_agent_messages, build_verdict_messages
from app.schemas.debate import AgentStructuredMessage, ParsedTransaction, SpecterBrief


def _tx() -> ParsedTransaction:
    return ParsedTransaction(
        raw="04/30 BRIEFCASE TECHNOLOGIES 8500.00 GBP REF:INV-Q1-LICENSE ...",
        vendor="BRIEFCASE TECHNOLOGIES",
        amount=8500.0,
        currency="GBP",
        reference="INV-Q1-LICENSE",
    )


def _brief() -> SpecterBrief:
    return SpecterBrief(
        status="available",
        summary="No record of this vendor found in Specter.",
        vendor_found=False,
        red_flags=[],
    )


def _transcript() -> list[AgentStructuredMessage]:
    msgs = []
    for i in range(1, 5):
        msgs.append(
            AgentStructuredMessage(
                role="hermes" if i % 2 else "nemesis",
                round=i,
                stance="approve" if i % 2 else "reject",
                claim=f"claim-{i}",
                evidence=f"evidence-{i}",
                counterpoint=f"counter-{i}",
                risk_tags=["unknown_vendor"] if i % 2 == 0 else [],
                confidence=0.6,
                text=f"round-{i} text",
                structured_available=True,
            )
        )
    return msgs


def _memory() -> dict:
    return {
        "agreed_facts": ["fact-a"],
        "disputed_points": ["dispute-a"],
        "unresolved_checks": ["missing_contract", "unknown_vendor"],
        "current_risk_summary": "high uncertainty persists",
    }


def test_debater_context_uses_memory_and_latest_turns_only():
    msgs = build_agent_messages(
        role="hermes",
        tx=_tx(),
        brief=_brief(),
        transcript=_transcript(),
        current_round=5,
        memory=_memory(),
        history_turn_limit=2,
    )
    assert len(msgs) == 2
    user_content = msgs[1]["content"]
    assert "ROLLING MEMORY STATE" in user_content
    assert "missing_contract" in user_content
    # only latest two rounds should appear
    assert "[Round 4]" in user_content
    assert "[Round 3]" in user_content
    assert "[Round 1]" not in user_content


def test_verdict_context_contains_full_transcript_and_memory():
    transcript = _transcript()
    msgs = build_verdict_messages(
        tx=_tx(),
        brief=_brief(),
        transcript=transcript,
        memory=_memory(),
    )
    user_content = msgs[1]["content"]
    assert "FINAL ROLLING MEMORY STATE" in user_content
    assert "[Round 1]" in user_content
    assert "[Round 4]" in user_content
    assert "STRUCTURED EVIDENCE PER TURN" in user_content
