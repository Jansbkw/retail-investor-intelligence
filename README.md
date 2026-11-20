# Retail Investor Intelligence

## Project Overview

An interview-ready MVP for investor-relations teams: collect public retail-investor discussion, distinguish the right listed company, classify each post with a structured LLM workflow, compute statistics deterministically, and keep every insight traceable to original evidence.

The primary workflow is **search ticker → select exchange-qualified company → view intelligence**. Summary stays first and evidence is one click away. The dashboard shows sample size, coverage gaps, sentiment, themes, concerns, source links, and a company-scoped question box that refuses investment advice and abstains when evidence is thin.

The configured targets are TTWO (Take-Two Interactive), VEON (VEON Ltd.) and STB. Because `STB` is not globally unique, search returns Secure Trust Bank, Storebrand and Société Tunisienne de Banque separately; every stored record and AI query is isolated by an internal `company_id`.

## Tech Stack

| Layer | Technology | MVP responsibility |
|---|---|---|
| Collection | Python adapters, Stocktwits MCP export, YouTube Data API v3, Hacker News Algolia API | Retrieve public source records without scraping fallbacks |
| Data pipeline | Pydantic, Python | Normalize, clean, deduplicate and validate company relevance |
| AI | OpenAI structured outputs, Pydantic schemas, FTS5 retrieval | Enrichment, grounded Q&A, citation validation and abstention |
| Storage | SQLite + FTS5 | Posts, analyses, coverage, cache and call telemetry |
| Backend | FastAPI | Company search, analytics, evidence and Ask APIs |
| Frontend | Streamlit | Search → select company → intelligence dashboard |
| Quality/deployment | pytest, Docker, Docker Compose | Regression tests and reproducible local deployment |

## Setup Instructions

Prerequisite: Docker Desktop with Docker Compose.

```bash
docker compose up --build
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). The API documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

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

## Data Sources

The reproducible MVP uses three public discussion sources:

1. **Stocktwits** — connected MCP only. The worker authenticates with `whoami`, validates each symbol with `get_symbol`, then retrieves public records with `get_symbol_messages`. The repository includes a provenance-labelled real snapshot so reviewers do not need the original OAuth session.
2. **YouTube comments** — official YouTube Data API v3. Search queries are company-aware; comments enter relevance review only after the parent video passes company-identity validation.
3. **Hacker News** — public Algolia stories/comments API with pagination, retry, deduplication and company validation. It is kept as an experimental third source because investor relevance is low.

Finnhub is optional **reference data for entity discovery**, not a social source. The X connector is implemented but disabled in the demo because the tested official API project returned payment-required. Reddit was not used because API approval could not be obtained within the take-home window.

### Actual data coverage

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

## Environment Variables

You do **not** need to put any Stocktwits value in `.env`. MCP authentication belongs to the execution environment and must be authorized independently by each developer or ingestion worker.

Copy the example only when enabling live services:

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
|---|---:|---|
| `OPENAI_API_KEY` | For live AI | Runtime enrichment and generative RAG |
| `OPENAI_MODEL_SMALL` | For live AI | Structured enrichment model; no model name is hard-coded |
| `OPENAI_MODEL_LARGE` | No | Q&A model; falls back to the small model when omitted |
| `OPENAI_EMBEDDING_MODEL` | No | Reserved model configuration for a future vector retrieval path |
| `YOUTUBE_API_KEY` | For live YouTube | Official YouTube Data API v3 collection |
| `FINNHUB_API_KEY` | No | Security-candidate discovery only |
| `X_BEARER_TOKEN` | No | Official X Recent Search connector |
| `ALLOW_PAID_X_CALLS` | No | Explicit cost guard for X; defaults to `false` |
| `DATABASE_PATH` | No | SQLite location; defaults to `data/retail_intelligence.db` |
| `API_BASE_URL`, `CORS_ORIGINS` | No | Serving configuration |

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

### Repository structure

```text
app/collectors/       source adapters
app/pipeline/         cleaning, entity relevance, enrichment and aggregation
app/ai/               prompts, Pydantic schemas, LLM client and grounded Q&A
app/reference_data/   Finnhub security-candidate discovery
app/api/              FastAPI service
app/ui/               Streamlit application
data/live/            provenance-labelled real snapshots and approved enrichment
evals/                reviewed regression cases
tests/                unit and integration tests
```

See [DESIGN.md](DESIGN.md) for boundaries and production evolution.

## AI Approach

Enrichment uses strict Pydantic JSON output with bounded enums:

- investor relevance;
- Bullish / Bearish / Neutral / Unclear sentiment;
- up to three controlled topics and concerns;
- confidence, short explanation, neutral summary, and exact evidence record ID.

Social text is delimited and treated as untrusted input. Model output is rejected if its evidence ID does not match the supplied record. Unchanged records are skipped when content hash, model, and prompt version still match; cross-run responses are cached. API calls use timeouts and bounded exponential backoff, and log tokens, latency, and estimated cost.

The reproducible snapshot contains 20 analyses produced by `gpt-5.6-sol (Codex build-time)` and validated through `PostAnalysis` before database import. The session did not expose actual billable token cost. Using the configured reference rates and approximate text size gives an **equivalent estimate around $0.006**, not an asserted invoice amount.

For free-text questions, FTS5 retrieval is `company_id`-scoped and falls back to recent enriched evidence when a broad question has no literal keyword match. OpenAI strict structured output is validated again with Pydantic. The system rejects unsupported citations, refuses buy/sell advice, and says there is insufficient evidence below the minimum threshold. With no runtime LLM key, common concern questions use deterministic aggregation over existing enrichment and other questions show an explicitly labelled extractive fallback—it never presents a fallback as generated synthesis.

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

- 37 unit/integration tests pass, including strict OpenAI schema compatibility, HN pagination/provenance/relevance boundaries, Finnhub candidate filtering, company search and same-ticker database isolation, plus cleaning, dedupe, STB relevance, MCP provenance, source failure isolation, idempotency, enrichment cache, deterministic aggregation, retrieval, citation safety, and API contracts.
- 30/30 regression cases pass: 20 enrichment labels, 7 relevance cases, and 3 RAG safety/grounding behaviors.
- Live RAG smoke test: `gpt-4.1-mini` returned a grounded TTWO answer with three validated citations from five retrieved evidence records; measured latency was 5.6 seconds and configured-rate estimated cost was about $0.00114.
- The Streamlit UI is smoke-tested against the local API, including company search, limited-coverage states, overview, evidence, abstention, and no-key fallback.

The enrichment cases are reviewed regression expectations, not an independently annotated expert benchmark. For production, add blinded labels, inter-annotator agreement, drift slices, and prompt/model promotion gates.

## Trade-offs

- **Integrity over apparent coverage:** ambiguous ticker-only records are rejected. This reduces recall, especially for STB, but prevents another company from contaminating an IR briefing.
- **Batch over streaming:** ingestion is a separate CLI job. This is easy to inspect and deploy for an MVP, but freshness depends on scheduling.
- **SQLite/FTS5 over a vector database:** deterministic, portable and sufficient for this data volume. Production multi-tenant scale would move to Postgres plus pgvector or managed search.
- **Structured enrichment over an agent framework:** bounded schemas, retries, caching and evidence IDs are easier to test than an open-ended agent. The trade-off is a narrower ontology.
- **Official/free access over maximum source coverage:** no scraping or synthetic substitution. Reddit and X remain future integrations until approval or budget exists.
- **Precomputed demo enrichment plus optional live RAG:** reviewers can reproduce the dashboard without credentials, while a configured OpenAI key enables arbitrary grounded questions.

## Limitations

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
