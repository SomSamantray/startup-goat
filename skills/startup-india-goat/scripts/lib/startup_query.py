"""Small, deterministic query helpers for the startup planner boundary."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .startup_identity import build_group_identities
from .startup_schema import QueryDimensions, StartupQuery

DEFAULT_DIMENSIONS = (
    "product",
    "market",
    "traction",
    "capital",
    "team",
    "distribution",
    "business_model",
    "risks",
)


def normalize_dimensions(values: Iterable[str] | None) -> tuple[str, ...]:
    """Normalize ordered dimensions while retaining the user's first occurrence."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        key = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return tuple(result)


def make_query(
    raw_query: str,
    *,
    entities: Iterable[dict] = (),
    dimensions: Iterable[str] | None = None,
    audience: str | None = None,
    depth: str = "standard",
    horizon_months: int = 24,
    comparison: bool | None = None,
) -> StartupQuery:
    """Build a query envelope without attempting fuzzy identity resolution."""
    identities = tuple(build_group_identities(entities, query=raw_query))
    selected = normalize_dimensions(dimensions)
    if not selected:
        selected = DEFAULT_DIMENSIONS
    is_comparison = len(identities) > 1 if comparison is None else comparison
    return StartupQuery(
        raw_query=raw_query,
        entities=identities,
        dimensions=QueryDimensions(
            values=selected,
            audience=audience,
            depth=depth,  # type: ignore[arg-type]
            horizon_months=horizon_months,
        ),
        comparison=is_comparison,
    )


__all__ = ["DEFAULT_DIMENSIONS", "make_query", "normalize_dimensions"]
