from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.ai.rag import ask
from app.collectors.stocktwits import StockTwitsCollector
from app.config import ROOT, get_settings, load_file_config
from app.db import connect, init_db, list_coverage
from app.pipeline.aggregate import discussions, overview
from app.pipeline.entity_resolution import classify_messages


class AskRequest(BaseModel):
    ticker: str
    question: str = Field(min_length=3, max_length=500)


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Retail Investor Intelligence",
    description="Evidence-backed public discussion intelligence for investor relations teams.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _ticker(value: str) -> str:
    ticker = value.upper()
    if ticker not in load_file_config().companies:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {value}")
    return ticker


@app.get("/health")
def health() -> dict[str, object]:
    init_db()
    with connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    return {"status": "ok", "database": "ready", "posts": count, "llm_configured": settings.llm_enabled}


@app.get("/companies")
def companies() -> list[dict[str, object]]:
    return [
        {"ticker": ticker, "name": company.name, "exchange": company.exchange,
         "ambiguous": company.ambiguous,
         "candidate_count": len([item for item in company.security_candidates if item.status == "active"])}
        for ticker, company in load_file_config().companies.items()
    ]


@app.get("/entities/search")
def entity_search(ticker: str) -> dict[str, object]:
    selected = _ticker(ticker)
    company = load_file_config().companies[selected]
    candidates = company.security_candidates
    active = [item.model_dump() for item in candidates if item.status == "active"]
    other = [item.model_dump() for item in candidates if item.status != "active"]

    source: dict[str, object] = {
        "source": "stocktwits", "raw_count": 0, "counts": {}, "records": [],
        "source_identity": None, "coverage": None, "snapshot_collected_at": None,
    }
    collector = StockTwitsCollector()
    if collector.export_path.exists():
        with collector.export_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("provenance") == "stocktwits_mcp":
            source.update(classify_messages(
                (payload.get("messages") or {}).get(selected, []), candidates,
            ))
            source["source_identity"] = (payload.get("symbols") or {}).get(selected)
            source["coverage"] = (payload.get("coverage") or {}).get(selected)

    discovery_path = Path(load_file_config().collection.stocktwits_entity_discovery_path)
    if not discovery_path.is_absolute():
        discovery_path = ROOT / discovery_path
    if discovery_path.exists():
        with discovery_path.open(encoding="utf-8") as handle:
            discovery = json.load(handle)
        if (
            discovery.get("provenance") == "stocktwits_mcp"
            and discovery.get("synthetic") is False
            and discovery.get("query_symbol") == selected
        ):
            source.update(classify_messages(discovery.get("messages") or [], candidates))
            source["source_identity"] = discovery.get("symbol")
            source["snapshot_collected_at"] = discovery.get("collected_at")

    return {
        "ticker": selected,
        "target": {"name": company.name, "exchange": company.exchange},
        "requires_selection": len(active) > 1,
        "active_candidates": active,
        "other_matches": other,
        "source_classification": source,
    }


@app.get("/coverage")
def coverage(ticker: str | None = None) -> list[dict[str, object]]:
    selected = _ticker(ticker) if ticker else None
    return [dict(row) for row in list_coverage() if not selected or row["ticker"] == selected]


@app.get("/analytics/overview")
def analytics_overview(
    ticker: str, days: Annotated[int, Query(ge=1, le=90)] = 30,
    source: list[str] | None = Query(default=None),
) -> dict[str, object]:
    return overview(_ticker(ticker), days=days, sources=source)


@app.get("/analytics/sentiment")
def analytics_sentiment(ticker: str, days: Annotated[int, Query(ge=1, le=90)] = 30) -> dict[str, object]:
    result = overview(_ticker(ticker), days=days)
    return {"ticker": result["ticker"], "sample_size": result["analysed_count"], "sentiment": result["sentiment"]}


@app.get("/analytics/topics")
def analytics_topics(ticker: str, days: Annotated[int, Query(ge=1, le=90)] = 30) -> dict[str, object]:
    result = overview(_ticker(ticker), days=days)
    return {"ticker": result["ticker"], "sample_size": result["analysed_count"], "topics": result["topics"], "concerns": result["concerns"]}


@app.get("/analytics/trends")
def analytics_trends(ticker: str, days: Annotated[int, Query(ge=1, le=90)] = 30) -> dict[str, object]:
    result = overview(_ticker(ticker), days=days)
    return {
        "ticker": result["ticker"], "sample_size": result["sample_size"],
        "volume": result["volume"], "sentiment_trend": result["sentiment_trend"],
        "mood_direction": result["mood_direction"],
    }


@app.get("/discussions")
def get_discussions(
    ticker: str, days: Annotated[int, Query(ge=1, le=90)] = 30,
    source: str | None = None, sentiment: str | None = None,
    topic: str | None = None, search: str | None = None,
) -> list[dict[str, object]]:
    return discussions(_ticker(ticker), days=days, source=source, sentiment=sentiment, topic=topic, search=search)


@app.post("/ask")
def ask_question(request: AskRequest) -> dict[str, object]:
    try:
        return ask(request.question, _ticker(request.ticker)).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
