# GridWise — LLM-Assisted Energy Optimizer

BUP CSE Fest 2026 Hackathon — Online Preliminary submission.

HTTP API that interprets natural-language campus operator notes with an LLM, deterministically validates the extracted directives, and solves a 24-hour battery/grid/solar linear program for a cost-minimal energy schedule.

**Live endpoint**: https://gridwise-tmng.onrender.com (`GET /health`, `POST /optimize-energy`)

## Architecture

```
Energy Data + Operator Notes
        |
        v
  LLM Interpreter  (Groq / Gemini — batched single call for all notes)
        |
        v
  Guardrail Validator  (deterministic; self-heals or downgrades to no_op)
        |
        v
  Math Optimizer  (scipy.optimize.linprog, HiGHS — 24h LP)
        |
        v
  Final Replay Validator  (independent constraint check + authoritative totals)
        |
        v
  API Response
```

The LLM is used only to interpret `operator_notes` into structured directives — never to compute the schedule or write `plan_summary`. Its raw output is untrusted until it passes the guardrail layer.

## Tech stack

FastAPI + Pydantic v2 (API contract) · scipy.optimize.linprog / HiGHS (optimizer, no external solver binary) · httpx (LLM REST calls) · Groq + Gemini (LLM providers).

## Environment variables

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `groq` (default) or `gemini` — which provider is tried first. |
| `GEMINI_API_KEY` | Google Gemini key (https://aistudio.google.com/apikey). |
| `GEMINI_MODEL` | Default `gemini-2.5-flash`. |
| `GROQ_API_KEY` | Groq key (https://console.groq.com/keys). |
| `GROQ_MODEL` | Primary Groq model, default `openai/gpt-oss-20b`. |
| `GROQ_FALLBACK_MODEL` | Secondary Groq model on a separate rate-limit bucket, default `allam-2-7b`. |
| `PORT` | Bind port, default `8000`. |

No secret values are committed. Copy `.env.example` to `.env` and fill in your own keys.

## Local quickstart

```bash
git clone https://github.com/Tariq-15/Gridwise.git
cd Gridwise
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # fill in GEMINI_API_KEY / GROQ_API_KEY
uvicorn app.main:app --reload
```

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Regression harness against the 10 public sample cases:

```bash
python tests/regression/run_public_samples.py http://localhost:8000
```

Manual smoke test (health + one sample request): `scripts/smoke_test.sh`

### Example `/optimize-energy` request

```bash
bash scripts/smoke_test.sh http://localhost:8000
```

## Docker

```bash
docker build -t gridwise:local .
docker run --rm -p 8000:8000 -e LLM_PROVIDER=groq -e GROQ_API_KEY=your-key-here gridwise:local
curl http://localhost:8000/health
```

Published fallback image: `tariquzzaman01/gridwise:v1-c2af3b1`
(digest `sha256:27a6832fcf6e65b6ac2545cf68f40054b8718e4acf8a4f382abe921da757c18b`, also `:latest`).

```bash
docker pull tariquzzaman01/gridwise:v1-c2af3b1
docker run --rm -p 8000:8000 -e LLM_PROVIDER=groq -e GROQ_API_KEY=your-key-here tariquzzaman01/gridwise:v1-c2af3b1
curl http://localhost:8000/health
```

## LLM provider strategy

- Primary: Groq `openai/gpt-oss-20b` (`reasoning_effort=low`), OpenAI-compatible `chat/completions` with `response_format={"type":"json_object"}`.
- Secondary: Groq `allam-2-7b` — a separate model on a separate rate-limit bucket.
- Tertiary: Gemini, best-effort.
- All 1–3 notes go in a single batched call per request. Only `battery.capacity_kwh` is sent alongside the notes — never the hourly demand/solar/tariff arrays — so the model has no data surface to invent changes to.
- Total provider failure degrades every note to `no_op`; the service still returns `200` with a valid schedule.

## Guardrails

`app/guardrails/validator.py` checks every LLM output entry before it reaches the optimizer: allowed directive types, `note_index` completeness/uniqueness, applies/no_op consistency, structured_adjustment shape per type, numeric ranges (solar factor 0–1, non-negative reserves/caps), and self-heals unsorted/duplicate hour lists. Anything unfixable is downgraded to `no_op` — never a new invented type, never a crash.

## Optimizer

24-hour linear program (120 variables: grid, solar-used, charge, discharge, battery-energy per hour) minimizing `Σ grid[h]·tariff[h]` subject to energy balance, battery/rate limits, active directive constraints, and end-of-day neutrality. A tiny tie-break term plus a post-solve netting step resolves simultaneous charge/discharge. If the LP fails, a deterministic fallback scheduler guarantees a valid response instead of a 500.

## Known limitations

- If both Groq models are rate-limited and Gemini also fails, that request's notes degrade to `no_op` (schedule stays valid, loses interpretation credit for that request only).
- The fallback scheduler (used only if the LP itself fails) is not guaranteed cost-optimal.
- `422` validation is intentionally narrow (battery energy bounds only) — optional per the Problem Statement.
- Render's free tier may spin down when idle; the first request after inactivity can be slower than the p95 target.

## Security

- No secrets committed (`.env` gitignored; `.env.example` has names only).
- Logs redact configured secret values.
- Docker image has no baked-in credentials — keys are runtime env vars only.
- The global exception handler never returns a stack trace or internal detail.
