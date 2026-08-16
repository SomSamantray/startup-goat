import pytest

from lib.schema import SourceOutcome
from lib.startup_sources import (
    DEFAULT_SOURCE_REGISTRY,
    FetchBudget,
    get_source,
    validate_registry,
)


def test_registry_is_complete_and_aliases_resolve():
    names = {source.canonical_name for source in DEFAULT_SOURCE_REGISTRY}
    assert {"github", "x", "reddit", "youtube", "web", "linkedin", "yourstory", "screener", "the-ken", "inc42", "startup-india", "tracxn"} <= names
    assert get_source("twitter").canonical_name == "x"
    assert get_source("startup india").canonical_name == "startup-india"
    assert get_source("the ken").canonical_name == "the-ken"


def test_registry_has_budgets_hooks_and_validated_adapter_interface():
    validate_registry(DEFAULT_SOURCE_REGISTRY)
    for source in DEFAULT_SOURCE_REGISTRY:
        assert source.fetch_budget.max_requests > 0
        assert callable(source.parser)
        assert callable(source.normalizer)
        assert callable(source.outcome_mapper)
        assert callable(source.adapter_factory)
        assert callable(source.adapter_factory().fetch)
    assert get_source("linkedin").is_capable({"LINKEDIN_ACCESS_TOKEN": "dummy"})
    assert not get_source("linkedin").is_capable({})
    assert get_source("tracxn").gated


def test_registry_rejects_duplicate_aliases_and_bad_budget():
    with pytest.raises(ValueError):
        FetchBudget(max_requests=0)
    first = DEFAULT_SOURCE_REGISTRY[0]
    with pytest.raises(ValueError):
        validate_registry([first, first])
    assert SourceOutcome(source="s", state="no-results").state == "no-results"
