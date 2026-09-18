# GridWise — LLM-Assisted Energy Optimizer

BUP CSE Fest 2026 Hackathon — Online Preliminary submission.

One HTTP API service that interprets natural-language campus operator notes with an LLM, deterministically validates the extracted directives, and solves a 24-hour battery/grid/solar linear program to return a valid, cost-minimal energy schedule.

**Live endpoint**: https://gridwise-tmng.onrender.com
(`GET /health`, `POST /optimize-energy`)

## Architecture

```
Energy Data + Operator Notes
        |
        v
  LLM Interpreter  (Gemini / Groq — batched single call for all notes)
        |
        v
  Guardrail Validator  (deterministic; self-heals fixable issues,
                         downgrades anything unsupported to no_op;
                         never invents a directive type; never crashes)
        |
        v
  Math Optimizer  (scipy.optimize.linprog, HiGHS — 24h LP)
        |
        v
  Final Replay Validator  (independent hour-by-hour constraint check +
                            authoritative totals; falls back to a
                            deterministic heuristic if the LP ever fails)
        |
        v
  API Response
```

The LLM is used **only** to interpret `operator_notes` into structured directives — never to compute the schedule or write `plan_summary` (which is generated deterministically). Its raw output is treated as untrusted data until it passes the guardrail layer.

## Tech stack

- **FastAPI** + **Pydantic v2** — API contract, request/response schemas.
- **scipy.optimize.linprog (HiGHS)** — the 24-hour scheduling LP. No external solver binary (unlike CBC/OR-Tools), which removes a class of Docker packaging risk.
- **httpx** — plain REST calls to both LLM providers (no heavyweight provider SDKs).
- **Gemini** and **Groq** — pluggable LLM providers (see below).

## Environment variables

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `groq` (default) or `gemini` — which provider is tried first. |
| `GEMINI_API_KEY` | API key for Google Gemini (https://aistudio.google.com/apikey). |
| `GEMINI_MODEL` | Gemini model id (default `gemini-2.5-flash`). |
| `GROQ_API_KEY` | API key for Groq (https://console.groq.com/keys). |
| `GROQ_MODEL` | Primary Groq model (default `openai/gpt-oss-20b`). |
| `GROQ_FALLBACK_MODEL` | Secondary Groq model on a separate rate-limit bucket (default `allam-2-7b`). |
| `PORT` | Port to bind (default `8000`; platforms like Render inject their own). |

No secret values are committed. Copy `.env.example` to `.env` and fill in your own keys locally.

## Local quickstart

```bash
git clone <this-repo-url>
cd gridwise-service
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in GEMINI_API_KEY / GROQ_API_KEY
uvicorn app.main:app --reload
```

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Run the public-sample regression harness (10 worked cases from the official pack):

```bash
python tests/regression/run_public_samples.py http://localhost:8000
```

A one-shot manual smoke test (health + one sample request) is in `scripts/smoke_test.sh`.

### Example `/optimize-energy` request

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @tests/regression/fixtures/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
```

(Use one case's `input` object as the body — see `scripts/smoke_test.sh` for a complete literal example using `SAMPLE-02`.)

## Docker

```bash
docker build -t gridwise:local .
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=groq \
  -e GROQ_API_KEY=your-key-here \
  gridwise:local
curl http://localhost:8000/health
```

Published fallback image: `tariquzzaman01/gridwise:v1-c2af3b1`
(digest `sha256:27a6832fcf6e65b6ac2545cf68f40054b8718e4acf8a4f382abe921da757c18b`, also tagged `:latest`).

```bash
docker pull tariquzzaman01/gridwise:v1-c2af3b1
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=groq \
  -e GROQ_API_KEY=your-key-here \
  tariquzzaman01/gridwise:v1-c2af3b1
curl http://localhost:8000/health
```

## LLM provider strategy

- **Primary**: Groq (`openai/gpt-oss-20b`, a reasoning model, `reasoning_effort=low` to conserve free-tier token budget) via its OpenAI-compatible `chat/completions` endpoint with `response_format={"type":"json_object"}`.
- **Secondary**: a second Groq model (`allam-2-7b`) on a **separate per-model rate-limit bucket** — if the primary model is rate-limited, this can still serve the request instead of immediately giving up.
- **Tertiary**: Gemini, attempted as a best-effort third path.
- **Total failure**: every note is safely degraded to `no_op` and the service still returns `200` with a valid, schema-correct schedule (built from base rules only). This is the documented SAFE FAILURE path — it costs interpretation/application credit for that request only, never availability.
- All 1–3 notes in a request are interpreted in a **single batched LLM call** (not one call per note) to stay well inside the 30-second request budget.
- Only `battery.capacity_kwh` is sent to the model along with the notes — the full hourly demand/solar/tariff arrays are deliberately withheld, since none of the 6 supported directive types need them, which removes any surface for the model to "invent" changes to base data.

## Guardrails

Every LLM output entry passes through `app/guardrails/validator.py` before it can affect the schedule: allowed-type check, `note_index` completeness/uniqueness (constructively rebuilt, not just checked), applies/no_op consistency, structured_adjustment shape per type, numeric range checks (solar factor 0–1, non-negative reserves/caps), and self-healing of out-of-order/duplicate hour lists. Anything that can't be fixed is downgraded to a transparent `no_op` — the guardrail layer never invents a new directive type and never raises.

## Optimizer

A linear program over 24 hours (120 decision variables: grid, solar-used, charge, discharge, battery-energy-after per hour) minimizing `Σ grid[h]·tariff[h]` subject to energy balance, battery bounds/rate limits, active directive constraints, and end-of-day battery neutrality. A tiny tie-break term on `charge+discharge` (plus a deterministic post-solve netting step) resolves the natural LP degeneracy where simultaneous charge-and-discharge would otherwise satisfy the same cost optimum. If the LP ever fails to solve, a deterministic greedy-with-backward-correction heuristic (and, as an absolute last resort, a pure-grid plan) guarantees a schema-valid response instead of a 500.

## Known limitations

- If both Groq models are simultaneously rate-limited and Gemini's request also fails, that request's notes degrade to `no_op` (schedule stays valid, but loses interpretation credit for that request).
- The fallback heuristic scheduler (used only if the LP itself fails, which should not happen for organizer-valid feasible scenarios) is not guaranteed cost-optimal — it exists purely to guarantee a valid response.
- `422` semantic validation is intentionally narrow (battery energy bounds only), per the Problem Statement's "422 optional" note.

## Security

- No API keys, tokens, or secrets are committed to this repository (`.env` is gitignored; `.env.example` has names only).
- Logs redact any configured secret value before being written.
- The Docker image contains no baked-in credentials — keys are supplied only via runtime environment variables.
- The global exception handler never returns a stack trace or internal detail to the client.

## Credits

Built with AI coding assistance (Claude Code); the architecture, guardrail logic, LP formulation, and prompt design are the team's own work.
