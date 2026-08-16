"""Public The Ken company/search metadata adapter with paywall detection."""
from __future__ import annotations
from typing import Any, Callable
from urllib.parse import quote_plus
from .startup_public_base import AdapterResult, access_outcome, failed, fetch_doc, is_no_results, item, outcome, parse_date
from .startup_web import canonical_url, safe_links

SOURCE = "the-ken"
DOMAINS = ("the-ken.com",)

class TheKenAdapter:
    source = SOURCE
    def fetch(self, *, entity_id: str, query: str = "", url: str | None = None, max_pages: int = 1,
              timeout: float = 15.0, fetcher: Callable[..., Any] | None = None, **_: Any) -> AdapterResult:
        target = url or (f"https://the-ken.com/company/?q={quote_plus(query)}" if query else "https://the-ken.com/")
        try:
            response, doc, access = fetch_doc(target, source=SOURCE, allowed_domains=DOMAINS, timeout=timeout, fetcher=fetcher)
        except Exception as exc:
            return failed(SOURCE, entity_id, exc)
        metadata = {"entity_id": entity_id, "access_state": access, "access_mode": "public-http", "canonical_url": response.url,
                    "author": doc.metadata.get("author"), "section": doc.metadata.get("article:section")}
        if access in {"paywalled", "login-required", "captcha", "bot"}:
            # Keep the URL and access state as an auditable limitation, never
            # copy subscriber-only preview text into evidence.
            limited = item(SOURCE, entity_id, url=response.url, title=doc.title or "The Ken restricted coverage", body="",
                           metadata={"access_state": "paywalled" if access == "paywalled" else access, "restricted": True}, claim_type="access-limitation")
            limited.metadata["access_state"] = access
            return AdapterResult([limited], access_outcome(SOURCE, access, items=1, detail=f"access_state={access}"), metadata)
        if is_no_results(doc.title + " " + doc.text):
            return AdapterResult([], outcome(SOURCE, "no-results"), metadata)
        results = []
        canonical = doc.metadata.get("og:url") or response.url
        try:
            canonical = canonical_url(canonical, allowed_domains=DOMAINS)
        except Exception:
            canonical = response.url
        published = parse_date(doc.metadata.get("article:published_time") or doc.metadata.get("date") or next((x.get("datePublished") for x in doc.jsonld if x.get("datePublished")), None))
        results.append(item(SOURCE, entity_id, url=canonical, title=doc.title or query or "The Ken company coverage", body=doc.text,
                            author=doc.metadata.get("author"), published_at=published, metadata={"author": metadata["author"], "section": metadata["section"]}, claim_type="article" if published else "company-search"))
        for link in safe_links(doc, DOMAINS, limit=100):
            if link == canonical or not ("/" in link):
                continue
            title = next((text for href, text in doc.links if href == link), "The Ken story card")
            if title:
                results.append(item(SOURCE, entity_id, url=link, title=title, body="", metadata={"parent_url": canonical}, claim_type="article-card"))
            if len(results) >= 50:
                break
        if not doc.title and not doc.text:
            return AdapterResult([], outcome(SOURCE, "schema-drift", detail="missing title and visible body"), metadata)
        return AdapterResult(results, outcome(SOURCE, "ok", items=len(results)), metadata)

def fetch(**kwargs: Any) -> AdapterResult:
    return TheKenAdapter().fetch(**kwargs)

__all__ = ["TheKenAdapter", "fetch"]
