# Agora

A two-agent adversarial payment authorisation system.

- **Hermes** argues FOR approval (commercial, good faith).
- **Nemesis** argues AGAINST approval (forensic, skeptical).
- **Verdict** reads the full debate and returns `APPROVE`, `REJECT`, or `ESCALATE TO HUMAN`.

The frontend streams the debate in real time over Server-Sent Events. The
backend enriches the transaction with Specter vendor intelligence before the
debate begins, and selects the LLM per role based on a risk-aware model router.
Final outcomes are fully model-driven — there are no deterministic override
rules.

## Repo layout

```
backend/   FastAPI app, debate orchestrator, Specter + OpenRouter clients
frontend/  React + Vite UI with SSE streaming and live debate columns
```

## Prerequisites

- Python 3.11+ (3.13 / 3.14 also work)
- Node.js 18+
- An OpenRouter API key (`OPENROUTER_API_KEY`)
- A Specter API key (`SPECTER_API_KEY`) — optional; the debate continues if Specter is unavailable

## Setup

```bash
# 1. Copy env template
cp .env.example backend/.env

# 2. Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

## Environment variables

All keys load from environment variables — none are hardcoded. See
[`.env.example`](./.env.example) for the canonical list. Highlights:

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Required. Used for all Hermes / Nemesis / Verdict LLM calls. |
| `SPECTER_API_KEY` | Optional. Enables vendor intelligence enrichment. |
| `MODEL_LOW_RISK` / `MODEL_MEDIUM_RISK` / `MODEL_HIGH_RISK` | Per-tier OpenRouter model IDs for debaters. |
| `MODEL_VERDICT_DEFAULT` / `MODEL_VERDICT_HIGH_RISK` | Verdict model IDs by tier. |
| `RISK_AMOUNT_MEDIUM_THRESHOLD` / `RISK_AMOUNT_HIGH_THRESHOLD` | Amount cutoffs that drive risk tier. |
| `DEBATE_MAX_ROUNDS` | Hard cap on debate rounds (defaults to 6, capped at 6). |
| `CORS_ORIGINS` | Comma-separated origins allowed by FastAPI CORS. |

## API

`POST /debate` — accepts:

```json
{
  "raw_transaction": "04/30 AMAZON WEB SERVICES 340.00 GBP REF:INV-AWS-9923 ...",
  "max_rounds": 6,
  "escalation_email": "ops@example.com"
}
```

Streams `text/event-stream` with these event types:

- `status` — orchestration progress, parsed transaction, routing decision
- `specter_brief` — vendor intelligence summary
- `agent_message` — a structured Hermes or Nemesis turn
- `round_state` — round start/end markers
- `verdict` — final outcome + one-sentence reason (+ escalation packet if needed)
- `error` — terminal error
- `done` — stream closed

Every event is wrapped in an `SseEnvelope` with `event_id`, `trace_id`,
`event_type`, `timestamp`, and `payload`.

## Demo transactions

Three preload buttons on the UI map to:

1. **Clean** — `04/30 AMAZON WEB SERVICES 340.00 GBP REF:INV-AWS-9923 Monthly cloud infrastructure`
2. **Fraud** — `04/30 NEXUS CAPITAL SOLUTIONS LTD 47000.00 GBP REF:INV-2281 Consultancy services`
3. **Ambiguous** — `04/30 BRIEFCASE TECHNOLOGIES 8500.00 GBP REF:INV-Q1-LICENSE Q1 platform licensing end of quarter reconciliation`

## Architecture summary

- **Transaction parser** (regex-based) extracts vendor, amount, currency, date, reference.
- **Specter client** searches for the vendor and pulls a detailed company record; failures degrade to a neutral "intelligence unavailable" brief.
- **Model router** computes a risk score from amount tier, vendor presence, red flags, legitimacy score, and reference completeness, then picks per-role models from config.
- **Debate orchestrator** alternates Hermes → Nemesis per round, validates each turn against a structured schema (with one repair retry, then text-only fallback), and stops early when both agents repeat their stance with stable, non-low confidence across two consecutive rounds.
- **Verdict** reads the parsed transaction, Specter brief, structured per-turn evidence, and the prose transcript, then emits `APPROVE | REJECT | ESCALATE TO HUMAN` with a one-sentence reason. Escalations include a reviewer handoff packet (transaction, Specter brief, last two turns, rationale).

## Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest tests -q
```

Currently covers transaction parsing, confidence label mapping, model routing,
structured-message parsing (including code-fence stripping), and verdict text
parsing.

## Notes

- PDF input is intentionally deferred for v1 — only the text input flow is wired up.
- No persistence — every `/debate` call is request-scoped.
- Adaptive stopping caps at 6 rounds and exits early on stance + confidence convergence.
