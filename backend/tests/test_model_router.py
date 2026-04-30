from app.core.settings import Settings
from app.llm.model_router import assess_risk, route_models
from app.schemas.debate import ParsedTransaction, SpecterBrief


def _settings() -> Settings:
    return Settings(
        OPENROUTER_API_KEY="x",
        SPECTER_API_KEY="y",
        MODEL_LOW_RISK="low",
        MODEL_MEDIUM_RISK="med",
        MODEL_HIGH_RISK="hi",
        MODEL_VERDICT_DEFAULT="vd",
        MODEL_VERDICT_HIGH_RISK="vd-hi",
        RISK_AMOUNT_MEDIUM_THRESHOLD=5000,
        RISK_AMOUNT_HIGH_THRESHOLD=20000,
    )


def _brief(found: bool = True, status: str = "available", red_flags=None, score=0.7):
    return SpecterBrief(
        status=status,  # type: ignore[arg-type]
        summary="x",
        vendor_found=found,
        legitimacy_score=score,
        red_flags=red_flags or [],
    )


def test_low_risk_clean_small():
    s = _settings()
    tx = ParsedTransaction(raw="x", vendor="acme", amount=200.0, reference="r")
    assert assess_risk(s, tx, _brief()) == "low"
    decision = route_models(s, tx, _brief())
    assert decision.hermes_model == "low"
    assert decision.verdict_model == "vd"


def test_high_risk_unknown_vendor_large_amount():
    s = _settings()
    tx = ParsedTransaction(raw="x", vendor="unknown", amount=47000.0, reference=None)
    brief = _brief(found=False, score=0.4)
    assert assess_risk(s, tx, brief) == "high"
    decision = route_models(s, tx, brief)
    assert decision.hermes_model == "hi"
    assert decision.verdict_model == "vd-hi"


def test_medium_risk_mid_amount_known_vendor():
    s = _settings()
    tx = ParsedTransaction(raw="x", vendor="acme", amount=8500.0, reference="r")
    brief = _brief(found=True, score=0.7)
    assert assess_risk(s, tx, brief) == "medium"
