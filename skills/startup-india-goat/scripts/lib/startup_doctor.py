"""Safe source diagnostics and actionable coverage guidance."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .startup_sources import SourceCapability, source_registry

def _configured(capability: SourceCapability, context: Mapping[str, Any]) -> bool:
    # Context values are booleans or opaque caller signals; never print them.
    return capability.is_capable(context)


def diagnose_sources(*, context: Mapping[str, Any] | None = None, public_only: bool = True,
                     outcomes: Mapping[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    outcomes = outcomes or {}
    sources: list[dict[str, Any]] = []
    for capability in source_registry():
        observed = outcomes.get(capability.canonical_name)
        observed_state = getattr(observed, "state", None) or (observed.get("state") if isinstance(observed, Mapping) else None)
        if observed_state in {"auth-failed", "login-required"}:
            status = "auth-failed"
        elif observed_state in {"quota-exhausted", "quota"}:
            status = "quota"
        elif observed_state in {"schema-drift", "schema-error"}:
            status = "schema-drift"
        elif observed_state in {"browser-unavailable", "browser_unavailable"}:
            status = "browser-unavailable"
        elif observed_state in {"skipped-unconfigured", "unconfigured"}:
            status = "unavailable"
        elif observed_state in {"error", "timeout", "partial"}:
            status = "failed"
        elif capability.gated and public_only:
            status = "gated"
        elif capability.gated:
            status = "configured" if _configured(capability, context) else "auth-failed"
        elif not _configured(capability, context):
            status = "unavailable"
        else:
            status = "available"
        guidance = []
        if status == "gated": guidance.append("Ask for explicit consent and an approved credential or browser capture.")
        elif status == "auth-failed": guidance.append("Verify the approved credential or sign in through the host; do not paste secrets into reports.")
        elif status == "quota": guidance.append("Wait for quota reset or use another source; do not retry aggressively.")
        elif status == "schema-drift": guidance.append("Capture a sanitized fixture and update the adapter contract before retrying.")
        elif status == "browser-unavailable": guidance.append("Use public HTTP retrieval or an approved browser capture; do not pass cookies or raw browser state.")
        elif status in {"failed", "unavailable"}: guidance.append("Check the source availability and add a permitted public alternative.")
        sources.append({"source": capability.canonical_name, "aliases": list(capability.aliases), "class": capability.source_class, "status": status, "guidance": guidance})
    available = [entry["source"] for entry in sources if entry["status"] == "available"]
    limited = [entry["source"] for entry in sources if entry["status"] != "available"]
    return {"schema_version": "startup-india-goat-doctor/1.0", "public_only": public_only, "sources": sources, "available_sources": available, "limited_sources": limited, "secret_values_inspected": False}


def coverage_guidance(report_or_doctor: Mapping[str, Any], *, public_only: bool = True) -> list[str]:
    """Explain how to improve coverage without implying unavailable == empty."""
    guidance: list[str] = []
    sources = report_or_doctor.get("sources", []) if isinstance(report_or_doctor, Mapping) else []
    for entry in sources:
        status = entry.get("status")
        name = entry.get("source", "source")
        if status == "gated" and public_only:
            guidance.append(f"{name}: unavailable in public-only mode; request consent before using an approved authenticated route.")
        elif status in {"unavailable", "failed"}:
            guidance.append(f"{name}: coverage is unavailable, not a no-results finding; try a permitted alternative or retry later.")
        elif status == "schema-drift":
            guidance.append(f"{name}: adapter schema needs review before it can contribute evidence.")
        elif status == "browser-unavailable":
            guidance.append(f"{name}: browser access is unavailable; use public HTTP or an approved capture instead.")
        elif status == "quota":
            guidance.append(f"{name}: quota is exhausted; wait or switch sources rather than retrying repeatedly.")
    if not guidance:
        guidance.append("Coverage is available for the configured source set; add an authoritative filing or registry source for stronger claims.")
    return guidance


def render_doctor(report: Mapping[str, Any]) -> str:
    lines = ["Startup India GOAT source doctor", ""]
    for entry in report.get("sources", []):
        lines.append(f"- {entry.get('source')}: {entry.get('status')}")
        lines.extend(f"  - {item}" for item in entry.get("guidance", []))
    lines.append("")
    lines.extend(f"- Coverage guidance: {item}" for item in coverage_guidance(report, public_only=bool(report.get("public_only", True))))
    return "\n".join(lines) + "\n"


def doctor_json(**kwargs: Any) -> str:
    return json.dumps(diagnose_sources(**kwargs), indent=2, sort_keys=True) + "\n"

__all__ = ["coverage_guidance", "diagnose_sources", "doctor_json", "render_doctor"]
