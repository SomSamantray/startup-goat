from types import SimpleNamespace

import pytest

from lib.schema import SourceItem, SourceOutcome
from lib.startup_goat import parse_request, research
from lib.startup_pipeline import StartupBudgets


def _fake_report(topic, **kwargs):
    source = kwargs["requested_sources"][0]
    item = SourceItem(
        item_id=f"{source}-{topic}", source=source, title=f"{topic} evidence",
        body="public evidence", url=f"https://example.test/{topic.lower()}",
        metadata={},
    )
    return SimpleNamespace(
        items_by_source={source: [item]}, ranked_candidates=[],
        source_status={source: SourceOutcome(source, "ok", items_returned=1)},
        errors_by_source={},
    )


def test_single_company_routes_alias_and_binds_entity(monkeypatch):
    from lib.startup_pipeline import generic_pipeline
    seen = {}
    def run(topic, **kwargs):
        seen.update(kwargs)
        return _fake_report(topic, **kwargs)
    monkeypatch.setattr(generic_pipeline, "run", run)
    result = research("Research Acme", sources=["twitter"], config={"AUTH_TOKEN": "dummy", "CT0": "dummy"}, mock=True)
    assert seen["config"]["AUTH_TOKEN"] == "dummy"
    assert seen["config"]["CT0"] == "dummy"
    assert [item.source for item in result.entities[0].items] == ["x"]
    assert result.entities[0].items[0].metadata["entity_id"] == result.entities[0].identity.entity_id
    assert result.entities[0].outcomes["x"].state == "ok"


def test_group_order_and_failure_isolation(monkeypatch):
    from lib.startup_pipeline import generic_pipeline
    def run(topic, **kwargs):
        if topic == "Broken":
            raise RuntimeError("boom")
        return _fake_report(topic, **kwargs)
    monkeypatch.setattr(generic_pipeline, "run", run)
    result = research({"query": "Acme vs Broken", "sources": ["github"]}, mock=True)
    assert [r.identity.display_name for r in result.entities] == ["Acme", "Broken"]
    assert result.entities[0].items
    assert result.entities[1].errors == ["github: retrieval failed"]


def test_unresolved_entity_is_quarantined_without_fanout(monkeypatch):
    from lib.startup_pipeline import generic_pipeline
    called = []
    monkeypatch.setattr(generic_pipeline, "run", lambda *a, **k: called.append(1) or _fake_report("Acme", **k))
    result = research({"query": "Acme", "entities": ["Acme", "unknown"], "sources": ["github"]}, mock=True)
    assert len(result.entities) == 1
    assert result.quarantined[0].reason
    assert len(called) == 1


def test_public_only_never_activates_authorized_source():
    result = research("Acme", sources=["linkedin"], public_only=True)
    assert len(result.entities) == 1
    assert result.entities[0].outcomes["linkedin"].state == "skipped-unconfigured"
    assert result.retrieval.requested_sources == ["linkedin"]
    assert result.retrieval.warnings


def test_gated_source_requires_consent_and_capability():
    result = research("Acme", sources=["linkedin"], public_only=False, consent=True)
    assert result.entities[0].outcomes["linkedin"].state == "skipped-unconfigured"


def test_linkedin_cookie_capability_activates_adapter(monkeypatch):
    """A cookie-capable, consented run reaches the adapter with the cookies."""
    from lib import startup_pipeline
    from lib.linkedin_cookie import LinkedInCookieAdapter

    seen = {}

    def fake_fetch(self, *, entity_id, query, **kwargs):
        seen["entity_id"] = entity_id
        seen["cookies"] = kwargs.get("cookies")
        seen["slug"] = kwargs.get("slug")
        from lib.startup_public_base import AdapterResult, item, outcome
        ev = item("linkedin", entity_id, url="https://www.linkedin.com/company/acme",
                  title="Acme", body="profile", claim_type="company-profile")
        return AdapterResult([ev], outcome("linkedin", "ok", items=1), {"entity_id": entity_id})

    monkeypatch.setattr(LinkedInCookieAdapter, "fetch", fake_fetch)
    result = research(
        {"query": "Acme", "companies": ["Acme"], "sources": ["linkedin"]},
        public_only=False, consent=True,
        adapter_kwargs={"cookies": {"li_at": "dummy-li-at", "JSESSIONID": "ajax:1", "bcookie": "b"}},
    )
    assert seen["cookies"]["li_at"] == "dummy-li-at"
    assert result.entities[0].outcomes["linkedin"].state == "ok"
    # The cookie values never leak into the pipeline context or outcome.
    assert "dummy-li-at" not in repr(result.entities[0].outcomes)
    assert "dummy-li-at" not in repr(result.to_dict())


def test_linkedin_handle_threaded_as_slug(monkeypatch):
    """A user-supplied linkedin.com/company/<slug> handle becomes the slug."""
    from lib.linkedin_cookie import LinkedInCookieAdapter

    seen = {}

    def fake_fetch(self, *, entity_id, query, **kwargs):
        seen["slug"] = kwargs.get("slug")
        from lib.startup_public_base import AdapterResult, item, outcome
        ev = item("linkedin", entity_id, url="https://www.linkedin.com/company/inc42",
                  title="Inc42 Media", body="profile", claim_type="company-profile")
        return AdapterResult([ev], outcome("linkedin", "ok", items=1), {"entity_id": entity_id})

    monkeypatch.setattr(LinkedInCookieAdapter, "fetch", fake_fetch)
    result = research(
        {"query": "Inc42 Media", "companies": [{"display_name": "Inc42 Media", "handles": ["linkedin.com/company/inc42"]}], "sources": ["linkedin"]},
        public_only=False, consent=True,
        adapter_kwargs={"cookies": {"li_at": "dummy-li-at"}},
    )
    assert seen["slug"] == "inc42"
    assert result.entities[0].outcomes["linkedin"].state == "ok"


def test_linkedin_token_only_run_selects_token_adapter(monkeypatch):
    """A LINKEDIN_ACCESS_TOKEN-only run must not be silently skipped: the
    factory routes it to the OAuth adapter."""
    from lib import startup_sources
    from lib.linkedin_token import LinkedInTokenAdapter

    seen = {}

    def fake_fetch(self, *, entity_id, query, **kwargs):
        seen["called"] = True
        seen["token"] = kwargs.get("token")
        from lib.startup_public_base import AdapterResult, item, outcome
        ev = item("linkedin", entity_id, url="https://api.linkedin.com/v2/organizations/x",
                  title="Acme", body="profile", claim_type="company-profile")
        return AdapterResult([ev], outcome("linkedin", "ok", items=1), {"entity_id": entity_id})

    monkeypatch.setattr(LinkedInTokenAdapter, "fetch", fake_fetch)
    result = research(
        {"query": "Acme", "companies": ["Acme"], "sources": ["linkedin"]},
        public_only=False, consent=True,
        adapter_kwargs={"token": "dummy-bearer"},
    )
    assert seen["called"] is True
    assert result.entities[0].outcomes["linkedin"].state == "ok"


def test_linkedin_env_cookie_run_activates_cookie_adapter(monkeypatch):
    """The README-documented `export LINKEDIN_LI_AT` flow reaches the cookie
    adapter via the env-presence capability signal."""
    from lib.linkedin_cookie import LinkedInCookieAdapter

    seen = {}

    def fake_fetch(self, *, entity_id, query, **kwargs):
        seen["called"] = True
        from lib.startup_public_base import AdapterResult, item, outcome
        ev = item("linkedin", entity_id, url="https://www.linkedin.com/company/acme",
                  title="Acme", body="profile", claim_type="company-profile")
        return AdapterResult([ev], outcome("linkedin", "ok", items=1), {"entity_id": entity_id})

    monkeypatch.setattr(LinkedInCookieAdapter, "fetch", fake_fetch)
    monkeypatch.setenv("LINKEDIN_LI_AT", "env-li-at")
    result = research(
        {"query": "Acme", "companies": ["Acme"], "sources": ["linkedin"]},
        public_only=False, consent=True,
    )
    assert seen["called"] is True
    assert result.entities[0].outcomes["linkedin"].state == "ok"


def test_linkedin_posts_survive_pipeline_binding(monkeypatch):
    """Post items emitted by the adapter are bound to the entity and reach the
    result (regression: posts were dropped when entity_id was empty)."""
    from lib.linkedin_cookie import LinkedInCookieAdapter

    def fake_fetch(self, *, entity_id, query, **kwargs):
        from lib.startup_public_base import AdapterResult, item, outcome
        ev = item("linkedin", entity_id, url="https://www.linkedin.com/company/acme",
                  title="Acme", body="profile", claim_type="company-profile")
        post = item("linkedin", entity_id, url="", title="A post", body="post body",
                    claim_type="post")
        return AdapterResult([ev, post], outcome("linkedin", "ok", items=2), {"entity_id": entity_id})

    monkeypatch.setattr(LinkedInCookieAdapter, "fetch", fake_fetch)
    result = research(
        {"query": "Acme", "companies": ["Acme"], "sources": ["linkedin"]},
        public_only=False, consent=True,
        adapter_kwargs={"cookies": {"li_at": "dummy-li-at"}},
    )
    items = result.entities[0].items
    claim_types = {it.metadata.get("claim_type") for it in items}
    assert "post" in claim_types
    assert result.entities[0].outcomes["linkedin"].items_returned == 2


def test_budget_validation_and_declarative_options():
    with pytest.raises(ValueError):
        parse_request("Acme", budgets={"max_entities": 0})
    with pytest.raises(ValueError):
        parse_request("Acme", unknown=True)
    request = parse_request({"query": "Acme", "companies": ["Acme"], "sources": "gh", "depth": "brief"})
    assert request.sources == ("github",)
    assert request.depth == "brief"
    with pytest.raises(ValueError):
        parse_request("Acme", public_only=True, consent=True)


def test_entity_cap_is_enforced_before_fanout():
    with pytest.raises(ValueError):
        research({"query": "A vs B vs C", "sources": ["github"]}, budgets={"max_entities": 2})
