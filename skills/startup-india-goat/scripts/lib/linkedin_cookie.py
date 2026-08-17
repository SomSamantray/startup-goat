"""LinkedIn company-profile adapter using user-supplied session cookies.

Fetches ``https://www.linkedin.com/company/<slug>/`` with a ``Cookie`` header
assembled in memory from user-supplied session cookies and extracts the
server-rendered visible company fields.  Cookies are secrets: they are held
only for the duration of one call, are never persisted, and never appear in
outcomes, items, logs, or diagnostics.

The adapter intentionally does not use Voyager GraphQL, does not replay
captured requests, and never follows a cross-origin redirect with a
credentialed request.  It is one of three LinkedIn lanes: the OAuth
``LinkedInTokenAdapter`` and the ScrapeCreators post-search path remain
available as fallbacks.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from .env import read_secret_env
from .startup_public_base import AdapterResult, item, outcome
from .startup_web import UnsafeURL, parse_document, truncate_text, validate_resolved_host, validate_url

LINKEDIN_SOURCE = "linkedin"
ALLOWED_HOSTS = ("www.linkedin.com", "linkedin.com")
COMPANY_PATH = "/company/{slug}"
# Provider text is untrusted and may echo a credential.
_SECRET = re.compile(r"(?:li_at|jsessionid|bcookie)\s*[=:]\s*[A-Za-z0-9._~+/=-]{8,}", re.I)
_COOKIE_ENV = ("LINKEDIN_LI_AT", "LINKEDIN_JSESSIONID", "LINKEDIN_BCOOKIE")
_AUTHWALL_MARKERS = ("authwall", "sign in to view", "sign in to continue", "please log in", "login required")
# Realistic browser user agent — a bare urllib UA reliably trips LinkedIn's
# edge-level 999 gate before any request reaches the app.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
def _redact(value: Any, secrets: tuple[str, ...]) -> str:
    """Redact cookie values and cookie-shaped strings from provider text.

    Values are replaced literally, then via URL- and HTML-entity-unescaped
    variants so an encoded echo (``li_at%3DAQE%2F...`` or ``li_at&#61;...``)
    cannot survive into evidence.
    """
    import html as _html
    import urllib.parse as _urlparse

    text = str(value or "")
    for secret in secrets:
        if not secret:
            continue
        text = text.replace(secret, "<redacted>")
        try:
            unquoted = _urlparse.unquote(secret)
            if unquoted != secret:
                text = text.replace(unquoted, "<redacted>")
        except Exception:
            pass
        text = text.replace(_html.escape(secret), "<redacted>")
        text = text.replace(_html.escape(secret, quote=True), "<redacted>")
    # Defensive sweep for name=value forms even when the value differs.
    return re.sub(_SECRET, "<redacted>", text)


def _cookie_header(cookies: Mapping[str, str]) -> str:
    """Assemble a ``Cookie`` header from a cookie dict, in memory only."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if name and value is not None)


def _slugify(value: str) -> str:
    """Best-effort display-name to LinkedIn vanity-slug conversion."""
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    return re.sub(r"-{2,}", "-", text)


_FOLLOWERS_RE = re.compile(r"([\d,.]+[kKmM]?)\s+followers\s+(\d+[\s-]+\d+\s*(?:employees?|people))", re.I)
# Industry runs end in one of these recognizable suffixes, which separates
# them from the tagline that precedes them.
_INDUSTRY_SUFFIX_RE = re.compile(
    r"([A-Z][A-Za-z0-9 ,&'-]{2,120}?(?:"
    r"Media|Technology|Services|Software|Information|Internet|Finance|"
    r"Health|Education|E-commerce|Ecommerce|Consulting|Manufacturing|"
    r"Energy|Retail|Banking|Transportation|Logistics|Real Estate|"
    r"Entertainment|Telecommunications|Telecom|Automotive|Aerospace|"
    r"Pharmaceuticals|Biotech|Food|Travel|Hospitality))(?=\s*$)",
    re.I,
)


def _extract_company_fields(text: str) -> dict[str, str]:
    """Extract the server-rendered company overview fields from page text.

    The live company page renders the tagline/industry/location/followers/
    employee-range as one canonical inline run, and the about text between the
    ``Overview`` heading and the ``Page posts`` marker.  Extraction anchors on
    the followers/employee-range pattern, reads backward for the location (a
    ``City, Region`` pair), then finds the industry run (which ends in a
    recognizable industry suffix) immediately before the location.
    """
    result: dict[str, str] = {}
    followers_match = _FOLLOWERS_RE.search(text)
    if followers_match:
        result["followers"] = truncate_text(followers_match.group(1) + " followers", 60)
        result["employee_range"] = truncate_text(followers_match.group(2), 60)
        prefix = text[: followers_match.start()].rstrip()
        location_match = re.search(r"([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?,\s+[A-Z][A-Za-z .'-]{1,40})\s*$", prefix)
        if location_match:
            location = location_match.group(1).strip()
            if location:
                result["headquarters"] = truncate_text(location, 120)
                before_location = prefix[: location_match.start()].rstrip()
                industry_match = _INDUSTRY_SUFFIX_RE.search(before_location)
                if industry_match:
                    result["industry"] = truncate_text(industry_match.group(1).strip(), 120)
    match = re.search(r"Overview\s+([A-Z][\s\S]{20,800}?)(?:\s+Page posts|\s+Show all details|\s*$)", text)
    if match:
        result["about"] = truncate_text(match.group(1).strip(), 800)
    return result


_POST_BLOCK_RE = re.compile(
    r"(?:feed-shared-update-v2|occludable-update)",
    re.I,
)


def _post_items(html_body: str, *, entity_id: str, max_posts: int, secrets: tuple[str, ...]) -> list[Any]:
    """Parse bounded post items from the raw posts HTML, if present.

    Posts live in the server-rendered DOM only when the layout renders them
    (the live session showed page posts present); a lazy-loaded or client-only
    surface yields no items, never fabricated ones.  Extraction splits the
    redacted body on the update-container elements only (never the right-rail
    ``artdeco-card`` chrome) and binds each item to ``entity_id`` so the
    pipeline does not discard it.
    """
    if not html_body or not _POST_BLOCK_RE.search(html_body):
        return []
    items: list[Any] = []
    blocks = re.split(r"(?=<div[^>]*class=\"[^\"]*(?:feed-shared-update-v2|occludable-update)[^\"]*\")", html_body, flags=re.I)
    for block in blocks[1:]:
        if len(items) >= max_posts:
            break
        text = re.sub(r"<[^>]+>", " ", block)
        text = truncate_text(re.sub(r"\s+", " ", text), 800)
        text = text.strip()
        if len(text) < 40:
            continue
        body = truncate_text(_redact(text, secrets), 800)
        if not body:
            continue
        items.append(
            item(
                LINKEDIN_SOURCE, entity_id, url="", title=truncate_text(body[:80], 80),
                body=body, claim_type="post",
                metadata={"access_state": "private-session", "access_mode": "cookie-session", "is_article": False},
            )
        )
    return items


class LinkedInCookieAdapter:
    """Fetch a LinkedIn company profile with user-supplied session cookies."""

    source = LINKEDIN_SOURCE

    def __init__(self, *, timeout: float = 15.0, fetcher: Callable[..., Any] | None = None,
                 max_posts: int = 5) -> None:
        self.timeout = timeout
        self.fetcher = fetcher
        self.max_posts = max_posts

    @staticmethod
    def read_cookies() -> dict[str, str]:
        """Read the per-run cookie set from the environment (never argv)."""
        cookies: dict[str, str] = {}
        for name in _COOKIE_ENV:
            value = read_secret_env(name)
            if value:
                cookies[name.removeprefix("LINKEDIN_").lower()] = value
        return cookies

    def _url(self, slug: str) -> str:
        if not slug or not re.fullmatch(r"[a-z0-9._-]{1,120}", slug):
            raise UnsafeURL("LinkedIn company slug is not a safe slug")
        return validate_url(
            urllib.parse.urlunsplit(("https", "www.linkedin.com", COMPANY_PATH.format(slug=slug), "", "")),
            ALLOWED_HOSTS,
        )

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        """Build an opener with no env proxy and no redirect following.

        Credentials must never traverse an env-configured proxy, and a
        credentialed request must never follow a redirect (even same-origin).
        """
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)

    def _request(self, url: str, cookies: Mapping[str, str]) -> tuple[int, str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": _USER_AGENT,
            "Cookie": _cookie_header(cookies),
        }
        if self.fetcher is not None:
            try:
                raw = self.fetcher(url, headers, self.timeout)
            except TypeError:
                raw = self.fetcher(url, headers)
            return _response_parts(raw, url)

        opener = self._build_opener()
        validate_resolved_host(urllib.parse.urlsplit(url).hostname or "")
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(request, timeout=self.timeout) as response:
                return int(response.status), _read_bounded(response, self.timeout), str(response.geturl() or url)
        except urllib.error.HTTPError as exc:
            return int(exc.code), _read_bounded(exc, self.timeout), str(exc.geturl() or url)

    def fetch(self, *, entity_id: str, query: str = "", slug: str | None = None,
              cookies: Mapping[str, str] | None = None, **_: Any) -> AdapterResult:
        """Fetch a company profile with the supplied session cookies.

        ``cookies`` may be a mapping passed by the caller; otherwise the
        adapter reads ``LINKEDIN_LI_AT`` / ``LINKEDIN_JSESSIONID`` /
        ``LINKEDIN_BCOOKIE`` from the environment.  ``slug`` may be a
        user-supplied LinkedIn company handle; otherwise the display name is
        slugified as a best-effort fallback.
        """
        credential = dict(cookies) if cookies is not None else self.read_cookies()
        if not credential:
            return AdapterResult([], outcome(self.source, "skipped-unconfigured", detail="LinkedIn session cookies are not configured", fix_hint="Provide LINKEDIN_LI_AT (plus LINKEDIN_JSESSIONID and LINKEDIN_BCOOKIE when available) in memory for this run."), {"entity_id": entity_id, "access_state": "login-required", "access_mode": "none"})
        secrets = tuple(str(value) for value in credential.values() if value)
        slug = slug or _slugify(query)
        try:
            url = self._url(slug)
            status, body, final_url = self._request(url, credential)
            if status in (301, 302, 303, 307, 308) or (final_url and final_url != url):
                # A redirect — even same-origin — is treated as provider drift;
                # no credentialed request follows a second hop.
                return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn redirect rejected"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "cookie-session"})
            if status in (999, 429):
                return AdapterResult([], outcome(self.source, "rate-limited", detail=f"LinkedIn quota or rate limit reached (HTTP {status})"), {"entity_id": entity_id, "access_state": "quota-exhausted", "access_mode": "cookie-session"})
            if status in (401, 403):
                return AdapterResult([], outcome(self.source, "auth-failed", detail=f"LinkedIn authorization rejected (HTTP {status})", fix_hint="Use a fresh LinkedIn session cookie set."), {"entity_id": entity_id, "access_state": "login-required", "access_mode": "cookie-session"})
            if status >= 400:
                return AdapterResult([], outcome(self.source, "unreachable", detail=f"LinkedIn request failed (HTTP {status})"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "cookie-session"})
            safe_body = _redact(body, secrets)
            if any(marker in safe_body.casefold() for marker in _AUTHWALL_MARKERS):
                return AdapterResult([], outcome(self.source, "auth-failed", detail="LinkedIn authwall presented", fix_hint="Use a fresh LinkedIn session cookie set."), {"entity_id": entity_id, "access_state": "login-required", "access_mode": "cookie-session"})
            document = parse_document(safe_body, url)
            text = document.text
            if not text.strip():
                return AdapterResult([], outcome(self.source, "no-results", detail="LinkedIn company page returned no rendered text"), {"entity_id": entity_id, "access_state": "private-session", "access_mode": "cookie-session"})
            name = _redact(document.title or "", secrets)
            name = name.removesuffix(" | LinkedIn").removesuffix("| LinkedIn").strip()
            if not name or name in {"LinkedIn", "Page not found"}:
                return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn company name is missing"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "cookie-session"})
            # Identity verification: a wrong slug can silently resolve to a
            # differently-named company, so compare against the requested
            # entity before emitting evidence.
            if not _name_matches(name, query):
                return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn company name does not match the requested entity", fix_hint="Provide the correct linkedin.com/company/<slug> handle for this entity."), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "cookie-session"})
            fields = _extract_company_fields(text)
            selected = {
                "name": truncate_text(name, 300),
                "description": truncate_text(fields.get("about", ""), 2_000),
                **{key: truncate_text(value, 800) for key, value in fields.items() if key != "about"},
            }
            safe_fields = {key: _redact(value, secrets) if isinstance(value, str) else value for key, value in selected.items()}
            profile_body = "\n".join(f"{key}: {truncate_text(value, 800)}" for key, value in safe_fields.items())
            evidence = item(self.source, entity_id, url=url, title=safe_fields["name"], body=profile_body,
                            claim_type="company-profile",
                            metadata={"access_state": "private-session", "access_mode": "cookie-session", "linkedin_fields": list(selected)})
            posts = _post_items(safe_body, entity_id=entity_id, max_posts=self.max_posts, secrets=secrets)
            return AdapterResult([evidence, *posts], outcome(self.source, "ok", items=1 + len(posts)),
                                 {"entity_id": entity_id, "access_state": "private-session", "access_mode": "cookie-session", "posts_returned": len(posts)})
        except UnsafeURL as exc:
            return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn endpoint rejected"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "none"})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            state = "timeout" if isinstance(getattr(exc, "reason", exc), TimeoutError) else "unreachable"
            return AdapterResult([], outcome(self.source, state, detail="LinkedIn request failed"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "cookie-session"})
        except Exception:
            # Never propagate provider text: response bodies may echo secrets.
            return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn response shape was not supported"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "cookie-session"})


_MAX_BODY = 2_000_001


def _read_bounded(handle: Any, timeout: float) -> str:
    """Read a response body capped in size and total wall-time.

    A slow-drip server must not hold a pipeline worker past ``timeout``: the
    per-socket timeout only bounds each individual ``recv``, so a trickling
    peer could otherwise extend the read indefinitely.
    """
    import time

    started = time.monotonic()
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() - started > timeout:
            break
        chunk = handle.read(65_536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= _MAX_BODY:
            break
    return b"".join(chunks)[:_MAX_BODY].decode("utf-8", "replace")


def _response_parts(raw: Any, fallback_url: str) -> tuple[int, str, str]:
    if isinstance(raw, tuple):
        if len(raw) >= 3:
            return int(raw[0]), str(raw[1]), str(raw[2] or fallback_url)
        return int(raw[0]), str(raw[1]), fallback_url
    if isinstance(raw, Mapping):
        return int(raw.get("status", 200)), str(raw.get("body", raw)), str(raw.get("url", fallback_url))
    return int(getattr(raw, "status", 200)), str(getattr(raw, "text", getattr(raw, "body", ""))), str(getattr(raw, "url", fallback_url))


def _name_matches(page_name: str, query: str) -> bool:
    """Whether the extracted page name plausibly matches the requested entity.

    Both sides are normalized with the identity legal-suffix stripper so
    ``Flipkart Pvt Ltd`` matches ``Flipkart Internet Pvt Ltd``.  A single-token
    query must be an exact (normalized) match to avoid a prefix false positive
    (``Infosys`` must not match ``Infosys Technologies``); multi-token queries
    use token-run containment in either direction.
    """
    from .startup_identity import normalize_name

    if not query:
        # No display name to verify against; accept the page on name presence.
        return True
    page = normalize_name(page_name)
    wanted = normalize_name(query)
    if not page or not wanted:
        return True
    page_tokens = page.split()
    wanted_tokens = wanted.split()
    if len(wanted_tokens) < 2 or len(page_tokens) < 2:
        return page == wanted
    return _token_run(wanted_tokens, page_tokens) or _token_run(page_tokens, wanted_tokens)


def _token_run(needle: list[str], haystack: list[str]) -> bool:
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


__all__ = ["ALLOWED_HOSTS", "COMPANY_PATH", "LinkedInCookieAdapter"]
