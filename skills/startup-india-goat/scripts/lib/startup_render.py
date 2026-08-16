"""Canonical decision-first Markdown reports for Startup India GOAT."""
from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from .schema import SourceOutcome
from .startup_evidence import EvidenceRecord
from .startup_schema import EvidenceReference, GroupProfile, StartupFact, StartupProfile

_DIMENSIONS = (
    "product", "market", "traction", "capital", "team", "distribution",
    "defensibility", "business_model", "indian_ecosystem_relevance",
    "evidence_quality", "risks",
)
_RUBRIC_FIELDS = {
    "product": {"product"},
    "market": {"market", "industry", "headquarters"},
    "traction": {"revenue", "employees", "funding_rounds", "stage"},
    "capital": {"funding", "funding_rounds", "investors", "revenue"},
    "team": {"founders", "employees"},
    "distribution": {"market", "business_model", "customers"},
    "defensibility": {"product", "market", "patents", "trademarks"},
    "business_model": {"business_model", "revenue"},
    "indian_ecosystem_relevance": {"dpiit_recognized", "dpiit_id", "industry", "stage"},
    "evidence_quality": set(),
    "risks": set(),
}
_SAFE_URL = re.compile(r"^https://[^\s<>\"']+$", re.I)


def _text(value: object) -> str:
    # Markdown metacharacters are escaped so hostile source text remains text.
    return str(value if value is not None else "").replace("\\", "\\\\").replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]")


def safe_link(label: object, url: object) -> str:
    value = str(url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password or not _SAFE_URL.fullmatch(value):
        return _text(label)
    return f"[{_text(label)}]({value})"


def _source_outcomes(source_outcomes: Mapping[str, SourceOutcome] | None) -> Mapping[str, SourceOutcome]:
    return source_outcomes or {}


def _refs(fact: StartupFact, refs: Mapping[str, EvidenceReference]) -> str:
    links = []
    for ref in fact.evidence_refs:
        evidence_id = ref if isinstance(ref, str) else ref.evidence_id
        resolved = refs.get(evidence_id, ref if isinstance(ref, EvidenceReference) else None)
        url = getattr(resolved, "url", None)
        source = getattr(resolved, "source", None) or "evidence"
        label = f"{source}:{evidence_id[:10]}"
        links.append(safe_link(label, url) if url else f"[{_text(label)}]")
    return ", ".join(links) or "[citation unavailable]"


def _fact_line(fact: StartupFact, refs: Mapping[str, EvidenceReference]) -> str:
    date_note = ""
    if not fact.is_evergreen:
        date_note = f" (as of {fact.as_of_date or fact.published_at or 'date unknown'})"
    authority = f"; authority: {fact.source_authority}" if fact.source_authority else ""
    confidence = f"; confidence: {fact.confidence}"
    return f"- **{_text(fact.field)}:** {_text(fact.value)}{date_note} ({_refs(fact, refs)}{authority}{confidence})"


def _facts(profile: StartupProfile, refs: Mapping[str, EvidenceReference]) -> list[StartupFact]:
    return [fact for fact in profile.facts if fact.entity_id == profile.identity.entity_id]


def _dimensions(profile: StartupProfile, requested: Iterable[str] | None) -> list[str]:
    values = list(requested if requested is not None else profile.dimensions)
    return [value for value in values if value in _DIMENSIONS] or list(_DIMENSIONS)


def _rubric(profile: StartupProfile, facts: list[StartupFact], dimensions: list[str]) -> list[str]:
    lines = []
    by_field = defaultdict(list)
    for fact in facts: by_field[fact.field].append(fact)
    for dimension in dimensions:
        if dimension == "evidence_quality":
            field_facts = [fact for fact in facts if fact.confidence in {"high", "medium", "low"}]
        elif dimension == "risks":
            field_facts = [fact for fact in facts if fact.conflict_group or fact.confidence == "unknown"]
        else:
            field_facts = [fact for field in _RUBRIC_FIELDS.get(dimension, {dimension}) for fact in by_field.get(field, [])]
        label = dimension.replace("_", " ").title()
        if dimension == "indian_ecosystem_relevance":
            label = "Indian Ecosystem Relevance"
        if field_facts:
            lines.append(f"- **{_text(label)}:** evidence-backed signals are present; assess against the cited facts above.")
        else:
            lines.append(f"- **{_text(label)}:** unknown — no explicit fact was extracted; do not infer strength.")
    lines.extend([
        "- **Strongest case:** the cited, highest-authority facts are the strongest support; this is not a composite score.",
        "- **Weakest evidence:** missing or conflicting facts remain uncertainty, not a negative claim.",
        "- **What would change the assessment:** a dated primary filing, first-party metric, or authoritative registry record for each unknown dimension.",
    ])
    return lines


def _coverage(outcomes: Mapping[str, SourceOutcome], profile: StartupProfile) -> list[str]:
    lines = [f"Entities: 1 · Facts: {len(profile.facts)} · Evidence references: {len(profile.evidence)}"]
    if not outcomes:
        lines.append("Source status: not supplied")
    for source, outcome in outcomes.items():
        detail = f" — {outcome.detail}" if outcome.detail else ""
        lines.append(f"- **{_text(source)}:** {outcome.state} ({outcome.items_returned} items){_text(detail)}")
    return lines


def render_profile(profile: StartupProfile, *, source_outcomes: Mapping[str, SourceOutcome] | None = None, title: str | None = None, dimensions: Iterable[str] | None = None) -> str:
    """Render every report section, including explicit unknowns and status."""
    identity = profile.identity
    refs = {ref.evidence_id: ref for ref in profile.evidence}
    facts = _facts(profile, refs)
    dims = _dimensions(profile, dimensions)
    lines = [f"# {_text(title or identity.display_name)}", "", f"Entity ID: `{_text(identity.entity_id)}` · Identity: {identity.state} ({identity.confidence})", f"Research horizon: current snapshot + {profile.horizon_months} months", "", "## Coverage and source status", ""]
    lines.extend(_coverage(_source_outcomes(source_outcomes), profile)); lines.extend(["", "## Executive snapshot", "", f"**Decision view:** Evidence is available for {len(facts)} explicit facts; unsupported claims are marked unknown.", "", "## Identity and facts", ""])
    identity_facts = [fact for fact in facts if fact.field in {"legal_name", "website", "headquarters", "founded_year", "dpiit_id", "dpiit_recognized", "industry", "stage"}]
    if identity_facts:
        lines.extend(_fact_line(fact, refs) for fact in identity_facts)
    else:
        lines.append("- No identity facts were extracted.")
    for heading, fields in (("Product, market, and traction", {"product", "market", "employees", "revenue", "profit", "net_profit", "ebitda", "market_cap", "pe"}), ("Team", {"founders", "employees"}), ("Funding and financial timeline", {"funding", "funding_rounds", "investors", "revenue", "profit", "net_profit", "ebitda", "market_cap", "pe"}), ("Community and media", {"community", "media"})):
        lines.extend(["", f"## {heading}", ""])
        section = [fact for fact in facts if fact.field in fields]
        lines.extend(_fact_line(fact, refs) for fact in section) if section else lines.append("- Unknown — no explicit evidence-backed facts were extracted.")
    lines.extend(["", "## Qualitative GOAT rubric", ""]); lines.extend(_rubric(profile, facts, dims))
    lines.extend(["", "## Risks and unknowns", "", "- Conflicting values are shown below without hiding alternatives.", "- Missing dates, unavailable sources, and unresolved identity details are unknowns, not inferred negatives."])
    if getattr(profile, "conflicts", None):
        lines.extend(["", "### Conflicts"])
        for conflict in profile.conflicts:
            values = "; ".join(_text(value) for value in conflict.values)
            lines.append(f"- **{_text(conflict.field)}:** {values}. Selected citation: `{_text(conflict.selected_evidence_id or 'none')}`. {conflict.rationale}")
    lines.extend(["", "## Source matrix", "", "| Source | Evidence |", "|---|---:|"])
    counts = defaultdict(int)
    for ref in profile.evidence: counts[ref.source or "unknown"] += 1
    lines.extend(f"| {_text(source)} | {count} |" for source, count in sorted(counts.items()))
    if not counts: lines.append("| none | 0 |")
    lines.extend(["", "## Evidence ledger and citations", ""])
    for ref in profile.evidence:
        link = safe_link(ref.url or "source", ref.url) if ref.url else "source"
        lines.append(f"- `{_text(ref.evidence_id)}` · {_text(ref.source or 'unknown')} · {_text(ref.field or 'source')} · {link}")
    return "\n".join(lines).rstrip() + "\n"


def render_group(group: GroupProfile, *, dimensions: Iterable[str] | None = None, source_outcomes: Mapping[str, Mapping[str, SourceOutcome]] | None = None, query: str | None = None) -> str:
    dims = [value for value in (list(dimensions) if dimensions is not None else _DIMENSIONS) if value in _DIMENSIONS]
    dims = dims or list(_DIMENSIONS)
    lines = [f"# Startup India GOAT comparison{': ' + _text(query) if query else ''}", "", "## Comparison matrix", "", "| Dimension | " + " | ".join(_text(profile.identity.display_name) for profile in group.profiles) + " |", "|---|" + "---|" * len(group.profiles)]
    for dimension in dims:
        cells = []
        for profile in group.profiles:
            facts = [fact for fact in profile.facts if fact.entity_id == profile.identity.entity_id and fact.field == dimension]
            cells.append("; ".join(_text(fact.value) for fact in facts) if facts else "Unknown")
        lines.append("| " + _text(dimension.title()) + " | " + " | ".join(cells) + " |")
    lines.extend(["", "*Comparison is qualitative and dimension-limited; no composite score is calculated.*", ""])
    for profile in group.profiles:
        lines.extend(["---", "", render_profile(profile, source_outcomes=(source_outcomes or {}).get(profile.identity.entity_id), title=profile.identity.display_name, dimensions=dims).lstrip()])
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(value: StartupProfile | GroupProfile, **kwargs: object) -> str:
    return render_group(value, **kwargs) if isinstance(value, GroupProfile) else render_profile(value, **kwargs)

render_report = render_markdown
render_startup_markdown = render_markdown
render_single = render_profile
render_comparison = render_group


def render_html(value: StartupProfile | GroupProfile, **kwargs: object) -> str:
    # Lazy import avoids a startup_render <-> startup_html import cycle while
    # keeping one discoverable rendering entrypoint for hosts.
    from .startup_html import render_html as _render_html
    return _render_html(value, **kwargs)


__all__ = ["render_comparison", "render_group", "render_html", "render_markdown", "render_profile", "render_report", "render_startup_markdown", "safe_link"]
