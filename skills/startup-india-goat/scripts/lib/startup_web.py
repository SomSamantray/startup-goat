"""Safe, bounded public-web primitives for Startup India GOAT adapters.

This module intentionally has no source-specific selectors.  It validates every
URL before a request, treats response text as untrusted data, and exposes only
small parsed projections to source adapters.
"""
from __future__ import annotations

import html as html_lib
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Iterable, Mapping

ACCESS_MARKERS: dict[str, tuple[str, ...]] = {
    "captcha": ("captcha", "i am not a robot", "recaptcha", "hcaptcha"),
    "paywalled": ("subscribe to read", "subscription required", "premium content", "become a member", "paywall"),
    "login-required": ("sign in to continue", "log in to continue", "please log in", "login required"),
    "bot": ("access denied", "unusual traffic", "automated queries", "verify you are human", "bot detection"),
}


class UnsafeURL(ValueError):
    """Raised before an unapproved URL is fetched."""


class WebFetchError(RuntimeError):
    def __init__(self, message: str, *, state: str = "unreachable", status: int | None = None):
        super().__init__(message)
        self.state = state
        self.status = status


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    body: str
    content_type: str = "text/html"
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    url: str
    title: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.metadata: dict[str, str] = {}
        self.jsonld_text: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._in_script = False
        self._in_title = False
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.tables: list[list[list[str]]] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(k).lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            if key and values.get("content"):
                self.metadata[key.casefold()] = values["content"].strip()
        elif tag == "a":
            self._href = values.get("href") or None
            self._link_text = []
        elif tag == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._in_script = True
        elif tag == "title":
            self._in_title = True
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._link_text).strip()))
            self._href = None
            self._link_text = []
        elif tag == "script" and self._in_script:
            self._in_script = False
        elif tag == "title":
            self._in_title = False
        elif tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if self._in_script:
            self.jsonld_text.append(data)
        elif clean:
            self.parts.append(clean)
            if self._href is not None:
                self._link_text.append(clean)
            if self._cell is not None:
                self._cell.append(clean)
            if self._in_title:
                self.title_parts.append(clean)


def truncate_text(value: Any, limit: int = 1_000) -> str:
    text = re.sub(r"\s+", " ", html_lib.unescape(str(value or "")).strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def validate_url(url: str, allowed_domains: Iterable[str], *, allow_query: bool = True) -> str:
    parsed = urllib.parse.urlsplit(str(url).strip())
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise UnsafeURL("only HTTPS URLs with a hostname are allowed")
    host = parsed.hostname.casefold().rstrip(".")
    allowed = {d.casefold().lstrip(".").rstrip(".") for d in allowed_domains}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise UnsafeURL(f"host is not allowlisted: {host}")
    if parsed.username or parsed.password:
        raise UnsafeURL("credentials in URL are not allowed")
    if not allow_query and parsed.query:
        raise UnsafeURL("query string is not allowed for this route")
    if _literal_private_ip(host):
        raise UnsafeURL("private or loopback address is not allowed")
    return urllib.parse.urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _literal_private_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified)


def validate_resolved_host(host: str, *, resolver: Callable[..., Any] = socket.getaddrinfo) -> None:
    """Reject private DNS answers when a caller elects to resolve a host."""
    for answer in resolver(host, None, socket.SOCK_STREAM):
        sockaddr = answer[4]
        address = ipaddress.ip_address(sockaddr[0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified:
            raise UnsafeURL("hostname resolves to a private address")


def canonical_url(url: str, *, base_url: str | None = None, allowed_domains: Iterable[str] = ()) -> str:
    absolute = urllib.parse.urljoin(base_url or url, url)
    parsed = urllib.parse.urlsplit(absolute)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if not k.casefold().startswith(("utm_", "fbclid", "gclid"))]
    return validate_url(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")), allowed_domains)


def classify_access(text: str, *, status: int = 200) -> str:
    if status == 401:
        return "login-required"
    if status == 402:
        return "paywalled"
    if status == 403:
        return "bot"
    if status == 429:
        return "rate-limited"
    lower = re.sub(r"\s+", " ", text.casefold())[:40_000]
    for state, markers in ACCESS_MARKERS.items():
        if any(marker in lower for marker in markers):
            return state
    return "public"


def parse_jsonld(values: Iterable[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in values:
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            continue
        candidates = decoded if isinstance(decoded, list) else [decoded]
        for candidate in candidates:
            if isinstance(candidate, dict):
                result.append(candidate)
    return result


def parse_document(body: str, url: str) -> ParsedDocument:
    parser = _DocumentParser()
    try:
        parser.feed(body[:2_000_000])
    except Exception:
        # HTMLParser is deliberately best-effort; malformed source becomes a
        # degraded document rather than executable content.
        pass
    return ParsedDocument(
        url=url,
        title=truncate_text(" ".join(parser.title_parts), 300),
        text=truncate_text(" ".join(parser.parts), 12_000),
        links=parser.links,
        metadata=parser.metadata,
        jsonld=parse_jsonld(parser.jsonld_text),
        tables=parser.tables,
    )


def extract_jsonld(document: ParsedDocument, types: Iterable[str] = ()) -> list[dict[str, Any]]:
    wanted = {item.casefold() for item in types}
    if not wanted:
        return list(document.jsonld)
    return [item for item in document.jsonld if str(item.get("@type", "")).casefold() in wanted]


def extract_tables(document: ParsedDocument, *, max_rows: int = 200) -> list[list[list[str]]]:
    return [[row[:50] for row in table[:max_rows]] for table in document.tables]


def safe_links(document: ParsedDocument, allowed_domains: Iterable[str], *, limit: int = 50) -> list[str]:
    links: list[str] = []
    for href, _ in document.links:
        try:
            value = canonical_url(href, base_url=document.url, allowed_domains=allowed_domains)
        except (UnsafeURL, ValueError):
            continue
        if value not in links:
            links.append(value)
        if len(links) >= limit:
            break
    return links


def page_urls(first_url: str, *, max_pages: int = 1, allowed_domains: Iterable[str]) -> list[str]:
    """Return bounded URLs while preventing page-number loops."""
    if max_pages < 1:
        return []
    parsed = urllib.parse.urlsplit(first_url)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    result: list[str] = []
    for page in range(max_pages):
        current = dict(params)
        current["page"] = [str(page)]
        value = canonical_url(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(current, doseq=True), "")), allowed_domains=allowed_domains)
        if value in result:
            break
        result.append(value)
    return result


def fetch_public(url: str, *, allowed_domains: Iterable[str], timeout: float = 15.0,
                 fetcher: Callable[[str, float], Any] | None = None,
                 max_bytes: int = 2_000_000) -> tuple[FetchResponse, ParsedDocument, str]:
    safe = validate_url(url, allowed_domains)
    if fetcher is None:
        # Validate DNS answers before opening a URL. A hostname allowlist alone
        # does not prevent DNS rebinding to loopback or private address space.
        validate_resolved_host(urllib.parse.urlsplit(safe).hostname or "")
    if fetcher is not None:
        try:
            raw = fetcher(safe, timeout)
        except TypeError:
            raw = fetcher(safe)  # type: ignore[misc]
        if isinstance(raw, FetchResponse):
            response = raw
        elif isinstance(raw, str):
            response = FetchResponse(safe, 200, raw)
        elif isinstance(raw, tuple):
            response = FetchResponse(safe, int(raw[0]), str(raw[1]))
        else:
            response = FetchResponse(str(getattr(raw, "url", safe)), int(getattr(raw, "status", 200)), str(getattr(raw, "text", "")))
    else:
        request = urllib.request.Request(safe, headers={"User-Agent": "startup-india-goat/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as handle:
                final = str(handle.geturl() or safe)
                validate_url(final, allowed_domains)
                body = handle.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise WebFetchError("response exceeds safety limit", state="schema-drift")
                response = FetchResponse(final, int(getattr(handle, "status", 200)), body.decode("utf-8", "replace"), str(handle.headers.get("Content-Type", "text/html")), dict(handle.headers.items()))
        except urllib.error.HTTPError as exc:
            state = "rate-limited" if exc.code == 429 else "login-required" if exc.code in {401} else "bot" if exc.code == 403 else "unreachable"
            raise WebFetchError(f"HTTP {exc.code}", state=state, status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            state = "timeout" if isinstance(getattr(exc, "reason", exc), TimeoutError) else "unreachable"
            raise WebFetchError("public request failed", state=state) from exc
    validate_url(response.url, allowed_domains)
    state = classify_access(response.body, status=response.status)
    return response, parse_document(response.body, response.url), state


__all__ = ["ACCESS_MARKERS", "FetchResponse", "ParsedDocument", "UnsafeURL", "WebFetchError", "canonical_url", "classify_access", "extract_jsonld", "extract_tables", "fetch_public", "page_urls", "parse_document", "safe_links", "truncate_text", "validate_resolved_host", "validate_url"]
