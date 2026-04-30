from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


VerdictOutcome = Literal["APPROVE", "REJECT", "ESCALATE TO HUMAN"]
AgentRole = Literal["hermes", "nemesis"]
Stance = Literal["approve", "reject", "escalate"]
SseEventType = Literal[
    "status",
    "specter_brief",
    "agent_message",
    "round_state",
    "verdict",
    "error",
    "done",
]


class DebateRequest(BaseModel):
    raw_transaction: str = Field(min_length=1)
    max_rounds: int = Field(default=6, ge=1, le=6)
    escalation_email: Optional[str] = None


class ParsedTransaction(BaseModel):
    raw: str
    date: Optional[str] = None
    vendor: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class SpecterBrief(BaseModel):
    status: Literal["available", "unavailable"]
    summary: str
    vendor_found: bool = False
    vendor_name: Optional[str] = None
    domain: Optional[str] = None
    founded_year: Optional[int] = None
    legitimacy_score: Optional[float] = None
    red_flags: List[str] = Field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None


class AgentStructuredMessage(BaseModel):
    role: AgentRole
    round: int = Field(ge=1)
    stance: Stance
    claim: str
    evidence: str
    counterpoint: str
    risk_tags: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    text: str
    structured_available: bool = True

    @field_validator("confidence")
    @classmethod
    def _round_confidence(cls, v: float) -> float:
        return round(float(v), 4)


class VerdictDecision(BaseModel):
    outcome: VerdictOutcome
    reason: str
    escalation_packet: Optional[Dict[str, Any]] = None


class SseEnvelope(BaseModel):
    event_id: str
    trace_id: str
    event_type: SseEventType
    timestamp: str
    payload: Dict[str, Any]
