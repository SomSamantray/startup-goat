"""Explicit bearer-token LinkedIn adapter.

This adapter intentionally does not use browser Voyager requests or
ScrapeCreators.  Credentials exist only for the duration of one call.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from .env import read_secret_env
from .schema import SourceOutcome
from .startup_public_base import AdapterResult, failed, item, outcome
from .startup_web import UnsafeURL, truncate_text

LINKEDIN_SOURCE = "linkedin"
ALLOWED_HOSTS = ("api.linkedin.com", "linkedin.com")
DEFAULT_ENDPOINT = "https://api.linkedin.com/v2/organizations/{entity_id}"
_SECRET = re.compile(r"(?:bearer\s+)?[A-Za-z0-9._~+/=-]{12,}")


def _redact(value: Any, secret: str | None = None) -> str:
    text = str(value or "")
    if secret:
        text = text.replace(secret, "<redacted>")
    return re.sub(r"(?i)(authorization\s*[:=]\s*)([^,;\s]+)", r"\1<redacted>", text)


def _response_parts(raw: Any, fallback_url: str) -> tuple[int, str, str]:
    if isinstance(raw, tuple):
        if len(raw) >= 3:
            return int(raw[0]), str(raw[1]), str(raw[2] or fallback_url)
        return int(raw[0]), str(raw[1]), fallback_url
    if isinstance(raw, Mapping):
        return int(raw.get("status", 200)), json.dumps(raw.get("body", raw)), str(raw.get("url", fallback_url))
    return int(getattr(raw, "status", 200)), str(getattr(raw, "text", getattr(raw, "body", ""))), str(getattr(raw, "url", fallback_url))


class LinkedInTokenAdapter:
    source = LINKEDIN_SOURCE

    def __init__(self, *, endpoint: str | None = None, timeout: float = 15.0,
                 fetcher: Callable[..., Any] | None = None) -> None:
        self.endpoint = endpoint or read_secret_env("LINKEDIN_API_ENDPOINT", DEFAULT_ENDPOINT) or DEFAULT_ENDPOINT
        self.timeout = timeout
        self.fetcher = fetcher

    def _url(self, entity_id: str, endpoint: str | None = None) -> str:
        template = endpoint or self.endpoint
        if not isinstance(template, str) or "?" in template:
            raise UnsafeURL("LinkedIn endpoint must not contain a query string")
        url = template.format(entity_id=urllib.parse.quote(str(entity_id), safe=""))
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS and not (parsed.hostname or "").endswith(".linkedin.com"):
            raise UnsafeURL("LinkedIn endpoint host is not allowlisted")
        try:
            port = parsed.port
        except ValueError as exc:
            raise UnsafeURL("LinkedIn endpoint port is invalid") from exc
        if port not in (None, 443):
            raise UnsafeURL("LinkedIn endpoint port is not allowlisted")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise UnsafeURL("LinkedIn endpoint contains unsafe URL material")
        return urllib.parse.urlunsplit(("https", parsed.hostname.casefold(), parsed.path or "/", "", ""))

    def _request(self, url: str, token: str) -> tuple[int, str, str]:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if self.fetcher is not None:
            try:
                raw = self.fetcher(url, headers, self.timeout)
            except TypeError:
                raw = self.fetcher(url, headers)
            return _response_parts(raw, url)
        request = urllib.request.Request(url, headers=headers, method="GET")
        # urllib's default redirect handler is deliberately disabled: a token
        # must never be sent to a different origin.
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=self.timeout) as response:
                return int(response.status), response.read(2_000_001).decode("utf-8", "replace"), str(response.geturl() or url)
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read(2_000_001).decode("utf-8", "replace"), str(exc.geturl() or url)

    def fetch(self, *, entity_id: str, query: str = "", token: str | None = None,
              endpoint: str | None = None, **_: Any) -> AdapterResult:
        credential = token if token is not None else read_secret_env("LINKEDIN_ACCESS_TOKEN")
        if not credential or not str(credential).strip():
            return AdapterResult([], outcome(self.source, "skipped-unconfigured", detail="LinkedIn bearer token is not configured", fix_hint="Provide a supported LINKEDIN_ACCESS_TOKEN in memory for this run."), {"entity_id": entity_id, "access_state": "login-required", "access_mode": "none"})
        credential = str(credential)
        try:
            url = self._url(entity_id, endpoint)
            status, body, final_url = self._request(url, credential)
            if final_url != url:
                # Even a same-origin redirect is treated as provider drift; no
                # redirect response may cause a second credentialed request.
                return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn redirect rejected"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "bearer-token"})
            if status in {401, 403}:
                state = "login-required" if status == 401 else "unknown"
                return AdapterResult([], outcome(self.source, "auth-failed", detail=f"LinkedIn authorization rejected (HTTP {status})", fix_hint="Use a supported token with organization read permissions."), {"entity_id": entity_id, "access_state": state, "access_mode": "bearer-token"})
            if status == 429 or status == 402:
                return AdapterResult([], outcome(self.source, "rate-limited", detail="LinkedIn quota or rate limit reached"), {"entity_id": entity_id, "access_state": "quota-exhausted", "access_mode": "bearer-token"})
            if status >= 400:
                return AdapterResult([], outcome(self.source, "unreachable", detail=f"LinkedIn request failed (HTTP {status})"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "bearer-token"})
            try:
                payload = json.loads(body)
            except (TypeError, ValueError) as exc:
                return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn returned non-JSON data"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "bearer-token"})
            if not isinstance(payload, Mapping):
                raise ValueError("response root is not an object")
            name = payload.get("name") or payload.get("localizedName") or payload.get("vanityName")
            if isinstance(name, Mapping):
                name = next((value for value in name.values() if isinstance(value, str)), None)
            if not isinstance(name, str) or not name.strip():
                raise ValueError("required organization name is missing")
            description = payload.get("description") or payload.get("tagline") or ""
            if not isinstance(description, str):
                description = ""
            # Provider text is untrusted and may echo an Authorization value.
            name = _redact(name, credential)
            description = _redact(description, credential)
            selected = {"name": truncate_text(name, 300), "description": truncate_text(description, 2_000)}
            for key in ("industry", "locations", "staffCount", "followerCount", "websiteUrl"):
                value = payload.get(key)
                if value is not None and isinstance(value, (str, int, float, bool, list, dict)):
                    selected[key] = _redact(value, credential) if isinstance(value, str) else value
            safe_body = "\n".join(f"{key}: {truncate_text(value, 800)}" for key, value in selected.items())
            evidence = item(self.source, entity_id, url=url, title=selected["name"], body=safe_body, claim_type="company-profile", metadata={"access_state": "private-session", "access_mode": "bearer-token", "linkedin_fields": list(selected)})
            return AdapterResult([evidence], outcome(self.source, "ok", items=1), {"entity_id": entity_id, "access_state": "private-session", "access_mode": "bearer-token"})
        except UnsafeURL as exc:
            return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn endpoint rejected"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "none"})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return AdapterResult([], outcome(self.source, "unreachable", detail="LinkedIn request failed"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "bearer-token"})
        except Exception as exc:
            # Do not propagate provider text: response bodies may echo the token.
            return AdapterResult([], outcome(self.source, "schema-drift", detail="LinkedIn response shape was not supported"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "bearer-token"})


__all__ = ["ALLOWED_HOSTS", "DEFAULT_ENDPOINT", "LinkedInTokenAdapter"]
