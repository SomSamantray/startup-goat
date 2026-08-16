"""Public Screener company snapshot and filing adapter."""
from __future__ import annotations
import re
from typing import Any, Callable
from urllib.parse import quote_plus
from .startup_public_base import AdapterResult, access_outcome, failed, fetch_doc, item, outcome, parse_date
from .startup_web import safe_links

SOURCE = "screener"
DOMAINS = ("screener.in", "bseindia.com", "nseindia.com")

class ScreenerAdapter:
    source = SOURCE
    def fetch(self, *, entity_id: str, query: str = "", ticker: str | None = None, url: str | None = None,
              max_pages: int = 1, timeout: float = 15.0, fetcher: Callable[..., Any] | None = None, **_: Any) -> AdapterResult:
        symbol = (ticker or "").strip().upper().lstrip("$")
        if not url and not ticker:
            return AdapterResult([], outcome(SOURCE, "skipped-unconfigured", detail="not-applicable: no verified listed-company identifier"), {"entity_id": entity_id, "access_state": "not-applicable", "access_mode": "none"})
        if not url and not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,30}", symbol):
            return AdapterResult([], outcome(SOURCE, "skipped-unconfigured", detail="not-applicable: invalid listed-company identifier"), {"entity_id": entity_id, "access_state": "not-applicable", "access_mode": "none"})
        target = url or f"https://www.screener.in/company/{quote_plus(symbol)}/consolidated/"
        try:
            response, doc, access = fetch_doc(target, source=SOURCE, allowed_domains=DOMAINS, timeout=timeout, fetcher=fetcher)
        except Exception as exc:
            return failed(SOURCE, entity_id, exc)
        metadata = {"entity_id": entity_id, "access_state": access, "access_mode": "public-http", "ticker": symbol,
                    "tables": doc.tables, "company_url": response.url}
        if access != "public":
            return AdapterResult([], access_outcome(SOURCE, access, detail=f"access_state={access}"), metadata)
        links = safe_links(doc, DOMAINS, limit=100)
        dates = [parse_date(value) for value in (doc.metadata.get("date") or "", doc.metadata.get("article:published_time") or "")]
        facts = {key: doc.metadata.get(key) for key in ("market-cap", "pe", "book-value", "dividend-yield", "roce", "roe", "face-value", "bse", "nse", "website") if doc.metadata.get(key)}
        snapshot = item(SOURCE, entity_id, url=response.url, title=doc.title or symbol, body=doc.text,
                        published_at=next((d for d in dates if d), None), metadata={"ticker": symbol, "structured_facts": facts, "tables": doc.tables, "units": "INR crore where shown", "generated_commentary": True}, claim_type="company-snapshot")
        results = [snapshot]
        for link in links:
            if link.lower().endswith((".pdf", ".pdf?")) or "/documents/" in link or "announcements" in link:
                results.append(item(SOURCE, entity_id, url=link, title="Public Screener filing or announcement", body="", metadata={"ticker": symbol, "linked_from": response.url}, claim_type="filing"))
                if len(results) >= 50:
                    break
        if not doc.title and not doc.tables:
            return AdapterResult([], outcome(SOURCE, "schema-drift", detail="missing company title and financial tables"), metadata)
        return AdapterResult(results, outcome(SOURCE, "ok", items=len(results)), metadata)

def fetch(**kwargs: Any) -> AdapterResult:
    return ScreenerAdapter().fetch(**kwargs)

__all__ = ["ScreenerAdapter", "fetch"]
