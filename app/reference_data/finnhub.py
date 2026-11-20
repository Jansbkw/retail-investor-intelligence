from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import Settings, get_settings


class FinnhubUnavailable(RuntimeError):
    pass


def search_symbols(
    query: str, *, settings: Settings | None = None, client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Return Finnhub security candidates without treating them as verified entities."""

    resolved_settings = settings or get_settings()
    if not resolved_settings.finnhub_api_key:
        raise FinnhubUnavailable("FINNHUB_API_KEY is not configured")
    resolved_client = client or httpx.Client(timeout=15)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = resolved_client.get(
                "https://finnhub.io/api/v1/search",
                params={"q": query, "token": resolved_settings.finnhub_api_key},
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Finnhub temporary error {response.status_code}",
                    request=response.request, response=response,
                )
            if response.status_code >= 400:
                raise FinnhubUnavailable(f"Finnhub unavailable ({response.status_code})")
            payload = response.json()
            if payload.get("error"):
                raise FinnhubUnavailable(str(payload["error"]))
            prefix = query.upper()
            results = []
            for item in payload.get("result") or []:
                display = str(item.get("displaySymbol") or item.get("symbol") or "")
                if display.upper() == prefix or display.upper().startswith(f"{prefix}."):
                    results.append({
                        "symbol": item.get("symbol"),
                        "display_symbol": display,
                        "description": item.get("description"),
                        "security_type": item.get("type"),
                        "verification_status": "provider_candidate",
                    })
            return results
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.25 * (2 ** attempt))
    raise FinnhubUnavailable(f"Finnhub request failed after retries: {last_error}")
