# Demo guide (5–7 minutes)

## Before the interview

```bash
docker compose up --build
```

Open <http://localhost:8501>. Keep <http://localhost:8000/docs> available for the architecture section.

## Talk track

1. **Start with the IR job.** An IR lead has ten minutes, so the first screen answers “what changed, what matters, and can I verify it?” Point out the real-data label, sample size, source status, and latest evidence date.
2. **Show TTWO.** Explain the mixed GTA VI reception: positive launch/product discussion, bearish product-quality reactions, and unverified commercial claims clearly summarized as claims. Open one original Stocktwits link.
3. **Switch to VEON.** Highlight earnings/growth themes and the supported capital-controls / management-awareness concern. This demonstrates that the same schema works for lower-volume discussion.
4. **Show STB.** The correct empty state is the product feature: Stocktwits STB is a different company. Expand Coverage details to show the identity mismatch. No contaminated posts enter the dashboard.
5. **Open Discussions.** Filter or search evidence and show sentiment labels, timestamps, and source links.
6. **Ask a question.** “What are people saying about TTWO?” With an API key, the service generates a cited synthesis. Without one, it explicitly shows retrieved evidence summaries and citations. Ask “Should I buy TTWO?” to show the investment-advice refusal.
7. **Finish with the pipeline.** MCP/API adapters → cleaning/dedupe → conservative relevance → SQLite/FTS5 → strict Pydantic LLM output/cache → deterministic aggregation → FastAPI → Streamlit.

## Numbers to know

- 21 genuine, verbatim Stocktwits MCP records: TTWO 11 raw / 10 relevant, VEON 10 / 10.
- 20/20 schema-validated enrichments; 0 processing failures.
- TTWO sentiment: 6 Bullish, 3 Bearish, 1 Neutral.
- VEON sentiment: 7 Bullish, 3 Neutral.
- 14 automated tests pass.
- 30/30 regression cases pass: 20 enrichment, 7 relevance, 3 RAG safety/grounding.
- Equivalent enrichment estimate around $0.006 using configured reference rates; actual Codex session billing was not exposed.

## Trade-offs to volunteer

- Stocktwits MCP provided a stream snapshot, not full 30-day history, so this is enough to prove the product loop but not to claim market representativeness.
- YouTube and X adapters exist, but this run has no credentials and X was not authorized for paid usage. The UI reports this rather than substituting fake data.
- Build-time LLM enrichment makes the no-secret demo reproducible. Runtime generative Q&A needs an OpenAI key; no-key mode remains grounded but extractive.
- SQLite/FTS5 and batch ingestion are intentionally small. Production would separate workers, API, object storage, Postgres, queues, tenant isolation, and observability.

## Recovery

- UI cannot reach API: wait for the Compose health check, then refresh.
- Stale local database: `python -m app.cli prepare-demo` is idempotent and reimports current enrichment.
- Port in use: stop the other service or change the host port in `docker-compose.yml`.
- Live enrichment fails: verify `OPENAI_API_KEY` plus both configured model names; failed records remain visible in processing state.
- Stocktwits refresh: reconnect the MCP in the execution environment, call `whoami`, validate all symbols with `get_symbol`, then use `get_symbol_messages`. Never switch to scraping or an undocumented HTTP endpoint.
