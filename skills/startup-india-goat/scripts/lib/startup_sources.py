"""The sole composition root for Startup India GOAT sources.

This module owns source names, aliases, capability metadata, budgets, and hook
interfaces.  Concrete adapters are added in later units and are injected here;
this registry intentionally has no imports from adapters or the entrypoint.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from .schema import SourceItem, SourceOutcome

SourceClass = Literal["public", "authorized", "gated"]


class StartupAdapter(Protocol):
    """Minimum interface every startup adapter must expose."""

    def fetch(self, *, entity_id: str, query: str = "", **kwargs: Any) -> Any: ...


ParserHook = Callable[[Any], list[SourceItem]]
NormalizerHook = Callable[[SourceItem], SourceItem]
OutcomeHook = Callable[[SourceOutcome], SourceOutcome]
CapabilityPredicate = Callable[[Mapping[str, Any]], bool]
AdapterFactory = Callable[[], StartupAdapter]


def _identity_parse(value: Any) -> list[SourceItem]:
    return value if isinstance(value, list) else []


def _identity_normalize(item: SourceItem) -> SourceItem:
    return item


def _identity_outcome(outcome: SourceOutcome) -> SourceOutcome:
    return outcome


class UnimplementedStartupAdapter:
    """Validated placeholder until a source-specific adapter is registered."""

    def fetch(self, *, entity_id: str, query: str = "", **kwargs: Any) -> Any:
        raise NotImplementedError("startup source adapter is not implemented yet")


def _placeholder_factory() -> StartupAdapter:
    return UnimplementedStartupAdapter()


def _yourstory_factory() -> StartupAdapter:
    from .yourstory import YourStoryAdapter
    return YourStoryAdapter()


def _startup_india_factory() -> StartupAdapter:
    from .startup_india import StartupIndiaAdapter
    return StartupIndiaAdapter()


def _screener_factory() -> StartupAdapter:
    from .screener import ScreenerAdapter
    return ScreenerAdapter()


def _inc42_factory() -> StartupAdapter:
    from .inc42 import Inc42Adapter
    return Inc42Adapter()


def _the_ken_factory() -> StartupAdapter:
    from .the_ken import TheKenAdapter
    return TheKenAdapter()


@dataclass(frozen=True)
class FetchBudget:
    """Hard upper bounds supplied to a source adapter."""

    max_requests: int = 1
    max_pages: int = 1
    timeout_seconds: float = 15.0
    max_items: int = 100

    def __post_init__(self) -> None:
        if self.max_requests < 1 or self.max_pages < 1 or self.max_items < 1:
            raise ValueError("source fetch budgets must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("source timeout budget must be positive")


@dataclass(frozen=True)
class SourceCapability:
    """Validated registration metadata for one canonical source."""

    canonical_name: str
    aliases: tuple[str, ...]
    capability_predicate: CapabilityPredicate
    fetch_budget: FetchBudget
    parser: ParserHook = _identity_parse
    normalizer: NormalizerHook = _identity_normalize
    outcome_mapper: OutcomeHook = _identity_outcome
    adapter_factory: AdapterFactory = _placeholder_factory
    source_class: SourceClass = "public"
    # Public/gated is explicit metadata, not inferred from the adapter.
    public: bool = True
    requires_consent: bool = False
    required_context_keys: tuple[str, ...] = ()
    source_tier: str = "secondary"

    def __post_init__(self) -> None:
        if not self.canonical_name or self.canonical_name != self.canonical_name.casefold():
            raise ValueError("canonical source names must be non-empty lowercase")
        if not self.aliases or self.canonical_name not in self.aliases:
            raise ValueError("aliases must include canonical source name")
        if self.source_class not in {"public", "authorized", "gated"}:
            raise ValueError(f"unknown source class: {self.source_class}")
        if self.public != (self.source_class == "public"):
            raise ValueError("public flag must match source_class")
        if self.source_class == "public" and self.requires_consent:
            raise ValueError("public sources cannot require consent")
        if not callable(self.capability_predicate) or not callable(self.parser):
            raise ValueError("source hooks must be callable")
        if not callable(self.normalizer) or not callable(self.outcome_mapper) or not callable(self.adapter_factory):
            raise ValueError("source hooks must be callable")

    @property
    def gated(self) -> bool:
        return not self.public

    def is_capable(self, context: Mapping[str, Any] | None = None) -> bool:
        values = context or {}
        if any(not values.get(key) for key in self.required_context_keys):
            return False
        return bool(self.capability_predicate(values))


def _always(_: Mapping[str, Any]) -> bool:
    return True


def _has_linkedin_token(context: Mapping[str, Any]) -> bool:
    return bool(context.get("LINKEDIN_ACCESS_TOKEN"))


def _has_tracxn_access(context: Mapping[str, Any]) -> bool:
    return bool(context.get("TRACXN_ACCESS_TOKEN") or context.get("browser_consent"))


def _registration(
    name: str,
    aliases: tuple[str, ...],
    *,
    source_class: SourceClass = "public",
    predicate: CapabilityPredicate = _always,
    budget: FetchBudget = FetchBudget(),
    source_tier: str = "secondary",
    required_context_keys: tuple[str, ...] = (),
    requires_consent: bool = False,
    adapter_factory: AdapterFactory = _placeholder_factory,
) -> SourceCapability:
    return SourceCapability(
        canonical_name=name,
        aliases=aliases,
        capability_predicate=predicate,
        fetch_budget=budget,
        source_class=source_class,
        public=source_class == "public",
        requires_consent=requires_consent,
        required_context_keys=required_context_keys,
        source_tier=source_tier,
        adapter_factory=adapter_factory,
    )


# Keep aliases stable: planners and saved reports may contain them.
DEFAULT_SOURCE_REGISTRY: tuple[SourceCapability, ...] = (
    _registration("github", ("github", "gh"), source_tier="primary"),
    _registration("x", ("x", "twitter"), source_tier="social"),
    _registration("reddit", ("reddit",), source_tier="social"),
    _registration("youtube", ("youtube", "yt"), source_tier="social"),
    _registration("web", ("web", "web-search"), source_tier="secondary"),
    _registration(
        "linkedin", ("linkedin", "linkedin-token", "linkedin_token"), source_class="authorized",
        predicate=_has_linkedin_token, required_context_keys=("LINKEDIN_ACCESS_TOKEN",),
        requires_consent=True, source_tier="primary",
    ),
    _registration("yourstory", ("yourstory", "your-story"), source_tier="secondary", adapter_factory=_yourstory_factory),
    _registration("screener", ("screener", "screener.in"), source_tier="authoritative", adapter_factory=_screener_factory),
    _registration("the-ken", ("the-ken", "the_ken", "the ken", "ken"), source_tier="secondary", adapter_factory=_the_ken_factory),
    _registration("inc42", ("inc42", "inc 42"), source_tier="secondary", adapter_factory=_inc42_factory),
    _registration("startup-india", ("startup-india", "startup_india", "startup india", "dpiit"), source_tier="authoritative", adapter_factory=_startup_india_factory),
    _registration(
        "tracxn", ("tracxn",), source_class="authorized", predicate=_has_tracxn_access,
        requires_consent=True, source_tier="commercial",
    ),
)


def validate_registry(registry: tuple[SourceCapability, ...] | list[SourceCapability]) -> None:
    """Fail closed on duplicate names, aliases, or unreachable hooks."""
    names: set[str] = set()
    aliases: dict[str, str] = {}
    for capability in registry:
        if capability.canonical_name in names:
            raise ValueError(f"duplicate source: {capability.canonical_name}")
        names.add(capability.canonical_name)
        # Calling the factory validates the common adapter protocol without
        # importing concrete adapters or making a network request.
        adapter = capability.adapter_factory()
        if not callable(getattr(adapter, "fetch", None)):
            raise ValueError(f"adapter for {capability.canonical_name} lacks fetch()")
        for alias in capability.aliases:
            key = alias.casefold().strip()
            if not key:
                raise ValueError("source aliases must not be empty")
            previous = aliases.get(key)
            if previous and previous != capability.canonical_name:
                raise ValueError(f"alias {alias!r} maps to multiple sources")
            aliases[key] = capability.canonical_name


validate_registry(DEFAULT_SOURCE_REGISTRY)


def source_registry() -> tuple[SourceCapability, ...]:
    return DEFAULT_SOURCE_REGISTRY


def resolve_source(name: str, registry: tuple[SourceCapability, ...] = DEFAULT_SOURCE_REGISTRY) -> SourceCapability:
    key = name.casefold().strip()
    for capability in registry:
        if key in {alias.casefold() for alias in capability.aliases}:
            return capability
    raise KeyError(f"unknown startup source: {name}")


# Friendly aliases for callers and contract tests.
get_source = resolve_source
get_source_registry = source_registry


__all__ = [
    "AdapterFactory", "CapabilityPredicate", "DEFAULT_SOURCE_REGISTRY", "FetchBudget",
    "SourceCapability", "StartupAdapter", "get_source", "get_source_registry",
    "resolve_source", "source_registry", "validate_registry",
]
