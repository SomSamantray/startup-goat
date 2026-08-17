"""Deterministic startup identity normalization and bounded resolution helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from typing import Iterable
from urllib.parse import urlsplit

from .startup_schema import (
    IdentityCandidate,
    IdentityConfidence,
    QuarantinedIdentity,
    StartupIdentity,
)

# Only legal-form suffixes are removed from the matching key. Product words
# such as "Labs", "Pay", and "Tech" are meaningful and must remain intact.
_LEGAL_SUFFIXES = (
    "private limited",
    "pvt limited",
    "pvt ltd",
    "private ltd",
    "public limited",
    "public ltd",
    "limited liability partnership",
    "llp",
    "ltd",
    "incorporated",
    "inc",
    "corporation",
    "corp",
    "limited",
    "ltd",
)
_SPACE_RE = re.compile(r"\s+")
_NON_NAME_RE = re.compile(r"[^\w\s&+.-]+", re.UNICODE)


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return _SPACE_RE.sub(" ", text)


def normalize_name(value: str | None) -> str:
    """Normalize a display/brand name into a conservative matching key."""
    text = _clean(value).replace("&", " and ")
    text = text.replace("’", "'")
    text = _NON_NAME_RE.sub(" ", text)
    text = re.sub(r"[._/-]+", " ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    # Repeatedly remove one legal suffix, including punctuation-normalized
    # variants, but never remove a product word merely because it is common.
    changed = True
    while changed and text:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text == suffix:
                return ""
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].rstrip()
                changed = True
                break
    return text


def normalize_legal_name(value: str | None) -> str:
    """Normalize legal names while retaining their legal-form suffix."""
    text = _clean(value)
    text = _NON_NAME_RE.sub(" ", text)
    text = re.sub(r"[._/-]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_domain(value: str | None) -> str:
    """Return a host-only lowercase domain, or ``""`` for invalid input."""
    text = _clean(value).strip("<>")
    if not text:
        return ""
    parsed = urlsplit(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").rstrip(".").casefold()
    if not host or any(ch.isspace() for ch in host) or "." not in host:
        return ""
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_ticker(value: str | None) -> str:
    """Normalize an exchange ticker while preserving meaningful separators."""
    text = _clean(value).lstrip("$").replace(" ", "")
    return re.sub(r"[^a-z0-9._-]", "", text).upper()


def normalize_handle(value: str | None) -> str:
    """Normalize a social handle or profile URL to a bare lowercase handle.

    A URL with a path (``https://www.linkedin.com/company/inc42`` or
    ``linkedin.com/company/inc42``) yields the last path segment — the vanity
    slug.  A bare dotted handle with no path (``acme.x``) and a bare handle
    (``@acme``) are kept as-is, preserving identity-key stability for existing
    handle inputs.
    """
    text = _clean(value).strip().rstrip("/")
    has_path = "/" in text.rstrip("/")
    if "://" in text or text.startswith("www.") or has_path:
        path = (urlsplit(text if "://" in text else "https://" + text).path or "").strip("/")
        # A company-profile URL yields the vanity slug; a bare handle stays.
        segments = [segment for segment in path.split("/") if segment]
        text = segments[-1] if segments else text
    text = text.lstrip("@").split("?", 1)[0].split("#", 1)[0]
    return re.sub(r"[^a-z0-9._-]", "", text)


def normalize_exchange_id(value: str | None) -> str:
    """Normalize a BSE/NSE or other exchange identifier."""
    text = _clean(value).upper()
    return re.sub(r"[^A-Z0-9._-]", "", text)


def normalize_dpiit_id(value: str | None) -> str:
    """Normalize a Startup India/DPIIT identifier without inventing one."""
    text = _clean(value).upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def _unique(values: Iterable[str], normalizer) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalizer(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _identity_key(
    normalized_name: str,
    *,
    legal_name: str | None,
    domains: list[str],
    tickers: list[str],
    handles: list[str],
    exchange_ids: list[str],
    dpiit_ids: list[str],
    occurrence: int | None = None,
) -> str:
    identifiers = [
        *(f"domain:{item}" for item in domains),
        *(f"ticker:{item}" for item in tickers),
        *(f"handle:{item}" for item in handles),
        *(f"exchange:{item}" for item in exchange_ids),
        *(f"dpiit:{item}" for item in dpiit_ids),
    ]
    # Legal names are useful aliases but are not a stable identity key on
    # their own: ``Acme Pvt Ltd`` and ``Acme`` remain one candidate until a
    # stronger identifier or an explicit collision disambiguator appears.
    identifiers = [item for item in identifiers if item]
    if not identifiers:
        identifiers = [f"name:{normalized_name}"]
    if occurrence is not None:
        identifiers.append(f"occurrence:{occurrence}")
    digest = hashlib.sha256("|".join([normalized_name, *sorted(identifiers)]).encode()).hexdigest()[:20]
    return f"startup_{digest}"


def build_identity(
    display_name: str,
    *,
    legal_name: str | None = None,
    aliases: Iterable[str] = (),
    domains: Iterable[str] = (),
    tickers: Iterable[str] = (),
    handles: Iterable[str] = (),
    exchange_ids: Iterable[str] = (),
    dpiit_ids: Iterable[str] = (),
    state: str = "unresolved",
    confidence: IdentityConfidence = "none",
    input_position: int | None = None,
    occurrence: int | None = None,
    candidate_ids: Iterable[str] = (),
    quarantine_reason: str | None = None,
    user_confirmed: bool = False,
) -> StartupIdentity:
    """Create a normalized identity without asserting unresolved matches."""
    normalized = normalize_name(display_name)
    if not normalized:
        raise ValueError("display_name has no usable normalized value")
    normalized_legal = normalize_legal_name(legal_name) or None
    normalized_aliases = _unique(aliases, normalize_name)
    if normalized not in normalized_aliases:
        normalized_aliases.insert(0, normalized)
    normalized_domains = _unique(domains, normalize_domain)
    normalized_tickers = _unique(tickers, normalize_ticker)
    normalized_handles = _unique(handles, normalize_handle)
    normalized_exchange_ids = _unique(exchange_ids, normalize_exchange_id)
    normalized_dpiit_ids = _unique(dpiit_ids, normalize_dpiit_id)
    entity_id = _identity_key(
        normalized,
        legal_name=normalized_legal,
        domains=normalized_domains,
        tickers=normalized_tickers,
        handles=normalized_handles,
        exchange_ids=normalized_exchange_ids,
        dpiit_ids=normalized_dpiit_ids,
        occurrence=occurrence,
    )
    return StartupIdentity(
        entity_id=entity_id,
        display_name=display_name.strip(),
        normalized_name=normalized,
        legal_name=normalized_legal,
        aliases=normalized_aliases,
        domains=normalized_domains,
        tickers=normalized_tickers,
        handles=normalized_handles,
        exchange_ids=normalized_exchange_ids,
        dpiit_ids=normalized_dpiit_ids,
        state=state,  # validated by StartupIdentity.__post_init__ on known values
        confidence=confidence,
        input_position=input_position,
        candidate_ids=list(candidate_ids),
        quarantine_reason=quarantine_reason,
        user_confirmed=user_confirmed,
    )


def build_group_identities(inputs: Iterable[dict], *, query: str = "") -> list[StartupIdentity]:
    """Build identities in input order, disambiguating duplicate weak names."""
    seen: Counter[str] = Counter()
    result: list[StartupIdentity] = []
    for position, data in enumerate(inputs):
        values = dict(data)
        name = values.pop("display_name", values.pop("name", ""))
        normalized = normalize_name(name)
        occurrence = seen[normalized]
        seen[normalized] += 1
        values.setdefault("input_position", position)
        if occurrence:
            values["occurrence"] = occurrence
        result.append(build_identity(name, **values))
    return result


def quarantine(raw_input: str, reason: str, *, input_position: int | None = None) -> QuarantinedIdentity:
    """Represent malformed or ambiguous input without creating a fake entity."""
    if not raw_input.strip():
        raise ValueError("raw_input must not be empty")
    if not reason.strip():
        raise ValueError("reason must not be empty")
    return QuarantinedIdentity(raw_input=raw_input, reason=reason, input_position=input_position)


def candidate_from_identity(identity: StartupIdentity, *, reason: str | None = None) -> IdentityCandidate:
    return IdentityCandidate(
        candidate_id=identity.entity_id,
        display_name=identity.display_name,
        normalized_name=identity.normalized_name,
        confidence=identity.confidence,
        state=identity.state,
        matched_identifiers=tuple(
            identity.domains
            + identity.tickers
            + identity.handles
            + identity.exchange_ids
            + identity.dpiit_ids
        ),
        reason=reason,
    )


# Friendly aliases used by callers and hidden integration tests.
normalize_brand_name = normalize_name
normalize_identity = build_identity


def stable_entity_id(identity_or_name: StartupIdentity | str, **kwargs: object) -> str:
    """Return the deterministic ID for an identity or normalized name.

    Passing a ``StartupIdentity`` returns its already-materialized ID. Passing
    a name is useful at the planning boundary and accepts the same optional
    identifier keyword arguments as :func:`build_identity`.
    """
    if isinstance(identity_or_name, StartupIdentity):
        return identity_or_name.entity_id
    identity = build_identity(str(identity_or_name), **kwargs)  # type: ignore[arg-type]
    return identity.entity_id

__all__ = [
    "build_group_identities",
    "build_identity",
    "candidate_from_identity",
    "normalize_brand_name",
    "normalize_domain",
    "normalize_dpiit_id",
    "normalize_exchange_id",
    "normalize_handle",
    "normalize_identity",
    "normalize_legal_name",
    "normalize_name",
    "normalize_ticker",
    "quarantine",
    "stable_entity_id",
]
