"""Public Inc42 archive, article, and company-card adapter."""
from __future__ import annotations
from typing import Any, Callable
from urllib.parse import quote_plus
from .startup_public_base import AdapterResult, access_outcome, failed, fetch_doc, is_no_results, item, outcome, parse_date
from .startup_web import canonical_url, safe_links

SOURCE = "inc42"
DOMAINS = ("inc42.com",)

class Inc42Adapter:
    source = SOURCE
    def fetch(self, *, entity_id: str, query: str = "", url: str | None = None, max_pages: int = 2,
              timeout: float = 15.0, fetcher: Callable[..., Any] | None = None, **_: Any) -> AdapterResult:
        target = url or (f"https://inc42.com/?s={quote_plus(query)}" if query else "https://inc42.com/startups/")
        try:
            response, doc, access = fetch_doc(target, source=SOURCE, allowed_domains=DOMAINS, timeout=timeout, fetcher=fetcher)
        except Exception as exc:
            return failed(SOURCE, entity_id, exc)
        metadata = {"entity_id": entity_id, "access_state": access, "access_mode": "public-http", "canonical_url": response.url,
                    "category": doc.metadata.get("article:section") or doc.metadata.get("category"), "author": doc.metadata.get("author"),
                    "reading_time": doc.metadata.get("reading-time")}
        if access != "public":
            return AdapterResult([], access_outcome(SOURCE, access, detail=f"access_state={access}"), metadata)
        if is_no_results(doc.title + " " + doc.text):
            return AdapterResult([], outcome(SOURCE, "no-results"), metadata)
        results = []
        canonical = doc.metadata.get("og:url") or response.url
        try:
            canonical = canonical_url(canonical, allowed_domains=DOMAINS)
        except Exception:
            canonical = response.url
        published = parse_date(doc.metadata.get("article:published_time") or doc.metadata.get("date") or next((x.get("datePublished") for x in doc.jsonld if x.get("datePublished")), None))
        results.append(item(SOURCE, entity_id, url=canonical, title=doc.title or query or "Inc42 startup archive", body=doc.text,
                            author=doc.metadata.get("author"), published_at=published, metadata={"category": metadata["category"], "reading_time": metadata["reading_time"], "source_fields": metadata}, claim_type="article" if published else "archive"))
        for link in safe_links(doc, DOMAINS, limit=120):
            if link == canonical or not link.startswith("https://inc42.com/"):
                continue
            title = next((text for href, text in doc.links if href == link), "Inc42 startup coverage")
            if not title:
                continue
            results.append(item(SOURCE, entity_id, url=link, title=title, body="", metadata={"parent_url": canonical, "category": metadata["category"]}, claim_type="article-card"))
            if len(results) >= 60:
                break
        if not doc.title and not doc.text and not results:
            return AdapterResult([], outcome(SOURCE, "no-results"), metadata)
        return AdapterResult(results, outcome(SOURCE, "ok", items=len(results)), metadata)

def fetch(**kwargs: Any) -> AdapterResult:
    return Inc42Adapter().fetch(**kwargs)

__all__ = ["Inc42Adapter", "fetch"]
