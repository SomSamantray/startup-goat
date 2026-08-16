"""Typed domain models for Startup India GOAT research.

These models sit above the generic :mod:`schema` transport models.  They keep
startup identity and claims explicit without teaching ``SourceItem`` about
startup-specific semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Literal

STARTUP_SCHEMA_VERSION = "1.0"

IdentityState = Literal["resolved", "ambiguous", "unresolved", "quarantined"]
IdentityConfidence = Literal["high", "medium", "low", "none"]
FactConfidence = Literal["high", "medium", "low", "unknown"]


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def to_dict(value: Any) -> Any:
    """Return a JSON-compatible representation without dropping explicit state."""
    return _json_value(value)


@dataclass(frozen=True)
class EvidenceReference:
    """A claim-to-evidence pointer; raw transport remains a ``SourceItem``."""

    evidence_id: str
    item_id: str | None = None
    source: str | None = None
    url: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class IdentityCandidate:
    """A deterministic or agent-proposed identity match awaiting validation."""

    candidate_id: str
    display_name: str
    normalized_name: str
    confidence: IdentityConfidence = "none"
    state: IdentityState = "unresolved"
    matched_identifiers: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None


@dataclass
class StartupIdentity:
    """Canonical identifiers for one startup, with explicit resolution state."""

    entity_id: str
    display_name: str
    normalized_name: str
    legal_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    handles: list[str] = field(default_factory=list)
    exchange_ids: list[str] = field(default_factory=list)
    dpiit_ids: list[str] = field(default_factory=list)
    state: IdentityState = "unresolved"
    confidence: IdentityConfidence = "none"
    input_position: int | None = None
    candidate_ids: list[str] = field(default_factory=list)
    quarantine_reason: str | None = None
    user_confirmed: bool = False

    def __post_init__(self) -> None:
        if self.state not in {"resolved", "ambiguous", "unresolved", "quarantined"}:
            raise ValueError(f"unknown identity state: {self.state}")
        if self.confidence not in {"high", "medium", "low", "none"}:
            raise ValueError(f"unknown identity confidence: {self.confidence}")
        if not self.entity_id:
            raise ValueError("StartupIdentity.entity_id must not be empty")
        if not self.display_name.strip():
            raise ValueError("StartupIdentity.display_name must not be empty")
        if not self.normalized_name:
            raise ValueError("StartupIdentity.normalized_name must not be empty")
        if self.state == "quarantined" and not self.quarantine_reason:
            raise ValueError("quarantined identities require quarantine_reason")
        if self.state == "resolved" and self.confidence == "none":
            raise ValueError("resolved identities require non-empty confidence")


@dataclass
class StartupFact:
    """One typed, dated startup claim and its immutable evidence references."""

    entity_id: str
    field: str
    value: Any
    evidence_refs: list[EvidenceReference | str] = field(default_factory=list)
    confidence: FactConfidence = "unknown"
    as_of_date: str | None = None
    published_at: str | None = None
    conflict_group: str | None = None
    source_authority: str | None = None
    is_evergreen: bool = True

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("StartupFact.entity_id must not be empty")
        if not self.field.strip():
            raise ValueError("StartupFact.field must not be empty")
        if not self.is_evergreen and not (self.as_of_date or self.published_at):
            raise ValueError("dated facts require as_of_date or published_at")


@dataclass
class StartupProfile:
    """A single startup snapshot plus dated facts and evidence links."""

    identity: StartupIdentity
    facts: list[StartupFact] = field(default_factory=list)
    evidence: list[EvidenceReference] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    horizon_months: int = 24
    generated_at: str | None = None
    schema_version: str = STARTUP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.horizon_months < 0:
            raise ValueError("horizon_months must not be negative")
        for fact in self.facts:
            if fact.entity_id != self.identity.entity_id:
                raise ValueError("StartupProfile facts must match identity.entity_id")


@dataclass
class GroupProfile:
    """Ordered profiles for a comparison request; no implicit cross-entity joins."""

    profiles: list[StartupProfile] = field(default_factory=list)
    query: str = ""
    schema_version: str = STARTUP_SCHEMA_VERSION

    @property
    def entity_ids(self) -> list[str]:
        return [profile.identity.entity_id for profile in self.profiles]

    def __post_init__(self) -> None:
        ids = self.entity_ids
        if len(ids) != len(set(ids)):
            raise ValueError("GroupProfile entity IDs must be unique")


@dataclass(frozen=True)
class QueryDimensions:
    """Requested dimensions, kept ordered for deterministic planning and output."""

    values: tuple[str, ...] = ()
    audience: str | None = None
    depth: Literal["brief", "standard", "deep"] = "standard"
    horizon_months: int = 24

    def __post_init__(self) -> None:
        if self.horizon_months < 0:
            raise ValueError("horizon_months must not be negative")
        if len(set(self.values)) != len(self.values):
            raise ValueError("query dimensions must be unique")


@dataclass(frozen=True)
class StartupQuery:
    """Normalized request envelope consumed by later planner integration."""

    raw_query: str
    entities: tuple[StartupIdentity, ...] = ()
    dimensions: QueryDimensions = QueryDimensions()
    comparison: bool = False

    def __post_init__(self) -> None:
        if not self.raw_query.strip():
            raise ValueError("raw_query must not be empty")
        if self.comparison and len(self.entities) < 2:
            raise ValueError("comparison queries require at least two entities")


@dataclass(frozen=True)
class QuarantinedIdentity:
    """Explicit unresolved input that must not enter source fanout."""

    raw_input: str
    reason: str
    input_position: int | None = None
    candidate_ids: tuple[str, ...] = ()


__all__ = [
    "STARTUP_SCHEMA_VERSION",
    "EvidenceReference",
    "GroupProfile",
    "IdentityCandidate",
    "IdentityConfidence",
    "IdentityState",
    "QueryDimensions",
    "QuarantinedIdentity",
    "StartupFact",
    "StartupIdentity",
    "StartupProfile",
    "StartupQuery",
    "to_dict",
]
