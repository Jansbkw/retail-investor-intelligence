# Retail Investor Intelligence

MVP take-home for Curation: turn public retail-investor discussion into a concise,
evidence-backed view for investor-relations teams.

> Status: repository skeleton. Core interfaces and configuration are present; the
> end-to-end ingestion, enrichment, analytics, and dashboard flow is still to be built.

## Scope

- Companies: TTWO, VEON, STB
- Sources: Reddit, StockTwits, YouTube comments
- Experience: weekly briefing, trends, themes, concerns, investor questions, and grounded Q&A
- Offline demo path: clearly labelled synthetic seed data

## Architecture

```text
collectors -> clean/relevance -> AI enrichment -> SQLite/embeddings
           -> deterministic aggregation -> FastAPI -> Streamlit
```

Ingestion is a batch process and is kept separate from the serving API.

## Local setup (once implementation begins)

```bash
cp .env.example .env
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.api.main:app --reload
streamlit run app/ui/streamlit_app.py
```

See [DESIGN.md](DESIGN.md) for system boundaries and planned trade-offs.

