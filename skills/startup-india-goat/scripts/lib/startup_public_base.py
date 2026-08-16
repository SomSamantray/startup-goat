"""Shared result and item helpers for public Startup India GOAT adapters."""
from __future__ import annotations
import hashlib
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable
from .schema import SourceItem, SourceOutcome
from .startup_web import WebFetchError, fetch_public, truncate_text

@dataclass
class AdapterResult:
    items: list[SourceItem] = field(default_factory=list)
    outcome: SourceOutcome | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    def __iter__(self): return iter(self.items)
    def __len__(self): return len(self.items)
    def __getitem__(self, index): return self.items[index]


def stable_id(source: str, entity_id: str, url: str, suffix: str = "") -> str:
    return f"{source}_{hashlib.sha256('|'.join((entity_id, url, suffix)).encode()).hexdigest()[:20]}"


def item(source: str, entity_id: str, *, url: str, title: str, body: str = "", published_at: str | None = None,
         metadata: dict[str, Any] | None = None, author: str | None = None, claim_type: str = "article") -> SourceItem:
    return SourceItem(
        item_id=stable_id(source, entity_id, url, title), source=source, title=truncate_text(title, 300) or "Untitled",
        body=truncate_text(body, 6_000), url=url, author=truncate_text(author, 200) if author else None,
        published_at=published_at, date_confidence="high" if published_at else "low", relevance_hint=0.8,
        why_relevant=f"{source} {claim_type} bound to entity {entity_id}", snippet=truncate_text(body, 500),
        metadata={"entity_id": entity_id, "access_state": "public", "access_mode": "public-http", "claim_type": claim_type, **(metadata or {})},
    )


def parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"\\b(20\\d{2})[-/]([01]\\d)[-/]([0-3]\\d)\\b", text)
    if match:
        try:
            return datetime.strptime("-".join(match.groups()), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    return None


def is_no_results(text: str) -> bool:
    value = str(text or "").casefold()
    return any(marker in value for marker in ("no results", "no startups found", "nothing found", "no stories found"))


def access_outcome(source: str, access_state: str, *, items: int = 0, detail: str | None = None) -> SourceOutcome:
    state = {"rate-limited": "rate-limited", "timeout": "timeout", "bot": "auth-failed", "login-required": "auth-failed"}.get(access_state, "partial")
    return outcome(source, state, items=items, detail=detail)


def outcome(source: str, state: str, *, items: int = 0, detail: str | None = None, fix_hint: str | None = None) -> SourceOutcome:
    allowed = {"ok", "no-results", "partial", "rate-limited", "auth-failed", "unreachable", "timeout", "schema-drift", "skipped-unconfigured", "error"}
    return SourceOutcome(source=source, state=state if state in allowed else "error", items_returned=items, detail=detail, fix_hint=fix_hint)


def fetch_doc(url: str, *, source: str, allowed_domains: tuple[str, ...], timeout: float, fetcher: Callable[..., Any] | None):
    try:
        return fetch_public(url, allowed_domains=allowed_domains, timeout=timeout, fetcher=fetcher)
    except WebFetchError:
        raise


def failed(source: str, entity_id: str, exc: Exception) -> AdapterResult:
    state = getattr(exc, "state", "unreachable")
    if state == "bot": state = "auth-failed"
    if state == "rate-limited": state = "rate-limited"
    metadata = {"entity_id": entity_id, "access_state": getattr(exc, "state", "unknown"), "access_mode": "none"}
    return AdapterResult([], outcome(source, state, detail=str(exc)), metadata)
