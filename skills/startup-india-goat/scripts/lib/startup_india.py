"""Public Startup India listing and DPIIT profile adapter."""
from __future__ import annotations
import re
from typing import Any, Callable
from urllib.parse import quote_plus
from .startup_public_base import AdapterResult, access_outcome, failed, fetch_doc, is_no_results, item, outcome, parse_date
from .startup_web import canonical_url, safe_links

SOURCE = "startup-india"
DOMAINS = ("startupindia.gov.in",)
PROFILE_RE = re.compile(r"/profile\.Startup\.([^./?#]+)\.html", re.I)

class StartupIndiaAdapter:
    source = SOURCE
    def fetch(self, *, entity_id: str, query: str = "", url: str | None = None, max_pages: int = 2,
              timeout: float = 15.0, fetcher: Callable[..., Any] | None = None, **_: Any) -> AdapterResult:
        target = url or (f"https://www.startupindia.gov.in/content/sih/en/profile.Startup.{query}.html" if query and re.fullmatch(r"[A-Za-z0-9_-]+", query) else f"https://www.startupindia.gov.in/content/sih/en/search.html?roles=Startup&query={quote_plus(query)}")
        try:
            response, doc, access = fetch_doc(target, source=SOURCE, allowed_domains=DOMAINS, timeout=timeout, fetcher=fetcher)
        except Exception as exc:
            return failed(SOURCE, entity_id, exc)
        profile_id = (PROFILE_RE.search(response.url) or PROFILE_RE.search(target))
        profile_id = profile_id.group(1) if profile_id else None
        metadata = {"entity_id": entity_id, "access_state": access, "access_mode": "public-http", "profile_id": profile_id,
                    "portal_last_updated": doc.metadata.get("last-updated") or doc.metadata.get("article:modified_time"),
                    "source_fields": {k: doc.metadata[k] for k in ("description", "stage", "industry", "city", "state", "dpiit-recognized") if k in doc.metadata}}
        if access != "public":
            return AdapterResult([], access_outcome(SOURCE, access, detail=f"access_state={access}"), metadata)
        links = safe_links(doc, DOMAINS, limit=150)
        records = []
        for link in links:
            if "/profile.Startup." not in link:
                continue
            title = next((text for href, text in doc.links if href == link), "Startup India listing")
            records.append(item(SOURCE, entity_id, url=link, title=title or "Startup India listing", body="", metadata={"profile_id": (PROFILE_RE.search(link).group(1) if PROFILE_RE.search(link) else None), "stage": doc.metadata.get("stage"), "city": doc.metadata.get("city"), "industry": doc.metadata.get("industry"), "dpiit_recognized": doc.metadata.get("dpiit-recognized")}, claim_type="listing"))
            if len(records) >= 100:
                break
        if profile_id or "/profile.Startup." in response.url:
            published = parse_date(doc.metadata.get("joined-date") or doc.metadata.get("date") or doc.metadata.get("article:modified_time"))
            records.insert(0, item(SOURCE, entity_id, url=response.url, title=doc.title or query or "Startup India profile", body=doc.text,
                                   published_at=published, metadata={"profile_id": profile_id, "dpiit_recognized": doc.metadata.get("dpiit-recognized"), "stage": doc.metadata.get("stage"), "industry": doc.metadata.get("industry"), "city": doc.metadata.get("city"), "state": doc.metadata.get("state"), "portal_last_updated": metadata["portal_last_updated"]}, claim_type="dpiit-profile"))
        if is_no_results(doc.title + " " + doc.text):
            return AdapterResult([], outcome(SOURCE, "no-results"), metadata)
        if not records and not doc.title and not doc.text:
            return AdapterResult([], outcome(SOURCE, "no-results"), metadata)
        if not records:
            records.append(item(SOURCE, entity_id, url=response.url, title=doc.title or "Startup India search", body=doc.text,
                                metadata={"portal_last_updated": metadata["portal_last_updated"]}, claim_type="listing-search"))
        return AdapterResult(records, outcome(SOURCE, "ok", items=len(records)), metadata)

def fetch(**kwargs: Any) -> AdapterResult:
    return StartupIndiaAdapter().fetch(**kwargs)

__all__ = ["StartupIndiaAdapter", "fetch"]
