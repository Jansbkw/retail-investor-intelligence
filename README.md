# Retail Investor Intelligence

An interview-ready MVP for investor-relations teams: collect public retail-investor discussion, distinguish the right listed company, classify each post with a structured LLM workflow, compute statistics deterministically, and keep every insight traceable to original evidence.

The primary workflow is **search ticker → select exchange-qualified company → view intelligence**. Summary stays first and evidence is one click away. The dashboard shows sample size, coverage gaps, sentiment, themes, concerns, source links, and a company-scoped question box that refuses investment advice and abstains when evidence is thin.

## Run the demo

Prerequisite: Docker Desktop with Docker Compose.

```bash
docker compose up --build
```

Open [http://localhost:8501](http://localhost:8501). The API is at [http://localhost:8000/docs](http://localhost:8000/docs).

The command rebuilds SQLite idempotently from the checked-in **real, verbatim Stocktwits MCP snapshot**, imports schema-validated build-time enrichment, waits for the API health check, and starts Streamlit. No credentials are required for the reproducible demo.

### Local Python alternative

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli prepare-demo
uvicorn app.api.main:app --reload
```

In a second terminal:

```bash
source .venv/bin/activate
streamlit run app/ui/streamlit_app.py
```

## Actual data coverage

Snapshot collected on **2026-11-20 UTC**. Dates below are source post timestamps, not ingestion time.

| Company | Source | Status | Raw / retained | Source-time range | Truthful limitation |
|---|---|---:|---:|---|---|
| TTWO | Stocktwits MCP | available | 11 / 10 | 2026-11-19 23:55–2026-11-20 01:43 UTC | One ticker-only post rejected; stream snapshot is not a historical firehose |
| VEON | Stocktwits MCP | available | 10 / 10 | 2026-11-06 07:17–2026-11-18 21:21 UTC | Verbatim, curated live stream snapshot; not a historical firehose |
| STB | Stocktwits MCP | identity mismatch | 30 discovery records / 0 target-company records | mixed historical stream | The stream mixes several `STB` entities; none verify as Secure Trust Bank |
| TTWO | YouTube comments | available | 24 retrieved in the targeted run | last 90 days | Parent-video identity is verified before comments enter AI relevance review |
| VEON | YouTube comments | sparse | 1 retrieved in the targeted run | last 90 days | Genuine data; low volume is preserved as a coverage signal |
| STB | YouTube comments | no verified data | 0 / 0 | — | Ambiguous videos were excluded rather than assigned to the wrong company |
| TTWO | Hacker News | experimental | 100 verified company mentions / 1 deterministic investor-relevant | last 30 days | 99 general company/product mentions await AI review |
| VEON / STB | Hacker News | no verified data | 0 / 0 | last 30 days | Public API worked; identity validation removed fuzzy-search noise |
| All | X | connector disabled | 0 / 0 | — | Official API returned payment-required; no scraping fallback is used |

Stocktwits identity was authenticated with `whoami`, then every symbol was checked with `get_symbol` before `get_symbol_messages`. The checked-in export has `provenance=stocktwits_mcp` and `synthetic=false`. It stores exact public text and only hashed author identifiers. **No synthetic posts appear in the demo or its metrics.**

The “last 30 days” window is always based on each post's real `created_at` timestamp in UTC. A source can be available yet sparse; “unavailable” and “zero relevant posts” are separate states.

## Configuration and secrets

You do **not** need to put any Stocktwits value in `.env`. MCP authentication belongs to the execution environment and must be authorized independently by each developer or ingestion worker.

Copy the example only when enabling live services:

```bash
cp .env.example .env
```

Relevant variables:

- `OPENAI_API_KEY`, `OPENAI_MODEL_SMALL`, `OPENAI_MODEL_LARGE`: live enrichment and generative RAG.
- `YOUTUBE_API_KEY`: official YouTube Data API v3 collection.
- `FINNHUB_API_KEY`: optional security-candidate discovery. Finnhub is reference data, not a social source.
- `X_BEARER_TOKEN`: official X Recent Search.
- `ALLOW_PAID_X_CALLS=true`: an additional cost guard; do not enable without approval.
- `DATABASE_PATH`, `API_BASE_URL`, `CORS_ORIGINS`: deployment settings.

Missing credentials produce an explicit coverage record and do not crash the run. The code never scrapes Stocktwits, calls an undocumented Stocktwits HTTP endpoint, or silently substitutes synthetic records.

## Architecture

```text
Finnhub + verified exchange/ISIN registry
  -> exchange-qualified entity candidates
MCP/API adapters (Stocktwits, YouTube, Hacker News)
  -> normalize + clean + content/source-ID dedupe
  -> deterministic company relevance / STB ambiguity gate
  -> SQLite posts + FTS5 index
  -> structured LLM enrichment (Pydantic + retry + content/version cache)
  -> deterministic SQL/Python aggregation
  -> FastAPI
  -> Streamlit overview + evidence explorer + grounded Q&A
```

Batch ingestion is separate from serving. One source failure is recorded in `coverage` and the other source/company jobs continue. Numeric analytics are never delegated to an LLM.

Core tables:

- `posts`: internal `company_id`, source provenance, exact raw text, cleaned text, UTC timestamps, nullable engagement, hashed author ID, stable composite ID, content hash, relevance state, synthetic flag. Uniqueness is enforced by source ID plus `company_id`, not ticker.
- `analysis`: strict relevance/sentiment/topic/concern/summary output plus model, prompt version, content hash, status, and evidence IDs.
- `llm_cache`: cache key over content hash, company identity, model, and prompt version.
- `coverage`: per-company, per-run source status, raw/relevant/rejected counts, time range, restrictions, and errors.
- `posts_fts`: company-scoped FTS5 retrieval for grounded questions.

See [DESIGN.md](DESIGN.md) for boundaries and production evolution.

## AI behavior

Enrichment uses strict Pydantic JSON output with bounded enums:

- investor relevance;
- Bullish / Bearish / Neutral / Unclear sentiment;
- up to three controlled topics and concerns;
- confidence, short explanation, neutral summary, and exact evidence record ID.

Social text is delimited and treated as untrusted input. Model output is rejected if its evidence ID does not match the supplied record. Unchanged records are skipped when content hash, model, and prompt version still match; cross-run responses are cached. API calls use timeouts and bounded exponential backoff, and log tokens, latency, and estimated cost.

The reproducible snapshot contains 20 analyses produced by `gpt-5.6-sol (Codex build-time)` and validated through `PostAnalysis` before database import. The session did not expose actual billable token cost. Using the configured reference rates and approximate text size gives an **equivalent estimate around $0.006**, not an asserted invoice amount.

For free-text questions, FTS5 retrieval is `company_id`-scoped. The system validates citations, refuses buy/sell advice, and says there is insufficient evidence below the minimum threshold. With no runtime LLM key, the UI explicitly displays an extractive evidence fallback—it never presents that fallback as generated synthesis.

## API

- `GET /health`
- `GET /companies`
- `GET /companies/search?q=STB`
- `GET /companies/{company_id}`
- `GET /entities/search?ticker=STB`
- `GET /coverage?company_id=take-two-interactive-nasdaq`
- `GET /analytics/overview?company_id=take-two-interactive-nasdaq&days=30`
- `GET /analytics/sentiment`, `/topics`, `/trends`
- `GET /discussions?company_id=take-two-interactive-nasdaq&sentiment=Bullish`
- `POST /ask` with `{"company_id":"take-two-interactive-nasdaq","question":"What are people saying about GTA VI?"}`

Unknown companies, missing data, source failures, and invalid questions return controlled responses.

## Tests and evaluation

```bash
pytest -q
python evals/run_evals.py
```

Current verification:

- 35 unit/integration tests pass, including HN pagination/provenance/relevance boundaries, Finnhub candidate filtering, company search and same-ticker database isolation, plus cleaning, dedupe, STB relevance, MCP provenance, source failure isolation, idempotency, enrichment cache, deterministic aggregation, retrieval, citation safety, and API contracts.
- 30/30 regression cases pass: 20 enrichment labels, 7 relevance cases, and 3 RAG safety/grounding behaviors.
- Local API smoke test: all main endpoints returned 200 in roughly 0.6–2.6 ms on this laptop.
- The Streamlit UI is smoke-tested against the local API, including company search, limited-coverage states, overview, evidence, abstention, and no-key fallback.

The enrichment cases are reviewed regression expectations, not an independently annotated expert benchmark. For production, add blinded labels, inter-annotator agreement, drift slices, and prompt/model promotion gates.

## Known limitations

- Hacker News is deliberately labelled experimental: the API returns many TTWO product mentions but very little investor-relevant discussion, and no verified VEON/STB discussion in the tested window.
- Finnhub improves ticker discovery but has incomplete global-exchange coverage; exchange and ISIN evidence remain authoritative.
- The Stocktwits MCP returned a current symbol stream, not full 30-day history; volume trends are therefore illustrative and explicitly sample-sized.
- STB has no valid target-company Stocktwits identity. The raw stream is classified into exchange-qualified, historical, mistagged, non-company and unresolved entities instead of being mixed into Secure Trust Bank analytics.
- Engagement fields are sparse and nullable. Missing is never treated as zero.
- SQLite + batch jobs fit this take-home scale, not high-throughput multi-tenant production.
- Runtime generative Q&A needs an OpenAI API key; the demo's build-time LLM enrichment remains fully inspectable without one.

## Production path

Deploy serving and ingestion separately. An MCP-capable scheduled worker must have its **own** Stocktwits OAuth authorization, run `whoami` and symbol validation, and deliver an auditable export to storage before ingestion. The API server itself needs no Stocktwits secret. Use a managed secret store for YouTube/X/OpenAI, Postgres for concurrent tenants, an object store for raw immutable exports, a queue for enrichment, per-tenant RBAC, retention/deletion policy, source rate-limit monitoring, tracing/cost budgets, and evaluation gates before prompt/model changes.

For a short walkthrough, use [DEMO.md](DEMO.md).
