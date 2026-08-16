"""Tracxn adapter for validated browser projections or supported responses.

No cookie, browser header, SPA request, or request body is accepted here.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .browser_capture import BrowserCaptureEnvelope, BrowserCaptureError
from .schema import SourceOutcome
from .startup_public_base import AdapterResult, item, outcome
from .startup_web import truncate_text, validate_url

TRACXN_SOURCE = "tracxn"


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): "<redacted>" if any(marker in str(key).casefold() for marker in ("token", "secret", "cookie", "authorization", "password")) else _safe_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_safe_value(child) for child in value]
    if isinstance(value, str):
        if value.count(".") == 2 and len(value) > 24:
            return "<redacted>"
        return value
    return value


def _state_outcome(access_state: str, items: int = 0) -> SourceOutcome:
    if access_state == "quota-exhausted":
        return outcome(TRACXN_SOURCE, "rate-limited", items=items, detail="Tracxn quota or upgrade limit reached")
    if access_state in {"login-required", "captcha"}:
        return outcome(TRACXN_SOURCE, "auth-failed", items=items, detail="Tracxn authorized session is unavailable")
    if access_state in {"paywalled", "unknown"}:
        return outcome(TRACXN_SOURCE, "partial", items=items, detail="Tracxn access is limited")
    return outcome(TRACXN_SOURCE, "ok" if items else "no-results", items=items)


class TracxnAdapter:
    source = TRACXN_SOURCE

    def __init__(self, *, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def _from_token_response(self, entity_id: str, response: Any) -> AdapterResult:
        if not isinstance(response, Mapping):
            return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn token response is not an object"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "token-response"})
        status = int(response.get("status", 200)) if str(response.get("status", "200")).isdigit() else 200
        if status in {401, 403}:
            return AdapterResult([], outcome(self.source, "auth-failed", detail="Tracxn permission denied"), {"entity_id": entity_id, "access_state": "login-required", "access_mode": "token-response"})
        if status in {402, 429} or response.get("quota_exhausted") or response.get("upgrade_required"):
            return AdapterResult([], _state_outcome("quota-exhausted"), {"entity_id": entity_id, "access_state": "quota-exhausted", "access_mode": "token-response"})
        payload = response.get("data", response)
        if not isinstance(payload, Mapping):
            return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn response shape is unsupported"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "token-response"})
        name = payload.get("name") or payload.get("company_name")
        if not isinstance(name, str) or not name.strip():
            return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn company name is missing"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "token-response"})
        selected = {key: payload[key] for key in ("name", "description", "stage", "location", "founded_year", "funding_rounds", "employee_count", "investors", "revenue", "market_cap") if key in payload}
        selected = {key: _safe_value(value) for key, value in selected.items()}
        body = "\n".join(f"{key}: {truncate_text(value, 800)}" for key, value in selected.items())
        try:
            url = validate_url(str(payload.get("url") or "https://platform.tracxn.com/"), {"tracxn.com", "platform.tracxn.com"})
        except Exception:
            return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn response URL was rejected"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "token-response"})
        evidence = item(self.source, entity_id, url=url, title=str(selected["name"]), body=body, claim_type="company-profile", metadata={"access_state": "private-session", "access_mode": "token-response", "tracxn_fields": list(selected)})
        return AdapterResult([evidence], _state_outcome("private-session", 1), {"entity_id": entity_id, "access_state": "private-session", "access_mode": "token-response"})

    def fetch(self, *, entity_id: str, query: str = "", browser_envelope: BrowserCaptureEnvelope | Mapping[str, Any] | None = None,
              envelope: BrowserCaptureEnvelope | Mapping[str, Any] | None = None,
              token_response: Mapping[str, Any] | None = None, **_: Any) -> AdapterResult:
        if token_response is not None:
            return self._from_token_response(entity_id, token_response)
        candidate = browser_envelope if browser_envelope is not None else envelope
        if candidate is None:
            return AdapterResult([], outcome(self.source, "skipped-unconfigured", detail="Tracxn requires an approved browser capture or supported response", fix_hint="Approve a sanitized Tracxn browser capture or provide a supported response."), {"entity_id": entity_id, "access_state": "browser-unavailable", "access_mode": "none"})
        try:
            capture = candidate if isinstance(candidate, BrowserCaptureEnvelope) else BrowserCaptureEnvelope.from_dict(candidate, expected_source=self.source, expected_entity_id=entity_id, allowed_domains={"tracxn.com", "platform.tracxn.com"})
            if capture.source != self.source or capture.entity_id != entity_id:
                raise BrowserCaptureError("Tracxn envelope identity mismatch")
            access = capture.access_state
            if access in {"quota-exhausted", "login-required", "captcha", "paywalled"}:
                return AdapterResult([], _state_outcome(access), {"entity_id": entity_id, "access_state": access, "access_mode": "browser-envelope"})
            selected = dict(capture.visible_fields)
            if not selected and not capture.visible_rows:
                return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn envelope contains no visible structured fields"), {"entity_id": entity_id, "access_state": access, "access_mode": "browser-envelope"})
            title = str(selected.get("name") or selected.get("company_name") or capture.page_title or entity_id)
            body_parts = [f"{key}: {truncate_text(value, 1_000)}" for key, value in selected.items()]
            if capture.visible_rows:
                body_parts.append("rows: " + truncate_text(json.dumps(list(capture.visible_rows), ensure_ascii=False), 4_000))
            evidence = item(self.source, entity_id, url=capture.page_url, title=title, body="\n".join(body_parts), claim_type="company-profile", metadata={"access_state": access, "access_mode": "browser-envelope", "capture_time": capture.captured_at, "tracxn_fields": list(selected), "public_links": list(capture.public_links)})
            return AdapterResult([evidence], _state_outcome(access, 1), {"entity_id": entity_id, "access_state": access, "access_mode": "browser-envelope"})
        except BrowserCaptureError:
            return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn browser capture was rejected"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "none"})
        except Exception:
            return AdapterResult([], outcome(self.source, "schema-drift", detail="Tracxn browser capture shape was unsupported"), {"entity_id": entity_id, "access_state": "unknown", "access_mode": "none"})


__all__ = ["TRACXN_SOURCE", "TracxnAdapter"]
