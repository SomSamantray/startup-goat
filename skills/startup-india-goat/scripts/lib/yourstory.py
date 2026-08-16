"""Public YourStory company, search, category, and article adapter."""
from __future__ import annotations
from typing import Any, Callable
from urllib.parse import quote_plus
from .startup_public_base import AdapterResult, access_outcome, failed, fetch_doc, is_no_results, item, outcome, parse_date
from .startup_web import canonical_url, safe_links, WebFetchError

SOURCE = "yourstory"
DOMAINS = ("yourstory.com",)

class YourStoryAdapter:
    source = SOURCE
    def fetch(self, *, entity_id: str, query: str = "", url: str | None = None, max_pages: int = 2,
              timeout: float = 15.0, fetcher: Callable[..., Any] | None = None, **_: Any) -> AdapterResult:
        target = url or (f"https://yourstory.com/companies/{query.strip().lower().replace(' ', '-')}" if query else "https://yourstory.com/companies")
        if not url and query and query.startswith("http"):
            target = query
        if not url and query and target.endswith("/companies"):
            target = f"https://yourstory.com/search?q={quote_plus(query)}"
        try:
            response, doc, access = fetch_doc(target, source=SOURCE, allowed_domains=DOMAINS, timeout=timeout, fetcher=fetcher)
        except Exception as exc:
            return failed(SOURCE, entity_id, exc)
        metadata = {"entity_id": entity_id, "access_state": access, "access_mode": "public-http", "canonical_url": response.url,
                    "source_fields": {key: doc.metadata[key] for key in ("description", "article:published_time", "og:description", "og:site_name") if key in doc.metadata}}
        if access != "public":
            return AdapterResult([], access_outcome(SOURCE, access, detail=f"access_state={access}"), metadata)
        canonical = doc.metadata.get("og:url")
        try:
            canonical = canonical_url(canonical or response.url, allowed_domains=DOMAINS)
        except Exception:
            canonical = response.url
        published = parse_date(doc.metadata.get("article:published_time") or doc.metadata.get("date") or next((x.get("datePublished") for x in doc.jsonld if x.get("datePublished")), None))
        structured = {"description": doc.metadata.get("description") or doc.metadata.get("og:description"),
                      "industry": doc.metadata.get("industry"), "headquarters": doc.metadata.get("headquarters"),
                      "legal_name": doc.metadata.get("legal_name"), "source_fields": metadata["source_fields"]}
        if is_no_results(doc.title + " " + doc.text):
            return AdapterResult([], outcome(SOURCE, "no-results"), metadata)
        if not doc.title:
            return AdapterResult([], outcome(SOURCE, "schema-drift", detail="missing title"), metadata)
        links = safe_links(doc, DOMAINS, limit=100)
        items = [item(SOURCE, entity_id, url=canonical, title=doc.title or query or "YourStory company profile", body=doc.text,
                      published_at=published, metadata=structured, claim_type="company-profile")]
        for link in links:
            if link == canonical or not ("/202" in link or "/companies/" in link):
                continue
            title = next((text for href, text in doc.links if href == link), "YourStory coverage")
            items.append(item(SOURCE, entity_id, url=link, title=title or "YourStory coverage", body="", metadata={"parent_url": canonical}, claim_type="article"))
            if len(items) >= 50:
                break
        if not doc.title and not doc.text:
            return AdapterResult([], outcome(SOURCE, "schema-drift", detail="missing title and visible body"), metadata)
        return AdapterResult(items, outcome(SOURCE, "ok", items=len(items)), metadata)


def fetch(**kwargs: Any) -> AdapterResult:
    return YourStoryAdapter().fetch(**kwargs)

__all__ = ["YourStoryAdapter", "fetch"]
