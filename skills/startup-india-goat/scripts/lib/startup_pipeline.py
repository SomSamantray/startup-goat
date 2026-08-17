"""Bounded retrieval bridge for Startup India GOAT.

The generic last30days pipeline remains the owner of GitHub, Reddit, X,
YouTube, and web retrieval.  This module only translates its report-shaped
output into entity-bound startup evidence and dispatches startup adapters.
"""
from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from . import pipeline as generic_pipeline
from .schema import SourceItem, SourceOutcome
from .startup_schema import StartupIdentity
from .startup_public_base import AdapterResult, outcome
from .env import read_secret_env
from .linkedin_cookie import LinkedInCookieAdapter
from .startup_sources import SourceCapability, resolve_source

GENERIC_SOURCES = frozenset({"github", "reddit", "x", "youtube", "web"})
WEB_BRIDGE_NAME = "grounding"


@dataclass(frozen=True)
class StartupBudgets:
    max_entities: int = 6
    max_sources_per_entity: int = 12
    max_items_per_source: int = 100
    max_concurrency: int = 4
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_entities < 1 or self.max_sources_per_entity < 1 or self.max_items_per_source < 1:
            raise ValueError("startup budgets must have positive caps")
        if self.max_concurrency < 1 or self.timeout_seconds <= 0:
            raise ValueError("startup concurrency and timeout must be positive")


@dataclass
class StartupEntityResult:
    identity: StartupIdentity
    items: list[SourceItem] = field(default_factory=list)
    outcomes: dict[str, SourceOutcome] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def partial(self) -> bool:
        return bool(self.errors) or any(value.state not in {"ok", "no-results"} for value in self.outcomes.values())


@dataclass
class StartupRetrievalResult:
    entities: list[StartupEntityResult] = field(default_factory=list)
    quarantined: list[Any] = field(default_factory=list)
    requested_sources: list[str] = field(default_factory=list)
    source_plan: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.entities) and not self.quarantined and all(not entity.partial for entity in self.entities)


def _generic_items(report: Any, entity_id: str, source: str, limit: int) -> list[SourceItem]:
    """Extract and entity-bind generic evidence without mutating the report."""
    pools: list[SourceItem] = []
    by_source = getattr(report, "items_by_source", {}) or {}
    pools.extend(by_source.get(source, []))
    # The web alias is implemented by the generic grounding source.
    if source == "web":
        pools.extend(by_source.get(WEB_BRIDGE_NAME, []))
    if not pools:
        allowed_sources = {source, WEB_BRIDGE_NAME} if source == "web" else {source}
        for candidate in getattr(report, "ranked_candidates", []) or []:
            pools.extend(
                item for item in (getattr(candidate, "source_items", []) or [])
                if isinstance(item, SourceItem) and item.source in allowed_sources
            )
    result: list[SourceItem] = []
    seen: set[tuple[str, str]] = set()
    for original in pools:
        if not isinstance(original, SourceItem):
            continue
        item = copy.deepcopy(original)
        metadata = dict(item.metadata or {})
        existing = metadata.get("entity_id")
        if existing not in (None, entity_id):
            # Never allow a reused/cached item from another entity through.
            continue
        metadata["entity_id"] = entity_id
        metadata["startup_source"] = source
        item.source = source
        item.metadata = metadata
        key = (item.item_id, item.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _report_outcome(report: Any, source: str, item_count: int) -> SourceOutcome:
    statuses = getattr(report, "source_status", {}) or {}
    candidate = statuses.get(source) or statuses.get(WEB_BRIDGE_NAME if source == "web" else source)
    if isinstance(candidate, SourceOutcome):
        copied = copy.deepcopy(candidate)
        copied.source = source
        copied.items_returned = item_count
        return copied
    if item_count:
        return SourceOutcome(source=source, state="ok", items_returned=item_count)
    errors = getattr(report, "errors_by_source", {}) or {}
    if source in errors or (source == "web" and WEB_BRIDGE_NAME in errors):
        return SourceOutcome(source=source, state="partial", items_returned=0, detail="generic retrieval reported a source failure")
    return SourceOutcome(source=source, state="no-results", items_returned=0)


def _adapter_result(value: Any, source: str, entity_id: str) -> AdapterResult:
    if isinstance(value, AdapterResult):
        return value
    if isinstance(value, list):
        return AdapterResult(value, outcome(source, "ok" if value else "no-results", items=len(value)), {"entity_id": entity_id})
    return AdapterResult([], outcome(source, "schema-drift", detail="adapter returned unsupported result"), {"entity_id": entity_id})


def _bind_adapter_items(result: AdapterResult, identity: StartupIdentity, source: str, limit: int) -> list[SourceItem]:
    items: list[SourceItem] = []
    for original in result.items[:limit]:
        if not isinstance(original, SourceItem) or original.source != source:
            continue
        item = copy.deepcopy(original)
        metadata = dict(item.metadata or {})
        existing = metadata.get("entity_id")
        if existing not in (None, identity.entity_id):
            continue
        metadata["entity_id"] = identity.entity_id
        metadata["startup_source"] = source
        item.metadata = metadata
        items.append(item)
    return items


def _linkedin_slug(handles: list[str]) -> str | None:
    """Return a LinkedIn company slug candidate from an identity's handles.

    Handles are stored bare (normalized), so the origin (which network the
    handle came from) is not recoverable here.  The adapter's ``_name_matches``
    guard rejects a wrong-company page, so a non-LinkedIn first handle fails
    closed as schema-drift rather than binding wrong evidence.
    """
    return handles[0] if handles else None


def _run_source(identity: StartupIdentity, capability: SourceCapability, *, config: Mapping[str, Any],
                public_only: bool, consent: bool, mock: bool, depth: str, budget: StartupBudgets,
                adapter_kwargs: Mapping[str, Any]) -> tuple[list[SourceItem], SourceOutcome, str | None]:
    source = capability.canonical_name
    started = time.monotonic()
    if capability.gated and (public_only or (capability.requires_consent and not consent)):
        return [], SourceOutcome(source=source, state="skipped-unconfigured", attempted=False, detail="gated source requires explicit consent"), None
    context = dict(config)
    context["consent"] = consent
    # Explicit per-run credentials/captures are capability signals, but are
    # never copied into result metadata or logs.
    if adapter_kwargs.get("token"):
        context["LINKEDIN_ACCESS_TOKEN"] = True
    if adapter_kwargs.get("cookies"):
        # Boolean capability signal only — cookie values stay in adapter_kwargs
        # and are read by the adapter for this call only.
        context["LINKEDIN_LI_AT"] = True
    if adapter_kwargs.get("browser_envelope") or adapter_kwargs.get("envelope") or adapter_kwargs.get("token_response"):
        context["browser_consent"] = bool(consent)
        context["TRACXN_ACCESS_TOKEN"] = True
    # Presence checks use only a boolean capability signal; the secret stays in
    # the environment and is read by the adapter for this call only.
    if source == "linkedin" and (read_secret_env("LINKEDIN_ACCESS_TOKEN") or read_secret_env("LINKEDIN_LI_AT")):
        if read_secret_env("LINKEDIN_ACCESS_TOKEN"):
            context["LINKEDIN_ACCESS_TOKEN"] = True
        if read_secret_env("LINKEDIN_LI_AT"):
            context["LINKEDIN_LI_AT"] = True
    if not capability.is_capable(context) and capability.source_class != "public":
        return [], SourceOutcome(source=source, state="skipped-unconfigured", attempted=False, detail="source capability is not configured"), None
    try:
        if source in GENERIC_SOURCES:
            requested = WEB_BRIDGE_NAME if source == "web" else source
            report = generic_pipeline.run(
                topic=identity.display_name,
                config=dict(config), depth=depth, requested_sources=[requested],
                mock=mock, internal_subrun=True,
            )
            items = _generic_items(report, identity.entity_id, source, budget.max_items_per_source)
            if time.monotonic() - started > budget.timeout_seconds:
                return [], SourceOutcome(source=source, state="timeout", detail="source timeout budget exceeded"), "timeout"
            return items, _report_outcome(report, source, len(items)), None
        if mock and not any(key in adapter_kwargs for key in ("fetcher", "url", "browser_envelope", "envelope", "token_response", "token", "cookies")):
            return [], SourceOutcome(source=source, state="no-results", attempted=False, detail="mock startup adapter has no fixture"), None
        adapter = capability.adapter_factory()
        # The factory dispatches on env credentials; an explicit cookies kwarg
        # (from adapter_kwargs) must select the cookie adapter even when no
        # LINKEDIN_LI_AT env var is set.
        if source == "linkedin" and adapter_kwargs.get("cookies") and not isinstance(adapter, LinkedInCookieAdapter):
            from .linkedin_cookie import LinkedInCookieAdapter as _CookieAdapter
            adapter = _CookieAdapter()
        call_kwargs = dict(adapter_kwargs)
        if source == "screener" and identity.tickers:
            call_kwargs.setdefault("ticker", identity.tickers[0])
        if source == "startup-india" and identity.dpiit_ids:
            call_kwargs.setdefault("profile_id", identity.dpiit_ids[0])
        if source == "linkedin" and identity.handles and "slug" not in call_kwargs:
            # A user-supplied linkedin.com/company/<slug> handle is the only
            # reliable slug source; display-name slugification is best-effort.
            call_kwargs["slug"] = _linkedin_slug(identity.handles)
        value = adapter.fetch(
            entity_id=identity.entity_id, query=identity.display_name,
            config=dict(config), timeout=budget.timeout_seconds, mock=mock, **call_kwargs,
        )
        result = _adapter_result(value, source, identity.entity_id)
        items = _bind_adapter_items(result, identity, source, budget.max_items_per_source)
        observed = copy.deepcopy(result.outcome or outcome(source, "ok" if items else "no-results", items=len(items)))
        observed.source = source
        observed.items_returned = len(items)
        if time.monotonic() - started > budget.timeout_seconds:
            return [], SourceOutcome(source=source, state="timeout", detail="source timeout budget exceeded"), "timeout"
        return items, observed, None
    except Exception as exc:
        return [], SourceOutcome(source=source, state="error", detail=f"source retrieval failed: {type(exc).__name__}"), str(exc)
    finally:
        # This is an observation hook for callers and tests; hard cancellation
        # of arbitrary third-party adapters is unsafe, so timeout is fail-closed
        # at the result boundary rather than a thread kill.
        _ = time.monotonic() - started


def retrieve_entity(identity: StartupIdentity, sources: Iterable[str], *, config: Mapping[str, Any] | None = None,
                    public_only: bool = True, consent: bool = False, mock: bool = False,
                    depth: str = "default", budgets: StartupBudgets | None = None,
                    adapter_kwargs: Mapping[str, Any] | None = None) -> StartupEntityResult:
    budgets = budgets or StartupBudgets()
    config = config or {}
    adapter_kwargs = adapter_kwargs or {}
    started = time.monotonic()
    result = StartupEntityResult(identity=identity)
    resolved: list[SourceCapability] = []
    for name in sources:
        capability = resolve_source(name)
        if capability.canonical_name not in {item.canonical_name for item in resolved}:
            resolved.append(capability)
    if len(resolved) > budgets.max_sources_per_entity:
        result.errors.append("source budget exceeded; remaining sources were not attempted")
        resolved = resolved[:budgets.max_sources_per_entity]
    # Source order is deterministic; parallel execution cannot change output
    # because results are installed by canonical source name.
    with ThreadPoolExecutor(max_workers=min(budgets.max_concurrency, max(1, len(resolved)))) as executor:
        futures = {
            executor.submit(_run_source, identity, capability, config=config,
                            public_only=public_only, consent=consent, mock=mock,
                            depth=depth, budget=budgets, adapter_kwargs=adapter_kwargs): capability
            for capability in resolved
        }
        completed: dict[str, tuple[list[SourceItem], SourceOutcome, str | None]] = {}
        for future in as_completed(futures):
            capability = futures[future]
            try:
                completed[capability.canonical_name] = future.result()
            except Exception as exc:  # defensive isolation around executor
                completed[capability.canonical_name] = ([], SourceOutcome(capability.canonical_name, "error", detail="source worker failed"), str(exc))
    for capability in resolved:
        items, observed, error = completed[capability.canonical_name]
        result.outcomes[capability.canonical_name] = observed
        result.items.extend(items)
        if error:
            result.errors.append(f"{capability.canonical_name}: retrieval failed")
    # Preserve source order and deduplicate only within this entity scope.
    result.items = _dedupe_entity(result.items, identity.entity_id)
    result.elapsed_seconds = time.monotonic() - started
    return result


def _dedupe_entity(items: Iterable[SourceItem], entity_id: str) -> list[SourceItem]:
    result: list[SourceItem] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if item.metadata.get("entity_id") != entity_id:
            continue
        key = (entity_id, item.source, item.url or item.item_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def retrieve_group(identities: Iterable[StartupIdentity], sources: Iterable[str], **kwargs: Any) -> list[StartupEntityResult]:
    ordered = list(identities)
    budgets: StartupBudgets = kwargs.pop("budgets", None) or StartupBudgets()
    if len(ordered) > budgets.max_entities:
        raise ValueError(f"entity budget exceeded: {len(ordered)} > {budgets.max_entities}")
    results: dict[str, StartupEntityResult] = {}
    with ThreadPoolExecutor(max_workers=min(budgets.max_concurrency, max(1, len(ordered)))) as executor:
        futures = {executor.submit(retrieve_entity, identity, sources, budgets=budgets, **kwargs): identity for identity in ordered}
        for future in as_completed(futures):
            identity = futures[future]
            try:
                results[identity.entity_id] = future.result()
            except Exception as exc:
                results[identity.entity_id] = StartupEntityResult(identity=identity, errors=["entity retrieval failed"])
    return [results[identity.entity_id] for identity in ordered]


run_entity = retrieve_entity
run_group = retrieve_group

__all__ = ["GENERIC_SOURCES", "StartupBudgets", "StartupEntityResult", "StartupRetrievalResult", "retrieve_entity", "retrieve_group", "run_entity", "run_group"]
