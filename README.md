# Critical Material Supply Exposure Index (CMSEI)

Supply concentration scores for 19 critical minerals. CMSEI is the platform built on the Material Supply Exposure Index described in the accompanying paper.

A market-level 0–100 score for how exposed US manufacturers are to supply disruption in 19 critical materials. Open source. Every score is the same for every user, shows a range, a data grade and its validation status, and can be reproduced from a stored snapshot.

**Status: preview.** Read "What this is not" before relying on any number.

## What this is not

- **Not validated as a predictor.** Backtests found the index does not beat simple world-production concentration at anticipating export restrictions. Use it to see where supply is concentrated and what could change it.
- **Data is unverified and dated.** Figures were transcribed from USGS Mineral Commodity Summaries 2024 and have not been checked against the PDFs by a person.
- **Processing-stage data exists for two materials** (cobalt, rare earths). The other 17 use production shares as a stand-in and are marked Indicative, grade C.
- **No alternate source is verified yet, so none earns credit.** This follows the paper and patent claim 4 (only verified sources count). Scores are therefore higher than the paper's pilot table, which credited every producer by share. Each result page shows the score if all listed producers were credited. For rare earths that is 50.9 (Moderate) against the official 74.7 (High).
- **The event layer runs in shadow mode.** It collects and gates events but changes no score. Do not set `PUBLISH_EVENTS=true` until the go-live accuracy test has been run on at least 300 labelled documents and a reviewer has approved.
- **Sectors are a draft list, and none can be scored yet.** Materials with only Indicative (grade C) data are left out of sector means, as the paper says. An indicative preview is shown and labelled as such.
- **Licence, terms and privacy text are pending legal review.** No licence file is included on purpose. Add one before accepting outside contributions.

## Formula (v1.1)

```
C = HHI(US import shares) / 100
P = 0.3 · raw-stage HHI/100 + 0.7 · processing-stage HHI/100
N_eff = Σ over non-dominant producers of min(1, global share / 5), for credited sources only
S = min(100, 100 / (1 + N_eff) · D)
Base = 0.3 C + 0.4 P + 0.3 S
G = min(1.5, 1 + Σ active event effects)      statement .02, proposed .08, enacted .15, ban .30
Composite = min(100, Base · G)
Tiers: Low ≤30, Moderate ≤60, High ≤80, Critical >80
```

Worked example: C 81.52, P 69.4, S 65, G 1.08 → 77.45, High.

## What is in the box

| Part | Where |
|---|---|
| Score engine, uncertainty run, scenario simulator, recommendations, classifier | `app/engine/` |
| API v1 (OpenAPI at `/api/docs`) and server-rendered site | `app/api.py`, `app/web.py`, `app/templates/` |
| Reviewer console (held events, corrections, sign-off) | `app/admin.py` at `/admin` |
| Event monitor (fetch, extract, gate, hold queue, decay, re-verify) | `app/worker/` |
| Data and taxonomy | `data/`, `scripts/build_taxonomy.py` |
| Migrations | `migrations/` |
| Company layer: parts-list upload, roll-up, what-if, supplier questionnaire, compliance screen, peer benchmark | `app/engine/bom.py`, `app/engine/compliance.py`, `app/services/company.py`, `app/company.py` |
| Alerts to Slack, Teams or email | `app/services/alerts.py` |
| Back-test against documented export restrictions | `app/engine/validation.py`, `data/shocks.json`, `scripts/backtest_shocks.py` |
| Double-entry data check, data refresh procedure | `scripts/verify_transcription.py`, `docs/DATA-REFRESH.md` |
| Governance, SAP export guide, outreach kit | `GOVERNANCE.md`, `MAINTAINERS.md`, `docs/` |
| Tests (0) | `tests/` |

This build uses FastAPI with server-rendered pages, not Next.js. It is one deployable service, which keeps the privacy and security surface small.

## For manufacturers: your own parts list

`/company` takes a CSV and shows which products and suppliers lean on which materials, with an optional what-if (for example "China cuts gallium"), a supplier questionnaire, a compliance screen (DFARS magnets and tantalum, conflict minerals, UFLPA sectors) and a PDF. The file is processed in memory and never stored (a test checks the database and logs). The roll-up is a screening heuristic: a part takes the highest score of its materials, and a product takes the highest of its parts. It is not part of the validated index. The same functions are on the API (`POST /api/v1/company/analyze`, CSV body). SAP headers are recognized; see `docs/SAP-EXPORT.md`. No live SAP connector exists. Tariff exposure by HTS code is not built.

**Validation.** The back-test at `/validation` puts the index at AUC 0.74 (95% interval 0.49 to 0.95) against 0.85 for the top producer's share, so it does not beat a simple concentration measure. That is published as found.

## Patent-relevant behaviour, and where it lives

| Behaviour | Code |
|---|---|
| Hash-chained, append-only snapshot log; `GET /api/v1/log/verify` walks it and regenerates every score, tier and explanation sentence | `app/services/chain.py`, `app/services/snapshots.py` |
| Documents with text addressed to an automated reader are quarantined before any extractor runs | `app/worker/screen.py`, `app/worker/monitor.py` |
| Explanation sentence filled from a stored template and validated fields; no model text | `app/engine/explain.py`, `data/explanation_templates.json` |
| Only verified alternate sources earn credit; continuous partial credit below 5% | `app/engine/scoring.py` |
| Uncertainty range uses the paper's Section V-A method (5th to 95th percentile of 50,000 seeded draws) | `app/engine/uncertainty.py` |

`tests/test_paper_alignment.py` reproduces the paper's worked example, Table III and the Section V-A figures (71.7 to 83.7, High in 74.6% of draws).

## Privacy by design

No accounts. The description you type, your region and your volume are used once and never written to the database or logs. Watchlists hang off a random session token stored as a hash. No IP addresses are stored. The assessment table has no free-text columns. Tests enforce this.

## Run it

```bash
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload          # SQLite, creates tables itself
```

With Postgres (docker compose):

```bash
cp .env.example .env     # set ADMIN_PASSWORD
docker compose up --build
docker compose --profile jobs run --rm daily
```

The container runs `alembic upgrade head` on start. Postgres has not been exercised in the build environment; CI runs the migration against Postgres 16, so check that first.

## Deploy on Render

`render.yaml` defines a web service, a Postgres database and a daily cron job. Set `PUBLIC_BASE_URL`, `CONTACT_URL` and, optionally, `ANTHROPIC_API_KEY` in the dashboard. `ADMIN_PASSWORD` is generated; read it from the service's environment.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres or SQLite URL | `sqlite:///./mse.db` |
| `ADMIN_PASSWORD` | Reviewer console. Empty disables `/admin` | empty |
| `ANTHROPIC_API_KEY` | Live classifier and extractor. Empty uses offline keyword methods | empty |
| `CLAUDE_MODEL` | Model for both | `claude-haiku-5-5` |
| `CLAUDE_DAILY_CALL_CAP`, `CLAUDE_MONTHLY_CALL_CAP` | Hard spend caps, counted in the database | 200, 3000 |
| `PUBLISH_EVENTS` | Let confirmed events change scores | `false` |
| `LAUNCH_STATUS` | `preview` shows the banner | `preview` |
| `RATE_PER_MINUTE_IP`, `RATE_ASSESS_PER_MINUTE_IP` | In-process rate limits (uploads, alerts and assessments use the second) | 60, 20 |
| `MAINTAINER_NAME`, `MAINTAINER_ROLE` | Shown on Status, Governance and PDFs | Ankit (GitHub: theleanx) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | Turns on email alerts. Slack and Teams alerts need none | empty |
| `MAX_BENCHMARK_PER_DAY` | Cap on peer-comparison submissions per day | 200 |

Rate limits are in-process, so run one worker (the Dockerfile does). Put a CDN or the platform's limiter in front for real abuse protection.

## What a maintainer must do

1. Replace the 2024 data with MCS 2026 (`docs/DATA-REFRESH.md`). From January 2027 the staleness rule makes every score Indicative.
2. Have a second person check every figure (`scripts/verify_transcription.py`), record it under "Data checks" in `/admin`, then sign off each material.
3. Record alternate-source decisions with evidence in `/admin`, and review the substitution factor D. Both are placeholders until someone does.
4. Run the event-layer go-live test before enabling `PUBLISH_EVENTS`.
5. Review the held-event queue within 72 hours of each alert, or events expire.
6. Get the terms, privacy notice, disclaimer and licence reviewed by counsel.

## Data sources

USGS Mineral Commodity Summaries (public domain). IEA Global Critical Minerals Outlook 2024 (CC BY 4.0, attribution required) for the cobalt and rare-earth processing shares. Event documents come only from hosts in `data/sources_allowlist.json`.
