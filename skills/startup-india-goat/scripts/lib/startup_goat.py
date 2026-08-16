"""Startup India GOAT planning and bounded retrieval entrypoint."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .startup_identity import build_identity, quarantine
from .startup_facts import extract_profile
from .startup_pipeline import StartupBudgets, StartupEntityResult, StartupRetrievalResult, retrieve_group
from .startup_schema import GroupProfile, QuarantinedIdentity, StartupIdentity, StartupProfile, to_dict
from .startup_sources import resolve_source, source_registry

DEFAULT_STARTUP_SOURCES = tuple(capability.canonical_name for capability in source_registry() if capability.public)
_QUERY_PREFIX = re.compile(r"^(?:please\s+)?(?:research|analyze|analyse|profile|evaluate|compare|benchmark|look\s+up)\s+", re.I)


@dataclass(frozen=True)
class StartupRequest:
    raw_query: str
    entities: tuple[Mapping[str, Any] | str, ...] = ()
    sources: tuple[str, ...] = DEFAULT_STARTUP_SOURCES
    dimensions: tuple[str, ...] = ()
    audience: str | None = None
    depth: str = "standard"
    horizon_months: int = 24
    public_only: bool = True
    consent: bool = False
    config: Mapping[str, Any] = field(default_factory=dict)
    mock: bool = False
    budgets: StartupBudgets = field(default_factory=StartupBudgets)
    adapter_kwargs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.raw_query.strip():
            raise ValueError("raw_query must not be empty")
        if self.depth not in {"brief", "standard", "deep"}:
            raise ValueError("depth must be brief, standard, or deep")
        if self.horizon_months < 0:
            raise ValueError("horizon_months must not be negative")
        if self.public_only and self.consent:
            # Consent is harmless but confusing in a public-only request and
            # must not be interpreted as permission to activate gated sources.
            raise ValueError("public_only requests cannot carry gated-source consent")
        if not self.sources:
            raise ValueError("at least one source is required")


@dataclass
class StartupRun:
    request: StartupRequest
    retrieval: StartupRetrievalResult
    contract: dict[str, Any]
    profiles: list[StartupProfile] = field(default_factory=list)

    @property
    def entities(self) -> list[StartupEntityResult]:
        return self.retrieval.entities

    @property
    def quarantined(self) -> list[Any]:
        return self.retrieval.quarantined

    @property
    def group_profile(self) -> GroupProfile:
        return GroupProfile(profiles=list(self.profiles), query=self.request.raw_query)

    def save(self, **options: Any) -> Any:
        from .startup_save import save_bundle
        return save_bundle(self, **options)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "startup-india-goat/1.0",
            "contract": self.contract,
            "request": {
                "raw_query": self.request.raw_query,
                "sources": list(self.request.sources),
                "dimensions": list(self.request.dimensions),
                "audience": self.request.audience,
                "depth": self.request.depth,
                "horizon_months": self.request.horizon_months,
                "public_only": self.request.public_only,
                "consent": self.request.consent,
            },
            "profiles": [to_dict(profile) for profile in self.profiles],
            "entities": [
                {
                    "identity": to_dict(result.identity),
                    "items": [to_dict(item) for item in result.items],
                    "outcomes": {source: to_dict(value) for source, value in result.outcomes.items()},
                    "errors": list(result.errors),
                }
                for result in self.entities
            ],
            "quarantined": [to_dict(value) for value in self.retrieval.quarantined],
            "warnings": list(self.retrieval.warnings),
        }


def _split_query(raw_query: str) -> list[str]:
    text = _QUERY_PREFIX.sub("", raw_query.strip()).strip(" .")
    # Delimiters are intentionally conservative.  A plain request remains one
    # company; only explicit comparison punctuation/phrases create fanout.
    if re.search(r"\s+(?:vs\.?|versus)\s+", text, re.I):
        return [part.strip(" .") for part in re.split(r"\s+(?:vs\.?|versus)\s+", text, flags=re.I)]
    if re.search(r"[,;]\s*", text):
        return [part.strip(" .") for part in re.split(r"[,;]", text) if part.strip()]
    if re.search(r"\s+and\s+", text, re.I) and re.match(r"^(?:compare|benchmark)\b", raw_query.strip(), re.I):
        return [part.strip(" .") for part in re.split(r"\s+and\s+", text, flags=re.I) if part.strip()]
    return [text] if text else []


def _identity_inputs(request: StartupRequest) -> tuple[list[StartupIdentity], list[QuarantinedIdentity]]:
    raw_values: list[Mapping[str, Any] | str] = list(request.entities) or _split_query(request.raw_query)
    identities: list[StartupIdentity] = []
    quarantined: list[QuarantinedIdentity] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_values):
        values: dict[str, Any]
        if isinstance(raw, str):
            values = {"display_name": raw}
        elif isinstance(raw, Mapping):
            values = dict(raw)
        else:
            quarantined.append(quarantine(str(raw), "entity must be a company name or object", input_position=position))
            continue
        name = str(values.pop("display_name", values.pop("name", ""))).strip()
        if not name or name.casefold() in {"unknown", "unclear", "?", "n/a", "none"}:
            quarantined.append(quarantine(name or str(raw), "company identity is missing or unresolved", input_position=position))
            continue
        try:
            # A name supplied by the caller is a candidate accepted for this
            # run, not an invented legal identity. Optional identifiers remain
            # evidence supplied by the caller and are normalized by the model.
            values.setdefault("state", "resolved")
            values.setdefault("confidence", "high" if any(values.get(key) for key in ("domains", "tickers", "dpiit_ids", "exchange_ids")) else "low")
            values["input_position"] = position
            identity = build_identity(name, **values)
        except (TypeError, ValueError):
            quarantined.append(quarantine(name, "identity fields failed validation", input_position=position))
            continue
        if identity.normalized_name in seen:
            quarantined.append(quarantine(name, "duplicate identity is ambiguous in this request", input_position=position))
            continue
        seen.add(identity.normalized_name)
        identities.append(identity)
    return identities, quarantined


def _canonical_sources(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        capability = resolve_source(str(value))
        if capability.canonical_name not in result:
            result.append(capability.canonical_name)
    return result


def parse_request(raw_query: str | Mapping[str, Any] | StartupRequest, **options: Any) -> StartupRequest:
    if isinstance(raw_query, StartupRequest):
        if options:
            raise ValueError("options cannot be combined with StartupRequest")
        return raw_query
    if isinstance(raw_query, Mapping):
        payload = dict(raw_query)
        text = payload.pop("raw_query", payload.pop("query", ""))
        payload.update(options)
    else:
        text = raw_query
        payload = dict(options)
    allowed = {"entities", "companies", "sources", "dimensions", "audience", "depth", "horizon_months", "public_only", "consent", "config", "mock", "budgets", "adapter_kwargs"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown startup request option(s): {', '.join(sorted(unknown))}")
    entities = payload.pop("entities", payload.pop("companies", ()))
    if isinstance(entities, str) or isinstance(entities, Mapping):
        entities = (entities,)
    else:
        entities = tuple(entities or ())
    source_values = payload.pop("sources", DEFAULT_STARTUP_SOURCES)
    if source_values is None:
        source_values = DEFAULT_STARTUP_SOURCES
    if isinstance(source_values, str):
        source_values = tuple(part.strip() for part in source_values.split(",") if part.strip())
    budgets = payload.pop("budgets", None)
    if budgets is None:
        budget = StartupBudgets()
    elif isinstance(budgets, StartupBudgets):
        budget = budgets
    elif isinstance(budgets, Mapping):
        budget = StartupBudgets(**dict(budgets))
    else:
        raise ValueError("budgets must be a StartupBudgets or object")
    canonical = _canonical_sources(source_values)
    dimensions = payload.pop("dimensions", ())
    if isinstance(dimensions, str):
        dimensions = tuple(part.strip() for part in dimensions.split(",") if part.strip())
    return StartupRequest(raw_query=str(text), entities=entities, sources=tuple(canonical), dimensions=tuple(dimensions or ()), budgets=budget, **payload)


def build_source_plan(raw_query: str | Mapping[str, Any] | StartupRequest, **options: Any) -> dict[str, Any]:
    """Return the validated contract before any source fanout occurs."""
    request = parse_request(raw_query, **options)
    identities, quarantined = _identity_inputs(request)
    return {
        "entities": [to_dict(identity) for identity in identities],
        "quarantined": [to_dict(value) for value in quarantined],
        "sources": list(request.sources),
        "public_only": request.public_only,
        "consent": request.consent,
        "dimensions": list(request.dimensions),
        "horizon_months": request.horizon_months,
    }


def research(raw_query: str | Mapping[str, Any] | StartupRequest, **options: Any) -> StartupRun:
    request = parse_request(raw_query, **options)
    identities, quarantined = _identity_inputs(request)
    if len(identities) > request.budgets.max_entities:
        raise ValueError(f"entity budget exceeded: {len(identities)} > {request.budgets.max_entities}")
    if request.public_only:
        # Keep explicitly requested gated sources in the per-entity ledger as
        # attempted=False outcomes; the retrieval bridge will not activate
        # them. This makes the limitation visible without losing entity shape.
        active_sources = list(request.sources)
        skipped = [source for source in request.sources if not resolve_source(source).public]
    else:
        active_sources = list(request.sources)
        skipped = []
    warnings: list[str] = []
    if skipped:
        warnings.append("gated sources skipped by public-only mode: " + ", ".join(skipped))
    contract = {
        "profile_horizon_months": request.horizon_months,
        "public_only": request.public_only,
        "consent_required_for_gated": True,
        "dimensions": list(request.dimensions),
        "source_plan": list(request.sources),
    }
    results = retrieve_group(identities, active_sources, config=request.config, public_only=request.public_only,
                             consent=request.consent, mock=request.mock, depth=request.depth,
                             budgets=request.budgets, adapter_kwargs=request.adapter_kwargs)
    profiles = [extract_profile(identity, result.items, dimensions=request.dimensions,
                                horizon_months=request.horizon_months)
                for identity, result in zip(identities, results)]
    return StartupRun(request=request, retrieval=StartupRetrievalResult(
        entities=results, quarantined=quarantined, requested_sources=list(request.sources),
        source_plan={identity.entity_id: list(active_sources) for identity in identities}, warnings=warnings,
    ), contract=contract, profiles=profiles)


def research_and_save(raw_query: str | Mapping[str, Any] | StartupRequest, **options: Any) -> tuple[StartupRun, Any]:
    save_options = {key: options.pop(key) for key in tuple(options) if key in {"save_dir", "emit", "private", "include_private_evidence"}}
    run_result = research(raw_query, **options)
    return run_result, run_result.save(**save_options)


run = research
run_startup_goat = research
# Friendly names for host integrations that distinguish this contract from
# the generic engine's query/report types.
StartupGoatRequest = StartupRequest
StartupGoatResult = StartupRun

__all__ = ["DEFAULT_STARTUP_SOURCES", "StartupGoatRequest", "StartupGoatResult", "StartupRequest", "StartupRun", "build_source_plan", "parse_request", "research", "research_and_save", "run", "run_startup_goat"]
