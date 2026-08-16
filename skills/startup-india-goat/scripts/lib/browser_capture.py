"""Strict, non-persistent browser capture envelopes.

The host integration, not this package, is responsible for selecting visible
page values.  This module accepts a small JSON-compatible projection only; it
never accepts a browser session, request material, or raw page content.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from .startup_schema import STARTUP_SCHEMA_VERSION

BROWSER_CAPTURE_VERSION = "1.0"
ACCESS_STATES = frozenset({
    "public", "private-session", "login-required", "paywalled", "captcha",
    "quota-exhausted", "browser-unavailable", "not-applicable", "unknown",
})
DEFAULT_DOMAINS = {"linkedin.com", "www.linkedin.com", "api.linkedin.com", "tracxn.com", "platform.tracxn.com"}
_TOP_LEVEL = frozenset({
    "schema_version", "source", "entity_id", "page_url", "page_title",
    "visible_fields", "visible_rows", "public_links", "access_state",
    "captured_at", "ttl_seconds", "session_classification",
})
_SECRET_KEY = re.compile(r"(?:token|secret|password|passwd|cookie|csrf|authorization|bearer|api[_-]?key|credential|session|storage|header|body|html|script|jwt|private[_-]?key)", re.I)
_HIDDEN_KEY = re.compile(r"(?:^|[_-])(hidden|input|internal|private|raw|dom|html|script|cookie|storage|header|request|response_body)(?:$|[_-])", re.I)
_JWT = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")


class BrowserCaptureError(ValueError):
    """Raised when a host-provided capture is unsafe or unusable."""


def _secret_like(value: Any, *, key: str = "") -> bool:
    if key and (_SECRET_KEY.search(key) or _HIDDEN_KEY.search(key)):
        return True
    if isinstance(value, str):
        text = value.strip()
        if _JWT.fullmatch(text):
            return True
        if re.search(r"<\s*(?:script|html|input|form|body|iframe)\b|<!doctype", text, re.I):
            return True
        if re.search(r"(?:bearer\s+|-----begin|eyJ[A-Za-z0-9_-]{8,}\.)", text, re.I):
            return True
        # Never accept a long opaque credential-like value in a visible field.
        if len(text) >= 80 and not re.search(r"\s", text):
            return True
    return False


def _validate_value(value: Any, *, path: str = "visible") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if not key_text or _HIDDEN_KEY.search(key_text) or _SECRET_KEY.search(key_text):
                raise BrowserCaptureError(f"secret or hidden field rejected at {path}.{key_text}")
            _validate_value(child, path=f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_value(child, path=f"{path}[{index}]")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise BrowserCaptureError(f"unsupported value at {path}")
    if _secret_like(value):
        raise BrowserCaptureError(f"secret-like value rejected at {path}")


def _iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BrowserCaptureError("captured_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrowserCaptureError("invalid captured_at") from exc
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _host_allowed(url: str, domains: Iterable[str]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise BrowserCaptureError("browser URLs must be credential-free HTTPS URLs")
    host = parsed.hostname.casefold().rstrip(".")
    allowed = {str(item).casefold().lstrip(".").rstrip(".") for item in domains}
    if not any(host == item or host.endswith("." + item) for item in allowed):
        raise BrowserCaptureError(f"browser URL host is not allowlisted: {host}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise BrowserCaptureError("browser URL port is invalid") from exc
    if port not in (None, 443):
        raise BrowserCaptureError("browser URL port is not allowlisted")
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise BrowserCaptureError("private browser URL rejected")
    except ValueError:
        pass
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _public_link(value: Any, domains: Iterable[str]) -> str:
    if not isinstance(value, str):
        raise BrowserCaptureError("public links must be strings")
    return _host_allowed(value, domains)


@dataclass(frozen=True)
class BrowserCaptureEnvelope:
    schema_version: str
    source: str
    entity_id: str
    page_url: str
    page_title: str
    visible_fields: Mapping[str, Any] = field(default_factory=dict)
    visible_rows: tuple[Mapping[str, Any], ...] = ()
    public_links: tuple[str, ...] = ()
    access_state: str = "private-session"
    captured_at: str = ""
    ttl_seconds: int = 900
    session_classification: str = "private-session"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, expected_source: str | None = None,
                  expected_entity_id: str | None = None, allowed_domains: Iterable[str] = DEFAULT_DOMAINS,
                  now: datetime | None = None) -> "BrowserCaptureEnvelope":
        if not isinstance(payload, Mapping):
            raise BrowserCaptureError("browser capture must be an object")
        unknown = set(payload) - _TOP_LEVEL
        if unknown:
            raise BrowserCaptureError(f"unknown browser capture field(s): {', '.join(sorted(map(str, unknown)))}")
        required = {"schema_version", "source", "entity_id", "page_url", "captured_at", "ttl_seconds"}
        missing = required - set(payload)
        if missing:
            raise BrowserCaptureError(f"missing browser capture field(s): {', '.join(sorted(missing))}")
        source = str(payload["source"]).strip().casefold()
        entity_id = str(payload["entity_id"]).strip()
        if not source or not entity_id:
            raise BrowserCaptureError("source and entity_id are required")
        if expected_source and source != expected_source.casefold():
            raise BrowserCaptureError("browser capture source mismatch")
        if expected_entity_id and entity_id != expected_entity_id:
            raise BrowserCaptureError("browser capture entity mismatch")
        if str(payload["schema_version"]) != BROWSER_CAPTURE_VERSION:
            raise BrowserCaptureError("unsupported browser capture schema")
        access = str(payload.get("access_state", "private-session"))
        if access not in ACCESS_STATES:
            raise BrowserCaptureError("unknown browser access state")
        classification = str(payload.get("session_classification", "private-session"))
        if classification != "private-session":
            raise BrowserCaptureError("browser captures must be classified private-session")
        try:
            ttl = int(payload["ttl_seconds"])
        except (TypeError, ValueError) as exc:
            raise BrowserCaptureError("ttl_seconds must be an integer") from exc
        if ttl <= 0 or ttl > 86_400:
            raise BrowserCaptureError("ttl_seconds outside safe bounds")
        captured = _iso(payload["captured_at"])
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if (reference - captured).total_seconds() > ttl:
            raise BrowserCaptureError("browser capture envelope has expired")
        page_url = _host_allowed(str(payload["page_url"]), allowed_domains)
        title = payload.get("page_title", "")
        if not isinstance(title, str) or _secret_like(title):
            raise BrowserCaptureError("invalid page_title")
        fields_value = payload.get("visible_fields", {})
        rows_value = payload.get("visible_rows", ())
        if not isinstance(fields_value, Mapping) or not isinstance(rows_value, (list, tuple)):
            raise BrowserCaptureError("visible fields/rows have invalid shape")
        _validate_value(fields_value, path="visible_fields")
        rows: list[Mapping[str, Any]] = []
        for row in rows_value:
            if not isinstance(row, Mapping):
                raise BrowserCaptureError("visible_rows must contain objects")
            _validate_value(row, path="visible_rows")
            rows.append(dict(row))
        links = tuple(_public_link(link, allowed_domains) for link in payload.get("public_links", ()))
        if len(set(links)) != len(links):
            raise BrowserCaptureError("duplicate public link")
        return cls(BROWSER_CAPTURE_VERSION, source, entity_id, page_url, title,
                   dict(fields_value), tuple(rows), links, access, captured.isoformat(), ttl, classification)

    @classmethod
    def validate(cls, payload: Mapping[str, Any], **kwargs: Any) -> "BrowserCaptureEnvelope":
        return cls.from_dict(payload, **kwargs)

    @property
    def fresh(self) -> bool:
        try:
            return (datetime.now(timezone.utc) - _iso(self.captured_at)).total_seconds() <= self.ttl_seconds
        except BrowserCaptureError:
            return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the selected projection only; no raw envelope is retained."""
        return {
            "schema_version": self.schema_version, "source": self.source, "entity_id": self.entity_id,
            "page_url": self.page_url, "page_title": self.page_title,
            "visible_fields": json.loads(json.dumps(self.visible_fields)),
            "visible_rows": json.loads(json.dumps(list(self.visible_rows))),
            "public_links": list(self.public_links), "access_state": self.access_state,
            "captured_at": self.captured_at, "ttl_seconds": self.ttl_seconds,
            "session_classification": self.session_classification,
        }

    def __repr__(self) -> str:
        return f"BrowserCaptureEnvelope(source={self.source!r}, entity_id={self.entity_id!r}, page_url={self.page_url!r}, access_state={self.access_state!r})"


def parse_browser_capture(payload: Mapping[str, Any], **kwargs: Any) -> BrowserCaptureEnvelope:
    return BrowserCaptureEnvelope.from_dict(payload, **kwargs)


__all__ = ["ACCESS_STATES", "BROWSER_CAPTURE_VERSION", "BrowserCaptureEnvelope", "BrowserCaptureError", "parse_browser_capture"]
