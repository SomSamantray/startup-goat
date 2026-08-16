"""Validated startup fact extraction and field-level conflict resolution.

Only explicit structured fields and conservative ``key: value`` lines become
facts.  Narrative source text is evidence, not an invitation to infer claims.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from .schema import SourceItem
from .startup_evidence import EvidenceRecord, group_conflicts
from .startup_schema import EvidenceReference, StartupFact, StartupIdentity, StartupProfile

# Larger values win within a field.  This is deliberately field-specific rather
# than a universal source leaderboard.
FIELD_AUTHORITIES: dict[str, tuple[str, ...]] = {
    "dpiit_recognized": ("startup-india",),
    "dpiit_id": ("startup-india",),
    "founded_year": ("startup-india", "linkedin", "screener"),
    "revenue": ("screener", "tracxn"),
    "profit": ("screener", "tracxn"),
    "net_profit": ("screener", "tracxn"),
    "ebitda": ("screener", "tracxn"),
    "market_cap": ("screener",),
    "pe": ("screener",),
    "funding": ("tracxn", "screener", "yourstory", "inc42", "the-ken"),
    "funding_rounds": ("tracxn", "yourstory", "inc42", "the-ken"),
    "investors": ("tracxn", "yourstory", "inc42"),
    "product": ("linkedin", "yourstory", "inc42", "the-ken"),
    "market": ("yourstory", "inc42", "the-ken"),
    "legal_name": ("startup-india", "screener", "linkedin"),
    "website": ("startup-india", "screener", "linkedin"),
    "stage": ("startup-india", "tracxn", "linkedin"),
}
SOURCE_TIERS = {"startup-india": "authoritative", "screener": "authoritative", "linkedin": "primary", "tracxn": "commercial", "yourstory": "secondary", "inc42": "secondary", "the-ken": "secondary", "github": "primary", "x": "social", "reddit": "social", "youtube": "social", "web": "secondary"}
_TIER_RANK = {"authoritative": 5, "primary": 4, "secondary": 3, "commercial": 2, "social": 1, "unknown": 0}

ALIASES = {
    "company_name": "legal_name", "name": "legal_name", "company": "legal_name",
    "dpiit-recognized": "dpiit_recognized", "dpiit_recognition": "dpiit_recognized",
    "dpiit_id": "dpiit_id", "profile_id": "dpiit_id", "market-cap": "market_cap",
    "employee_count": "employees", "employees_count": "employees", "team_size": "employees",
    "funding_rounds": "funding_rounds", "funding_total": "funding", "total_funding": "funding",
    "description": "product", "tagline": "product", "website_url": "website",
    "hq": "headquarters", "location": "headquarters", "city": "headquarters",
    "founded": "founded_year", "founded_year": "founded_year", "investor": "investors",
}
KNOWN_FIELDS = frozenset({"legal_name", "dpiit_recognized", "dpiit_id", "founded_year", "revenue", "profit", "net_profit", "ebitda", "market_cap", "pe", "funding", "funding_rounds", "investors", "product", "market", "employees", "headquarters", "website", "stage", "industry", "ticker", "founders"})
DATED_FIELDS = frozenset({"revenue", "profit", "net_profit", "ebitda", "market_cap", "pe", "funding", "funding_rounds", "employees", "stage"})
_FAILURE_MARKERS = ("no results", "unreachable", "request failed", "schema drift", "login required", "paywall", "captcha", "quota", "not configured", "access denied")
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _-]{1,50})\s*:\s*(.*?)\s*$")


@dataclass(frozen=True)
class FactConflict:
    conflict_group: str
    entity_id: str
    field: str
    values: tuple[Any, ...]
    selected_evidence_id: str | None = None
    rationale: str = "Selected by field authority, then recency; alternatives remain cited."


def canonical_field(value: Any) -> str | None:
    key = str(value or "").strip().casefold().replace(" ", "_")
    key = ALIASES.get(key, key)
    return key if key in KNOWN_FIELDS else None


def field_authority(field: str, source: str) -> int:
    preferred = FIELD_AUTHORITIES.get(field, ())
    if source in preferred:
        return len(preferred) - preferred.index(source) + 10
    return _TIER_RANK.get(SOURCE_TIERS.get(source, "unknown"), 0)


def _parse_value(field: str, value: Any) -> Any:
    if isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [_parse_value(field, child) for child in value[:100]]
    text = re.sub(r"<[^>]{0,500}>", " ", str(value)).strip()
    if not text or len(text) > 2_000 or any(marker in text.casefold() for marker in _FAILURE_MARKERS):
        raise ValueError("empty, hostile, or failure value")
    if field == "dpiit_recognized":
        if text.casefold() in {"yes", "true", "recognized", "registered"}: return True
        if text.casefold() in {"no", "false", "not recognized", "unrecognized"}: return False
    if field == "founded_year":
        match = re.fullmatch(r"(?:19|20)\d{2}", text)
        if match: return int(text)
    # Keep currencies and units intact; converting them would imply a unit.
    return text


def _explicit_fields(item: SourceItem) -> dict[str, Any]:
    metadata = item.metadata if isinstance(item.metadata, Mapping) else {}
    raw: dict[str, Any] = {}
    structured = metadata.get("structured_facts")
    if isinstance(structured, Mapping): raw.update(structured)
    for key, value in metadata.items():
        if canonical_field(key) and value is not None and key not in {"generated_commentary"}:
            raw[key] = value
    # Adapters such as Tracxn/LinkedIn emit labelled body rows.  Do not parse
    # prose sentences, and never turn access/failure diagnostics into claims.
    if isinstance(item.body, str):
        existing_fields = {canonical_field(key) for key in raw}
        for line in item.body.splitlines():
            match = _LINE.match(line)
            field = canonical_field(match.group(1)) if match else None
            if field and field not in existing_fields:
                raw[match.group(1)] = match.group(2)
                existing_fields.add(field)
    result: dict[str, Any] = {}
    for key, value in raw.items():
        field = canonical_field(key)
        if field is None or value is None or value == "": continue
        try: result[field] = _parse_value(field, value)
        except (TypeError, ValueError): continue
    return result


def _date_value(item: SourceItem) -> tuple[str | None, str | None]:
    metadata = item.metadata if isinstance(item.metadata, Mapping) else {}
    as_of = metadata.get("as_of_date") or metadata.get("portal_last_updated") or metadata.get("capture_time")
    published = item.published_at
    def clean(value: Any) -> str | None:
        if not value: return None
        text = str(value)[:40]
        try: return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            try: return date.fromisoformat(text[:10]).isoformat()
            except ValueError: return None
    return clean(as_of), clean(published)


def _confidence(source: str, access_state: str) -> str:
    if access_state in {"unknown", "login-required", "paywalled", "captcha", "quota-exhausted"}: return "unknown"
    rank = _TIER_RANK.get(SOURCE_TIERS.get(source, "unknown"), 0)
    return "high" if rank >= 4 else "medium" if rank >= 2 else "low"


def _valid_item(item: SourceItem, identity: StartupIdentity) -> bool:
    metadata = item.metadata if isinstance(item.metadata, Mapping) else {}
    if metadata.get("entity_id") not in (None, identity.entity_id): return False
    claim = str(metadata.get("claim_type", "")).casefold()
    if claim in {"access-limitation", "error", "failure"}: return False
    return bool(item.url and (item.title or item.body))


def extract_profile(identity: StartupIdentity, items: Iterable[SourceItem] = (), *, evidence_records: Iterable[EvidenceRecord] | None = None, dimensions: Iterable[str] = (), horizon_months: int = 24, generated_at: str | None = None) -> StartupProfile:
    """Build one entity-bound profile from explicit source fields."""
    selected_items = [item for item in items if isinstance(item, SourceItem) and _valid_item(item, identity)]
    records = list(evidence_records or [])
    records = [record for record in records if record.entity_id == identity.entity_id]
    by_item = {record.item_id: record for record in records}
    candidates: list[tuple[str, Any, EvidenceRecord, str | None, str | None]] = []
    for item in selected_items:
        fields = _explicit_fields(item)
        if not fields: continue
        record = by_item.get(item.item_id)
        for field, value in fields.items():
            if record is None:
                metadata = item.metadata if isinstance(item.metadata, Mapping) else {}
                record = EvidenceRecord.from_source_item(item, entity_id=identity.entity_id, claim_type=str(metadata.get("claim_type", "source")), field_type=field, source_tier=SOURCE_TIERS.get(item.source, "unknown"), confidence=_confidence(item.source, str(metadata.get("access_state", "public"))), access_state=str(metadata.get("access_state", "public")), access_mode=str(metadata.get("access_mode", "public-http")), as_of_date=_date_value(item)[0])
                records.append(record)
            # One source item can support several explicit fields. Keep a
            # distinct field-scoped evidence ID so conflict grouping never
            # conflates values from different fields.
            if record.field_type != field:
                record = EvidenceRecord(**{**record.__dict__, "evidence_id": f"{record.evidence_id}_{field}", "field_type": field})
            if record not in records:
                records.append(record)
            as_of, published = _date_value(item)
            candidates.append((field, value, record, as_of, published))
    values_for_conflict = {record.evidence_id: value for _, value, record, _, _ in candidates}
    records = group_conflicts(records, values_for_conflict)
    conflict_lookup = {record.evidence_id: record.conflict_group for record in records}
    facts: list[StartupFact] = []
    for field, value, record, as_of, published in candidates:
        group = conflict_lookup.get(record.evidence_id)
        # A metric without a source date is retained as an evergreen
        # snapshot rather than falsely assigning it to the research window.
        dated = field in DATED_FIELDS and bool(as_of or published)
        facts.append(StartupFact(entity_id=identity.entity_id, field=field, value=value, evidence_refs=[record.reference()], confidence=_confidence(record.source, record.access_state), as_of_date=as_of, published_at=published, conflict_group=group, source_authority=record.source, is_evergreen=not dated))
    # Keep one reference per record while preserving order.
    references: list[EvidenceReference] = []
    seen: set[str] = set()
    for record in records:
        if record.evidence_id not in seen:
            references.append(record.reference()); seen.add(record.evidence_id)
    conflicts: list[FactConflict] = []
    for field in sorted({fact.field for fact in facts}):
        field_facts = [fact for fact in facts if fact.field == field]
        unique = {json.dumps(fact.value, sort_keys=True, default=str) for fact in field_facts}
        if len(unique) < 2: continue
        group = next((fact.conflict_group for fact in field_facts if fact.conflict_group), f"conflict_{identity.entity_id}_{field}")
        ranked = sorted(field_facts, key=lambda fact: (field_authority(field, fact.source_authority or ""), fact.published_at or fact.as_of_date or ""), reverse=True)
        conflicts.append(FactConflict(group, identity.entity_id, field, tuple(fact.value for fact in ranked), ranked[0].evidence_refs[0].evidence_id if ranked and ranked[0].evidence_refs else None))
    return StartupProfile(identity=identity, facts=facts, evidence=references, dimensions=list(dimensions), horizon_months=horizon_months, generated_at=generated_at, conflicts=conflicts)


def extract_facts(identity: StartupIdentity, items: Iterable[SourceItem] = (), **kwargs: Any) -> StartupProfile:
    return extract_profile(identity, items, **kwargs)


def resolve_conflicts(profile: StartupProfile) -> list[FactConflict]:
    return list(getattr(profile, "conflicts", []))


# Descriptive aliases used by host integrations and earlier planning drafts.
build_profile = extract_profile
extract_startup_facts = extract_profile


__all__ = ["FIELD_AUTHORITIES", "FactConflict", "build_profile", "canonical_field", "extract_facts", "extract_profile", "extract_startup_facts", "field_authority", "resolve_conflicts"]
