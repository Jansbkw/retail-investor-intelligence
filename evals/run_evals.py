from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.rag import ask
from app.collectors.base import Post
from app.config import load_file_config
from app.db import connect
from app.pipeline.relevance import assess_relevance


def load_cases() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "evals/cases.jsonl").read_text().splitlines() if line]


def evaluate(case: dict) -> tuple[bool, str]:
    if case["type"] == "enrichment":
        with connect() as connection:
            row = connection.execute(
                "SELECT sentiment_label, topics_json, status FROM analysis WHERE post_id=?",
                (case["post_id"],),
            ).fetchone()
        passed = bool(row and row["status"] == "success" and
                      row["sentiment_label"] == case["sentiment"] and
                      case["topic"] in json.loads(row["topics_json"]))
        return passed, case["post_id"]

    if case["type"] == "relevance":
        company = load_file_config().companies[case["ticker"]]
        now = datetime.now(timezone.utc)
        post = Post(
            source="eval", source_post_id=case["ticker"] + case["expected"],
            ticker=case["ticker"], company_id=company.company_id,
            company_name=company.name, raw_text=case["text"],
            created_at=now, collected_at=now, source_url="https://example.invalid/eval",
        )
        actual = assess_relevance(post, company).status.value
        return actual == case["expected"], f"{case['ticker']}: {case['text']} -> {actual}"

    company_id = load_file_config().companies[case["ticker"]].company_id
    # Regression evaluation is deterministic and must never incur live API calls.
    with patch("app.ai.rag.get_settings", return_value=SimpleNamespace(llm_enabled=False)):
        result = ask(case["question"], company_id)
    passed = {
        "refusal": result.refused_investment_advice,
        "abstention": result.evidence_count == 0 and not result.citations,
        "citations": result.evidence_count >= 2 and len(result.citations) >= 2,
    }[case["expected"]]
    return bool(passed), f"{case['ticker']}: {case['expected']}"


def main() -> None:
    results = []
    for case in load_cases():
        passed, detail = evaluate(case)
        results.append({"type": case["type"], "passed": passed, "detail": detail})
    totals = Counter(item["type"] for item in results)
    passed = Counter(item["type"] for item in results if item["passed"])
    report = {
        "total": len(results), "passed": sum(item["passed"] for item in results),
        "by_type": {kind: {"passed": passed[kind], "total": total} for kind, total in totals.items()},
        "failures": [item["detail"] for item in results if not item["passed"]],
        "note": "Regression set; enrichment labels are reviewed build-time outputs, not independent expert ground truth.",
    }
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
