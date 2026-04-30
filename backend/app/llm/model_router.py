from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.settings import Settings
from app.schemas.debate import ParsedTransaction, SpecterBrief

RiskLevel = Literal["low", "medium", "high"]
Role = Literal["hermes", "nemesis", "verdict"]


@dataclass
class RoutingDecision:
    risk_level: RiskLevel
    hermes_model: str
    nemesis_model: str
    verdict_model: str
    rationale: str


def assess_risk(
    settings: Settings,
    transaction: ParsedTransaction,
    brief: SpecterBrief,
) -> RiskLevel:
    score = 0
    amt = transaction.amount or 0.0
    if amt >= settings.risk_amount_high_threshold:
        score += 3
    elif amt >= settings.risk_amount_medium_threshold:
        score += 2

    if brief.status == "unavailable":
        score += 1
    elif not brief.vendor_found:
        score += 2

    if brief.red_flags:
        score += 2

    if brief.legitimacy_score is not None and brief.legitimacy_score < 0.4:
        score += 1

    if not transaction.reference:
        score += 1

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def route_models(
    settings: Settings,
    transaction: ParsedTransaction,
    brief: SpecterBrief,
) -> RoutingDecision:
    level = assess_risk(settings, transaction, brief)

    if level == "low":
        debater = settings.model_low_risk
        verdict = settings.model_verdict_default
    elif level == "medium":
        debater = settings.model_medium_risk
        verdict = settings.model_verdict_default
    else:
        debater = settings.model_high_risk
        verdict = settings.model_verdict_high_risk

    rationale = (
        f"risk={level}; amount={transaction.amount}; "
        f"vendor_found={brief.vendor_found}; red_flags={len(brief.red_flags)}"
    )

    return RoutingDecision(
        risk_level=level,
        hermes_model=debater,
        nemesis_model=debater,
        verdict_model=verdict,
        rationale=rationale,
    )
