# Design and trade-offs

## User and product decision

The user is an IR lead with about ten minutes per week. The product first asks them to choose an exchange-qualified company, then answers: how much evidence exists, overall mood, top themes, concerns, recency, and where the claims came from. Detailed posts and filters live behind an Evidence tab. Coverage failures are product state, not log-only errors.

The application avoids a single “sentiment score”. Counts and sample sizes make uncertainty visible, while source links let an IR user inspect nuance and rumours.

## Boundaries

```text
collectors -> clean/dedupe -> relevance -> persist/FTS
                                     -> LLM enrichment/cache
                                     -> deterministic aggregation
                                     -> FastAPI -> Streamlit
```

- Adapters translate official source records into one `Post` model and may attach source-specific identity evidence; the pipeline owns the persisted relevance state.
- Relevance is a conservative deterministic gate before paid model calls.
- Enrichment handles semantic labels and summaries only.
- SQL/Python computes every count, distribution, time series, and sample size.
- FastAPI owns stable contracts; Streamlit owns presentation only.
- Ingestion is a batch command and can fail independently of the serving process.

## Data integrity

The stable ID is `source:source_post_id:company_id`, and the database uniqueness boundary is `(source, source_post_id, company_id)`. This lets companies sharing `STB` remain independent even if a provider reuses a source identifier. A separate company-scoped content hash supports duplicate suppression and change-aware analysis. Raw source text and cleaned text are both retained. Engagement values are nullable because unavailable is not zero.

Upserts make repeated collection idempotent. Every analysis row stores its input content hash, model, prompt version, creation time, and status. A current row is skipped; the response cache avoids repeated calls across runs. Failed analysis is recorded rather than silently dropped.

The current SQLite schema is deliberately compact. FTS5 is adequate for tens of thousands of posts and makes retrieval inspectable. Postgres plus pgvector or a managed search service is the natural multi-tenant migration.

## Company identity and STB

Ticker matching alone is unsafe. Each company has canonical name, aliases, exclusions, and source-specific identity expectations. For ambiguous STB:

1. The symbol first resolves to exchange-qualified candidates. The verified registry currently includes Secure Trust Bank (LSE), Storebrand (Oslo), and Société Tunisienne de Banque (Tunis).
2. Finnhub contributes discovery candidates such as `STB.L` and `STB.OL`, but provider candidates remain unverified until exchange/ISIN evidence agrees.
3. Stocktwits `STB` resolves to the historical Student Transportation identity and its raw stream mixes multiple entities, so those records are classified separately and never stored under Secure Trust Bank.
4. Text-source matches require “Secure Trust Bank”, `STB.L`, `LON:STB`, or equivalent verified context; bare `STB`, set-top boxes, historical issuers, mistags and crypto communities do not enter target-company analytics.

This prefers false negatives over contaminating an IR briefing with another company.

The UI therefore never defaults `STB` to London. Search returns every verified active match with company name, exchange, ticker and country. The user must select one, after which every post, coverage row, aggregation and RAG query is scoped by its internal `company_id`. A verified company with no matching posts receives an explicit Limited Coverage state.

## AI reliability and security

Pydantic rejects extra fields, invalid enums, excessive topic counts, invalid confidence, and missing evidence IDs. Prompts delimit social content and explicitly treat it as untrusted. Evidence IDs must equal the input record. Runtime calls use timeouts, bounded exponential backoff, and call telemetry.

RAG uses company-scoped FTS5 retrieval and passes only retrieved evidence. The answer schema includes citations and limitations; post-generation validation rejects invented IDs or URL mismatches. The service refuses investment advice and abstains below two evidence records. Without an LLM API key, it labels an extractive fallback rather than pretending it is AI synthesis.

Public post text is HTML-escaped before UI rendering. Usernames are not stored. Raw MCP exports in the repository replace source user IDs with a one-way hash.

## Source strategy

- **Stocktwits:** MCP only. OAuth is external to the repo. The ingest adapter accepts only an export declaring MCP provenance and validates the symbol title/exchange before normalizing it.
- **YouTube:** official Data API v3 search plus top-level comments; the comment's own timestamp is used. Disabled comments and quota failures are controlled source states.
- **Hacker News:** public Algolia stories/comments with pagination, retry and local entity validation. It is explicitly experimental because the tested window produced many TTWO product mentions but only one strong deterministic investor signal, and no verified VEON/STB records.
- **Finnhub:** optional reference-data lookup for ticker candidates. It is not counted as a social platform and is never the sole identity authority.
- **X:** official recent-search API only. The connector remains behind `ALLOW_PAID_X_CALLS`; the tested project returned payment-required, so it is not a current demo source.

The repository contains a real, verbatim Stocktwits snapshot so reviewers can reproduce the demo without inheriting one developer's OAuth session. It is intentionally described as a stream sample, not complete 30-day coverage.

## Deployment

Docker Compose is the smallest reproducible deployment: the API prepares SQLite, imports checked enrichment, exposes a health check, and then the UI starts. In production:

- run collection/enrichment as scheduled workers with queues and dead-letter handling;
- put immutable source payloads in object storage and relational data in Postgres;
- authorize Stocktwits separately on the worker, never by copying a Codex thread token;
- store OpenAI/YouTube/X/Finnhub secrets in a managed secret store;
- add tenant isolation, RBAC, audit logs, encryption, retention/deletion workflows, and content-policy controls;
- monitor freshness, rate limits, per-source failure rates, model cost/latency, schema failure rate, relevance drift, and retrieval/citation quality;
- promote prompt/model changes only after labelled evaluation and a canary run.

## Deliberate omissions

No fake multi-platform data, vector database, streaming infrastructure, authentication UI, or elaborate agent framework was added. The current free, reproducible source set is Stocktwits, YouTube comments, and experimental Hacker News. Reddit approval and paid X access are production source-expansion work, not blockers hidden by scraping or synthetic records.
