"""Versioned, secret-free JSON export for Startup India GOAT runs."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .startup_schema import GroupProfile, StartupProfile, to_dict
from .startup_sources import resolve_source

JSON_SCHEMA_VERSION = "startup-india-goat-json/1.0"
_SECRET_KEY = re.compile(r"(?:token|secret|password|cookie|authorization|api[_-]?key|access[_-]?token|credential|header)", re.I)
_SECRET_VALUE = re.compile(r"(?:bearer\s+|gh[pousr]_|xox[baprs]-|sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]{20,})", re.I)


def _safe(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _safe(v, key=str(k)) for k, v in value.items() if not _SECRET_KEY.search(str(k))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe(item, key=key) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return "[REDACTED]"
    return value


def _profile(profile: StartupProfile, *, public_only: bool = True) -> dict[str, Any]:
    value = to_dict(profile)
    if public_only:
        refs = []
        for ref in value.get("evidence", []):
            source = str(ref.get("source", "")) if isinstance(ref, Mapping) else ""
            try:
                if not resolve_source(source).public:
                    continue
            except KeyError:
                # Unknown source access is not safe to publish.
                continue
            refs.append(ref)
        value["evidence"] = refs
        allowed_ids = {ref.get("evidence_id") for ref in refs if isinstance(ref, Mapping)}
        value["facts"] = [fact for fact in value.get("facts", []) if not fact.get("evidence_refs") or any((item if isinstance(item, str) else item.get("evidence_id")) in allowed_ids for item in fact.get("evidence_refs", []))]
    # Evidence references are intentionally retained; raw source bodies/items
    # never enter the agent-facing export.
    return _safe(value)


def _observed_access_state(source: str, state: str) -> str:
    if state in {"ok", "no-results"}:
        try:
            return "public" if resolve_source(source).public else "private-session"
        except KeyError:
            return "unknown"
    return {
        "auth-failed": "auth-failed", "skipped-unconfigured": "gated",
        "rate-limited": "rate-limited", "timeout": "timeout",
        "unreachable": "unreachable", "schema-drift": "schema-drift",
        "partial": "partial", "error": "unknown",
    }.get(state, "unknown")


def export_payload(value: Any, *, artifact_paths: Mapping[str, str] | None = None,
                   coverage: Mapping[str, Any] | None = None,
                   request: Mapping[str, Any] | None = None,
                   status: str = "complete", public_only: bool = True) -> dict[str, Any]:
    """Build the stable wire object from a profile, group, or StartupRun."""
    run = value if hasattr(value, "profiles") and hasattr(value, "request") else None
    profiles = list(getattr(value, "profiles", [])) if run else ([value] if isinstance(value, StartupProfile) else list(getattr(value, "profiles", [])))
    if isinstance(value, GroupProfile):
        profiles = list(value.profiles)
    if run:
        request_obj = getattr(run, "request", None)
        request = request or _safe({
            "raw_query": getattr(request_obj, "raw_query", ""),
            "sources": list(getattr(request_obj, "sources", ())),
            "dimensions": list(getattr(request_obj, "dimensions", ())),
            "audience": getattr(request_obj, "audience", None),
            "depth": getattr(request_obj, "depth", "standard"),
            "horizon_months": getattr(request_obj, "horizon_months", 24),
            "public_only": getattr(request_obj, "public_only", True),
            "consent": bool(getattr(request_obj, "consent", False)),
        })
        retrieval = getattr(run, "retrieval", None)
        if coverage is None:
            entity_coverage = {}
            for result in getattr(retrieval, "entities", ()):
                outcomes = {}
                for source, observed in result.outcomes.items():
                    entry = dict(to_dict(observed))
                    entry["access_state"] = _observed_access_state(source, str(entry.get("state", "unknown")))
                    outcomes[source] = entry
                entity_coverage[result.identity.entity_id] = {"outcomes": outcomes, "errors": list(result.errors)}
            coverage = {
                "requested_sources": list(getattr(retrieval, "requested_sources", ())),
                "warnings": list(getattr(retrieval, "warnings", ())),
                "entities": entity_coverage,
            }
    payload = {
        "schema_version": JSON_SCHEMA_VERSION,
        "contract": {"name": "Startup India GOAT agent export", "version": JSON_SCHEMA_VERSION},
        "status": status,
        "request": _safe(request or {}),
        "profiles": [_profile(profile, public_only=public_only) for profile in profiles if isinstance(profile, StartupProfile)],
        "coverage": _safe(coverage or {}),
        "artifacts": _safe(dict(artifact_paths or {})),
    }
    return _safe(payload)


def export_json(value: Any, **kwargs: Any) -> str:
    return json.dumps(export_payload(value, **kwargs), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_startup_json(value: Any, **kwargs: Any) -> str:
    return export_json(value, **kwargs)

__all__ = ["JSON_SCHEMA_VERSION", "export_json", "export_payload", "export_startup_json"]
