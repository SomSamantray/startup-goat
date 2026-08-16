"""Startup provenance records layered over the generic ``SourceItem`` contract.

Adapters produce normal ``schema.SourceItem`` values.  This module deliberately
stores only references and provenance around those values; it never creates a
second transport item shape or copies untrusted source payloads into artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping

from .schema import SourceItem, SourceOutcome
from .startup_schema import EvidenceReference, StartupFact, to_dict

STARTUP_EVIDENCE_VERSION = "1.0"
AccessState = Literal[
    "public",
    "private-session",
    "login-required",
    "paywalled",
    "captcha",
    "quota-exhausted",
    "browser-unavailable",
    "not-applicable",
    "unknown",
]
AccessMode = Literal["public-http", "bearer-token", "browser-capture", "none", "unknown"]
EvidenceConfidence = Literal["high", "medium", "low", "unknown"]
SourceTier = Literal["authoritative", "primary", "secondary", "social", "commercial", "unknown"]

ACCESS_STATES = frozenset(
    {
        "public", "private-session", "login-required", "paywalled", "captcha",
        "quota-exhausted", "browser-unavailable", "not-applicable", "unknown",
    }
)
ACCESS_MODES = frozenset({"public-http", "bearer-token", "browser-capture", "none", "unknown"})
SOURCE_TIERS = frozenset({"authoritative", "primary", "secondary", "social", "commercial", "unknown"})

# These patterns are intentionally conservative: they catch credentials and
# transport secrets, while ordinary words in article text remain acceptable.
_SECRET_VALUE_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9_\-]{16,}|"
    r"AIza[A-Za-z0-9_\-]{20,}|Bearer\s+[A-Za-z0-9._\-~+/]{16,}|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|csrf[_-]?token)"
    r"\s*[:=]\s*[^\s,;]{8,})",
    re.IGNORECASE,
)
_SECRET_KEY_RE = re.compile(
    r"(?:authorization|cookie|set-cookie|x-csrf|csrf|password|secret|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|request[_-]?headers|browser[_-]?storage)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _walk_secrets(value: Any, path: str = "") -> str | None:
    """Return the first secret-bearing path, or ``None``.

    Mapping keys are rejected because preserving a cookie/header/token field is
    unsafe even when its value is redacted.  Values are scanned for common
    credential forms so secret-tainted evidence fails closed.
    """
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if _SECRET_KEY_RE.search(str(key)):
                return key_path
            found = _walk_secrets(child, key_path)
            if found:
                return found
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            found = _walk_secrets(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        return path or "value"
    return None


def assert_safe_evidence(value: Any) -> None:
    """Raise ``ValueError`` when serialization would preserve a secret."""
    found = _walk_secrets(value)
    if found:
        raise ValueError(f"secret-like evidence field rejected: {found}")


def source_item_content_hash(item: SourceItem) -> str:
    """Hash stable item content without changing the generic item contract."""
    payload = {
        "item_id": item.item_id,
        "source": item.source,
        "title": item.title,
        "body": item.body,
        "url": item.url,
        "published_at": item.published_at,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    """A provenance projection of one ``SourceItem``.

    ``item_id`` is the only transport link.  Callers retain the original
    ``SourceItem`` in the generic evidence pool and can join it by this ID.
    """

    evidence_id: str
    item_id: str
    entity_id: str
    source: str
    canonical_url: str
    claim_type: str
    field_type: str
    source_tier: SourceTier = "unknown"
    retrieved_at: str = field(default_factory=_utc_now)
    confidence: EvidenceConfidence = "unknown"
    access_state: AccessState = "unknown"
    access_mode: AccessMode = "unknown"
    content_hash: str = ""
    conflict_group: str | None = None
    as_of_date: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.item_id or not self.entity_id:
            raise ValueError("evidence_id, item_id, and entity_id are required")
        if not self.source or not self.canonical_url:
            raise ValueError("source and canonical_url are required")
        if self.access_state not in ACCESS_STATES:
            raise ValueError(f"unknown startup access_state: {self.access_state}")
        if self.access_mode not in ACCESS_MODES:
            raise ValueError(f"unknown startup access_mode: {self.access_mode}")
        if self.source_tier not in SOURCE_TIERS:
            raise ValueError(f"unknown source tier: {self.source_tier}")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError(f"unknown evidence confidence: {self.confidence}")
        if self.access_state == "public" and self.access_mode not in {"public-http", "unknown"}:
            raise ValueError("public evidence must use public-http or unknown access mode")
        if self.access_state in {"private-session", "login-required", "paywalled", "quota-exhausted"} and self.access_mode == "public-http":
            raise ValueError("gated evidence cannot claim public-http access")
        assert_safe_evidence(self.metadata)

    @classmethod
    def from_source_item(
        cls,
        item: SourceItem,
        *,
        entity_id: str,
        claim_type: str,
        field_type: str,
        source_tier: SourceTier = "unknown",
        retrieved_at: str | None = None,
        confidence: EvidenceConfidence = "unknown",
        access_state: AccessState = "public",
        access_mode: AccessMode = "public-http",
        as_of_date: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "EvidenceRecord":
        """Project an item into provenance after secret checks."""
        assert_safe_evidence(item.metadata)
        assert_safe_evidence(item.body)
        assert_safe_evidence(metadata or {})
        digest = source_item_content_hash(item)
        evidence_id = hashlib.sha256(f"{entity_id}|{item.item_id}|{digest}".encode()).hexdigest()[:24]
        return cls(
            evidence_id=evidence_id,
            item_id=item.item_id,
            entity_id=entity_id,
            source=item.source,
            canonical_url=item.url,
            claim_type=claim_type,
            field_type=field_type,
            source_tier=source_tier,
            retrieved_at=retrieved_at or _utc_now(),
            confidence=confidence,
            access_state=access_state,
            access_mode=access_mode,
            content_hash=digest,
            as_of_date=as_of_date or item.published_at,
            metadata=dict(metadata or {}),
        )

    def with_conflict_group(self, conflict_group: str | None) -> "EvidenceRecord":
        return replace(self, conflict_group=conflict_group)

    def reference(self) -> EvidenceReference:
        return EvidenceReference(
            evidence_id=self.evidence_id,
            item_id=self.item_id,
            source=self.source,
            url=self.canonical_url,
            field=self.field_type,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = to_dict(self)
        assert_safe_evidence(payload)
        return payload


def evidence_from_dict(payload: Mapping[str, Any]) -> EvidenceRecord:
    """Deserialize a validated provenance record, never a raw SourceItem."""
    record = EvidenceRecord(**dict(payload))
    assert_safe_evidence(record.to_dict())
    return record


def _conflict_key(record: EvidenceRecord, value: Any = None, *, entity_id: str | None = None) -> str:
    # A conflict group identifies the competing entity/field, not one value;
    # all citations for the field therefore share the same group.
    digest = hashlib.sha256(f"{entity_id or record.entity_id}|{record.field_type}".encode()).hexdigest()[:16]
    return f"conflict_{digest}"


def group_conflicts(records: Iterable[EvidenceRecord], values: Mapping[str, Any]) -> list[EvidenceRecord]:
    """Assign one conflict group to competing values of the same entity/field.

    Lower-ranked records are preserved.  Records without a value entry remain
    unchanged, and records for different entities cannot share a group.
    """
    records_list = list(records)
    buckets: dict[tuple[str, str], set[str]] = {}
    for record in records_list:
        if record.evidence_id not in values:
            continue
        key = (record.entity_id, record.field_type)
        encoded = json.dumps(values[record.evidence_id], sort_keys=True, ensure_ascii=False, default=str)
        buckets.setdefault(key, set()).add(encoded)
    groups = {key: len(items) > 1 for key, items in buckets.items()}
    result: list[EvidenceRecord] = []
    for record in records_list:
        if record.evidence_id not in values:
            result.append(record)
            continue
        key = (record.entity_id, record.field_type)
        group = _conflict_key(record, values[record.evidence_id]) if groups.get(key) else None
        result.append(record.with_conflict_group(group))
    return result


@dataclass
class EvidenceLedger:
    """Entity-scoped evidence records and typed facts for one run."""

    records: list[EvidenceRecord] = field(default_factory=list)
    facts: list[StartupFact] = field(default_factory=list)
    schema_version: str = STARTUP_EVIDENCE_VERSION

    def add_item(self, item: SourceItem, **kwargs: Any) -> EvidenceRecord:
        record = EvidenceRecord.from_source_item(item, **kwargs)
        self.records.append(record)
        return record

    def add_fact(self, fact: StartupFact) -> None:
        self.facts.append(fact)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "records": [record.to_dict() for record in self.records],
            "facts": [to_dict(fact) for fact in self.facts],
        }
        assert_safe_evidence(payload)
        return payload


__all__ = [
    "ACCESS_MODES", "ACCESS_STATES", "SOURCE_TIERS", "AccessMode", "AccessState",
    "EvidenceLedger", "EvidenceRecord", "assert_safe_evidence", "evidence_from_dict",
    "group_conflicts", "source_item_content_hash",
]
