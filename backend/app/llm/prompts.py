from __future__ import annotations

import json
from typing import List

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
    "in real data."
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
    "if the vendor is unknown or has red flags, lead with this."
)

VERDICT_SYSTEM = (
    "You are a neutral financial arbitrator. You have just read a full debate "
    "between Hermes (payment advocate) and Nemesis (payment prosecutor), along "
    "with a Specter intelligence brief on the vendor. Based on the quality of "
    "their arguments, the transaction details, and the Specter data, deliver a "
    "verdict of APPROVE, REJECT, or ESCALATE TO HUMAN. Follow with exactly "
    "one sentence explaining your decision. Be impartial."
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
- Output ONLY the JSON object. Do not wrap it in code fences.
""".strip()


_REPAIR_INSTRUCTION = (
    "Your previous response was not valid JSON matching the required schema. "
    "Reply again with a single valid JSON object only, no markdown, no commentary."
)


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
) -> List[dict]:
    system = HERMES_SYSTEM if role == "hermes" else NEMESIS_SYSTEM
    context = build_context_block(tx, brief)

    debate_history = []
    for msg in transcript:
        speaker = "Hermes" if msg.role == "hermes" else "Nemesis"
        debate_history.append(f"[Round {msg.round}] {speaker}: {msg.text}")
    history_block = "\n".join(debate_history) if debate_history else "(no prior turns)"

    user_content = (
        f"{context}\n\n"
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
) -> List[dict]:
    base = build_agent_messages(role, tx, brief, transcript, current_round)
    base.append({"role": "assistant", "content": bad_response})
    base.append({"role": "user", "content": _REPAIR_INSTRUCTION})
    return base


def build_verdict_messages(
    tx: ParsedTransaction,
    brief: SpecterBrief,
    transcript: List[AgentStructuredMessage],
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
        "FULL DEBATE TRANSCRIPT (in order):\n"
        + "\n".join(transcript_lines)
        + "\n\nSTRUCTURED EVIDENCE PER TURN:\n"
        + structured_dump
        + "\n\nReply with EXACTLY this format and nothing else:\n"
        "VERDICT: <APPROVE|REJECT|ESCALATE TO HUMAN>\n"
        "REASON: <one sentence>"
    )

    return [
        {"role": "system", "content": VERDICT_SYSTEM},
        {"role": "user", "content": user_content},
    ]
