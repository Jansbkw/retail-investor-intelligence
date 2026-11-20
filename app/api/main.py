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
from app.config import (
    ROOT,
    company_identity,
    company_registry,
    get_settings,
    load_file_config,
)
from app.db import connect, init_db, list_coverage
from app.pipeline.aggregate import discussions, overview
from app.pipeline.entity_resolution import classify_messages
from app.reference_data.finnhub import FinnhubUnavailable, search_symbols


class AskRequest(BaseModel):
    company_id: str
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


def _company(value: str):
    identity = company_identity(value)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"Unknown company: {value}")
    return identity


def _company_payload(identity) -> dict[str, object]:
    init_db()
    with connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM posts WHERE company_id=? AND relevance_status='relevant'",
            (identity.company_id,),
        ).fetchone()[0]
    return {
        **identity.model_dump(),
        "verified": True,
        "verified_discussions": count,
        "coverage_status": "available" if count else "limited",
    }


@app.get("/health")
def health() -> dict[str, object]:
    init_db()
    with connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    return {"status": "ok", "database": "ready", "posts": count, "llm_configured": settings.llm_enabled}


@app.get("/companies")
def companies() -> list[dict[str, object]]:
    return [_company_payload(identity) for identity in company_registry().values()]


@app.get("/companies/search")
def search_companies(q: str = "") -> list[dict[str, object]]:
    query = q.strip().casefold()
    identities = list(company_registry().values())
    if query:
        identities = [
            item for item in identities
            if query in item.ticker.casefold()
            or query in item.name.casefold()
            or query in item.exchange.casefold()
            or query in item.country.casefold()
        ]
    else:
        identities = [item for item in identities if item.analytics_enabled]
    identities.sort(key=lambda item: (
        0 if query and item.ticker.casefold() == query else 1,
        0 if item.analytics_enabled else 1,
    ))
    return [_company_payload(identity) for identity in identities]


@app.get("/companies/{company_id}")
def get_company(company_id: str) -> dict[str, object]:
    return _company_payload(_company(company_id))


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

    reference_lookup: dict[str, object] = {
        "provider": "finnhub", "status": "not_configured", "candidates": [],
        "limitation": "Provider candidates require exchange/ISIN verification",
    }
    if settings.finnhub_api_key:
        try:
            reference_lookup["candidates"] = search_symbols(selected, settings=settings)
            reference_lookup["status"] = "success"
        except FinnhubUnavailable as exc:
            reference_lookup["status"] = "unavailable"
            reference_lookup["error"] = str(exc)

    return {
        "ticker": selected,
        "target": {"name": company.name, "exchange": company.exchange},
        "requires_selection": len(active) > 1,
        "active_candidates": active,
        "other_matches": other,
        "reference_lookup": reference_lookup,
        "source_classification": source,
    }


@app.get("/coverage")
def coverage(company_id: str | None = None) -> list[dict[str, object]]:
    selected = _company(company_id).company_id if company_id else None
    return [dict(row) for row in list_coverage() if not selected or row["company_id"] == selected]


@app.get("/analytics/overview")
def analytics_overview(
    company_id: str, days: Annotated[int, Query(ge=1, le=90)] = 30,
    source: list[str] | None = Query(default=None),
) -> dict[str, object]:
    return overview(_company(company_id).company_id, days=days, sources=source)


@app.get("/analytics/sentiment")
def analytics_sentiment(company_id: str, days: Annotated[int, Query(ge=1, le=90)] = 30) -> dict[str, object]:
    result = overview(_company(company_id).company_id, days=days)
    return {"company_id": result["company_id"], "ticker": result["ticker"], "sample_size": result["analysed_count"], "sentiment": result["sentiment"]}


@app.get("/analytics/topics")
def analytics_topics(company_id: str, days: Annotated[int, Query(ge=1, le=90)] = 30) -> dict[str, object]:
    result = overview(_company(company_id).company_id, days=days)
    return {"company_id": result["company_id"], "ticker": result["ticker"], "sample_size": result["analysed_count"], "topics": result["topics"], "concerns": result["concerns"]}


@app.get("/analytics/trends")
def analytics_trends(company_id: str, days: Annotated[int, Query(ge=1, le=90)] = 30) -> dict[str, object]:
    result = overview(_company(company_id).company_id, days=days)
    return {
        "company_id": result["company_id"], "ticker": result["ticker"], "sample_size": result["sample_size"],
        "volume": result["volume"], "sentiment_trend": result["sentiment_trend"],
        "mood_direction": result["mood_direction"],
    }


@app.get("/discussions")
def get_discussions(
    company_id: str, days: Annotated[int, Query(ge=1, le=90)] = 30,
    source: str | None = None, sentiment: str | None = None,
    topic: str | None = None, search: str | None = None,
) -> list[dict[str, object]]:
    return discussions(_company(company_id).company_id, days=days, source=source, sentiment=sentiment, topic=topic, search=search)


@app.post("/ask")
def ask_question(request: AskRequest) -> dict[str, object]:
    try:
        return ask(request.question, _company(request.company_id).company_id).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
