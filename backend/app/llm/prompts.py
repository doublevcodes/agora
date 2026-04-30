from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.schemas.debate import (
    AgentRole,
    AgentStructuredMessage,
    ParsedTransaction,
    SpecterBrief,
)


HERMES_SYSTEM = (
    "You are Hermes, an AI payment advocate. Your role is to argue FOR the "
    "approval of financial transactions. You assume good faith, find legitimate "
    "explanations for anomalies, and build the strongest possible case for "
    "payment. You are persuasive, confident, and commercially minded. You may "
    "concede minor points but always push toward approval. Keep responses to "
    "3-4 sentences maximum. You are in a live debate with Nemesis, who argues "
    "against payment. Respond directly to their points. You have been given a "
    "Specter intelligence brief on the vendor — use it to ground your arguments "
    "in real data. For each turn, make your reasoning explicit: (1) claim, "
    "(2) strongest evidence, (3) rebuttal to Nemesis, (4) unresolved risk check. "
    "Avoid generic policy language; tie every major point to transaction, "
    "Specter, or opponent statements. Critically, each new turn MUST introduce a "
    "NEW concrete point or evidence not raised in your previous turns — do not "
    "repeat or rephrase prior arguments. If you have nothing materially new to "
    "add, concede that point and pivot to a different supporting angle."
)

NEMESIS_SYSTEM = (
    "You are Nemesis, an AI payment prosecutor. Your role is to argue AGAINST "
    "financial transactions unless they are unimpeachable. You assume bad "
    "faith, find anomalies, and build the strongest possible case for "
    "rejection or escalation. You are forensic, skeptical, and relentless. "
    "You may acknowledge Hermes makes valid points but always push toward "
    "rejection. Keep responses to 3-4 sentences maximum. You are in a live "
    "debate with Hermes, who argues for payment. Respond directly to their "
    "points. You have been given a Specter intelligence brief on the vendor — "
    "if the vendor is unknown or has red flags, lead with this. For each turn, "
    "make your reasoning explicit: (1) claim, (2) strongest evidence, (3) "
    "rebuttal to Hermes, (4) unresolved risk check. Avoid generic policy "
    "language; tie every major point to transaction, Specter, or opponent "
    "statements. CRITICAL: each new turn MUST raise a NEW specific risk or "
    "evidence gap not in your previous turns — do not repeat the same concern. "
    "If you cannot identify a new specific risk, concede the point and lower "
    "your confidence rather than rephrasing. Only invoke red flags backed by "
    "Specter facts, not speculation."
)

VERDICT_SYSTEM = (
    "You are a neutral financial arbitrator. You have just read a full debate "
    "between Hermes (payment advocate) and Nemesis (payment prosecutor), along "
    "with a Specter intelligence brief on the vendor. Based on the quality of "
    "their arguments, the transaction details, and the Specter data, deliver a "
    "verdict of APPROVE, REJECT, or ESCALATE TO HUMAN. Weigh evidence quality, "
    "not the volume or persistence of disagreement. Disagreement alone is not a "
    "reason to escalate; only escalate when there is a MATERIAL unresolved fact "
    "(e.g., unverifiable vendor, missing documentation, unexplained anomaly) "
    "that could change the decision. If Hermes presents concrete evidence and "
    "Nemesis only raises generic skepticism without specific risks tied to this "
    "transaction, lean APPROVE. If Nemesis identifies a clear, specific risk "
    "that Hermes cannot rebut with facts, lean REJECT. Internally arbitrate by "
    "identifying the strongest Hermes point, strongest Nemesis point, and any "
    "unresolved critical uncertainty before deciding. Follow with exactly one "
    "sentence explaining your decision. Be impartial."
)


_STRUCTURED_FORMAT_INSTRUCTION = """
You MUST reply with a single JSON object (no markdown fences, no commentary)
that conforms to this exact schema:

{
  "stance": "approve" | "reject" | "escalate",
  "claim": "1-2 sentence summary of your position this turn",
  "evidence": "specific fact(s) referencing the transaction, Specter brief, or prior debate point",
  "counterpoint": "direct response to your opponent's most recent argument",
  "risk_tags": ["short", "snake_case", "tags"],
  "confidence": 0.0,
  "text": "the 3-4 sentence argument the user will see"
}

Rules:
- confidence is a float between 0.0 and 1.0.
- risk_tags must be a JSON array of short snake_case strings (use [] if none).
- text must be 3-4 sentences and reflect the same stance.
- include an unresolved risk check inside text and/or evidence.
- avoid repeating prior wording; add at least one new concrete point each turn.
- Output ONLY the JSON object. Do not wrap it in code fences.
""".strip()


_REPAIR_INSTRUCTION = (
    "Your previous response was not valid JSON matching the required schema. "
    "Reply again with a single valid JSON object only, no markdown, no commentary."
)
_REPAIR_INSTRUCTION_COMPACT = (
    "Return ONLY valid JSON with keys: stance, claim, evidence, counterpoint, "
    "risk_tags, confidence, text. No markdown, no extra keys."
)

_DEBATER_MAX_TURN_CHARS = 380
_DEBATER_MAX_MEMORY_ITEMS = 4


def _trim(text: str, max_chars: int) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3].rstrip() + "..."


def _format_transaction(tx: ParsedTransaction) -> str:
    parts = [f"Raw line: {tx.raw}", f"Vendor: {tx.vendor}"]
    if tx.amount is not None:
        parts.append(f"Amount: {tx.amount}")
    if tx.currency:
        parts.append(f"Currency: {tx.currency}")
    if tx.date:
        parts.append(f"Date: {tx.date}")
    if tx.reference:
        parts.append(f"Reference: {tx.reference}")
    if tx.notes:
        parts.append(f"Notes: {tx.notes}")
    return "\n".join(parts)


def build_context_block(tx: ParsedTransaction, brief: SpecterBrief) -> str:
    return (
        "TRANSACTION DETAILS:\n"
        f"{_format_transaction(tx)}\n\n"
        "SPECTER INTELLIGENCE BRIEF:\n"
        f"{brief.summary}"
    )


def build_agent_messages(
    role: AgentRole,
    tx: ParsedTransaction,
    brief: SpecterBrief,
    transcript: List[AgentStructuredMessage],
    current_round: int,
    memory: Optional[Dict[str, Any]] = None,
    history_turn_limit: int = 2,
) -> List[dict]:
    system = HERMES_SYSTEM if role == "hermes" else NEMESIS_SYSTEM
    context = build_context_block(tx, brief)

    recent = transcript[-history_turn_limit:] if history_turn_limit > 0 else []
    debate_history = []
    for msg in recent:
        speaker = "Hermes" if msg.role == "hermes" else "Nemesis"
        debate_history.append(
            f"[Round {msg.round}] {speaker} "
            f"(stance={msg.stance}, confidence={msg.confidence:.2f}, "
            f"risk_tags={msg.risk_tags}): {_trim(msg.text, _DEBATER_MAX_TURN_CHARS)}"
        )
    history_block = "\n".join(debate_history) if debate_history else "(no prior turns)"
    memory_block = _format_memory(memory)

    user_content = (
        f"{context}\n\n"
        f"ROLLING MEMORY STATE:\n{memory_block}\n\n"
        f"DEBATE SO FAR:\n{history_block}\n\n"
        f"It is now Round {current_round}. You are "
        f"{'Hermes' if role == 'hermes' else 'Nemesis'}.\n\n"
        f"{_STRUCTURED_FORMAT_INSTRUCTION}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def build_repair_messages(
    role: AgentRole,
    tx: ParsedTransaction,
    brief: SpecterBrief,
    transcript: List[AgentStructuredMessage],
    current_round: int,
    bad_response: str,
    memory: Optional[Dict[str, Any]] = None,
    repair_round: int = 1,
) -> List[dict]:
    base = build_agent_messages(
        role, tx, brief, transcript, current_round, memory=memory
    )
    base.append({"role": "assistant", "content": bad_response})
    repair_instruction = (
        _REPAIR_INSTRUCTION if repair_round <= 1 else _REPAIR_INSTRUCTION_COMPACT
    )
    base.append({"role": "user", "content": repair_instruction})
    return base


def build_novelty_retry_messages(
    role: AgentRole,
    tx: ParsedTransaction,
    brief: SpecterBrief,
    transcript: List[AgentStructuredMessage],
    current_round: int,
    bad_response: str,
    previous_turn_text: str,
    memory: Optional[Dict[str, Any]] = None,
) -> List[dict]:
    base = build_agent_messages(
        role, tx, brief, transcript, current_round, memory=memory
    )
    base.append({"role": "assistant", "content": bad_response})
    base.append(
        {
            "role": "user",
            "content": (
                "Your previous answer repeats prior arguments too closely. "
                "Reply again with VALID JSON only, but introduce at least one "
                "materially new point not present in this prior turn:\n"
                f"{_trim(previous_turn_text, 420)}\n"
                "Keep stance if needed, but add fresh evidence/counterpoint."
            ),
        }
    )
    return base


def build_verdict_messages(
    tx: ParsedTransaction,
    brief: SpecterBrief,
    transcript: List[AgentStructuredMessage],
    memory: Optional[Dict[str, Any]] = None,
) -> List[dict]:
    context = build_context_block(tx, brief)

    transcript_lines = []
    for msg in transcript:
        speaker = "Hermes" if msg.role == "hermes" else "Nemesis"
        transcript_lines.append(
            f"[Round {msg.round}] {speaker} (stance={msg.stance}, "
            f"confidence={msg.confidence:.2f}, risk_tags={msg.risk_tags}): "
            f"{msg.text}"
        )
    structured_dump = json.dumps(
        [m.model_dump() for m in transcript], indent=2, default=str
    )

    user_content = (
        f"{context}\n\n"
        f"FINAL ROLLING MEMORY STATE:\n{_format_memory(memory)}\n\n"
        "FULL DEBATE TRANSCRIPT (in order):\n"
        + "\n".join(transcript_lines)
        + "\n\nSTRUCTURED EVIDENCE PER TURN:\n"
        + structured_dump
        + "\n\nReply with EXACTLY this format and nothing else:\n"
        "VERDICT: <APPROVE|REJECT|ESCALATE TO HUMAN>\n"
        "REASON: <one concise sentence summarizing why>\n"
        "Important:\n"
        "- VERDICT must be exactly one of APPROVE, REJECT, ESCALATE TO HUMAN.\n"
        "- Disagreement alone is NOT a reason to escalate.\n"
        "- Escalate only if there is a MATERIAL unresolved fact (e.g., unverifiable vendor, missing documentation, unexplained anomaly).\n"
        "- If Hermes provides concrete vendor/transaction evidence and Nemesis only raises generic skepticism, lean APPROVE.\n"
        "- If Nemesis identifies a specific risk that Hermes cannot rebut with facts, lean REJECT.\n"
        "- The REASON must reference the specific transaction/vendor or unresolved fact, not just outcome.\n"
        "- Output only these two lines."
    )

    return [
        {"role": "system", "content": VERDICT_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def _format_memory(memory: Optional[Dict[str, Any]]) -> str:
    if not memory:
        return "(memory empty)"
    agreed = _format_memory_list(memory.get("agreed_facts", []))
    disputed = _format_memory_list(memory.get("disputed_points", []))
    unresolved = _format_memory_list(memory.get("unresolved_checks", []))
    summary = _trim(str(memory.get("current_risk_summary", "(none)")), 220)
    recent_claims = _format_recent_claims(memory.get("recent_claims", {}))
    return (
        f"- agreed_facts: {agreed}\n"
        f"- disputed_points: {disputed}\n"
        f"- unresolved_checks: {unresolved}\n"
        f"- current_risk_summary: {summary}\n"
        f"- recent_claims: {recent_claims}"
    )


def _format_memory_list(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "(none)"
    trimmed = [_trim(str(i), 120) for i in items[:_DEBATER_MAX_MEMORY_ITEMS]]
    return "; ".join(trimmed)


def _format_recent_claims(value: Any) -> str:
    if not isinstance(value, dict):
        return "(none)"
    hermes = value.get("hermes", [])
    nemesis = value.get("nemesis", [])
    h = _format_memory_list(hermes)
    n = _format_memory_list(nemesis)
    return f"hermes=[{h}] nemesis=[{n}]"
