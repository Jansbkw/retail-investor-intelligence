# Design notes

## Product principle

Summary first, evidence one click away. Every metric shows its sample size. The main
workflow is designed for an IR lead with roughly ten minutes per week.

## System boundaries

- Collectors only fetch and normalise source-specific fields.
- Pipeline code cleans, deduplicates, and filters relevance.
- AI code produces validated labels and grounded narrative text.
- Numeric results are always computed in SQL/Python, never by the model.
- FastAPI presents stable contracts; Streamlit contains no business logic.

## MVP trade-offs

- SQLite and batch ingestion reduce operational complexity for the take-home.
- Synthetic fixtures make the demo deterministic when APIs or keys are unavailable.
- STB uses conservative company aliases and financial context to reduce ticker ambiguity.
- Embeddings can remain in SQLite at this scale; a vector database is a later migration.

## Planned production path

Move scheduled ingestion to a job runner, store secrets in a managed secret store, add
source-specific rate-limit and freshness monitoring, move to Postgres/vector search, and
add authentication, audit logs, tracing, prompt/evaluation gates, and retention controls.

