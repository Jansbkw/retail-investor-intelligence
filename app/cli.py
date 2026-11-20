from __future__ import annotations

import argparse
import json
import logging

from app.config import load_file_config
from app.db import init_db
from app.pipeline.enrich import enrich_posts, import_enrichment
from app.pipeline.ingest import ingest


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Retail Investor Intelligence batch jobs")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")

    collect = commands.add_parser("ingest", help="Collect, normalise, filter, and persist records")
    collect.add_argument("--ticker", action="append", choices=list(load_file_config().companies))
    source_choices = sorted(set(load_file_config().collection.platforms) | {"x"})
    collect.add_argument("--source", action="append", choices=source_choices)
    collect.add_argument("--days", type=int, default=30)
    collect.add_argument("--stocktwits-export")

    enrich = commands.add_parser("enrich", help="Enrich relevant, changed records with the configured LLM")
    enrich.add_argument("--ticker", action="append", choices=list(load_file_config().companies))

    imported = commands.add_parser("import-enrichment", help="Import schema-validated approved LLM output")
    imported.add_argument("path")

    demo = commands.add_parser("prepare-demo", help="Build the database from real MCP data and approved enrichment")
    demo.add_argument("--enrichment", default="data/live/enrichment_codex_2026-11-20.json")
    return root


def main() -> None:
    args = parser().parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if args.command == "init-db":
        init_db()
        result: object = {"status": "database ready"}
    elif args.command == "ingest":
        from app.pipeline.ingest import default_collectors
        result = ingest(
            tickers=args.ticker, sources=args.source, days=args.days,
            collectors=default_collectors(args.stocktwits_export),
        )
    elif args.command == "enrich":
        init_db()
        result = enrich_posts(tickers=args.ticker)
    elif args.command == "import-enrichment":
        init_db()
        result = import_enrichment(args.path)
    else:
        reports = ingest(days=30)
        enrichment = import_enrichment(args.enrichment)
        result = {"collection": reports, "enrichment": enrichment}
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
