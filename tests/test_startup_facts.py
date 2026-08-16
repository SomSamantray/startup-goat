from lib.schema import SourceItem
from lib.startup_facts import extract_profile
from lib.startup_identity import build_identity
from lib.startup_public_base import item


def _identity(name="Acme"):
    return build_identity(name, state="resolved", confidence="high")


def test_extracts_only_explicit_entity_bound_fields_and_preserves_dates():
    identity = _identity()
    source = item("startup-india", identity.entity_id, url="https://startupindia.gov.in/a", title="Acme", published_at="2025-01-02", body="DPIIT recognized: yes\nThis prose must not become a fact.", metadata={"structured_facts": {"dpiit_recognized": "yes", "stage": "seed"}})
    profile = extract_profile(identity, [source])
    assert {fact.field for fact in profile.facts} == {"dpiit_recognized", "stage"}
    assert all(fact.entity_id == identity.entity_id for fact in profile.facts)
    assert any(fact.published_at == "2025-01-02" for fact in profile.facts)
    assert "prose" not in {fact.field for fact in profile.facts}


def test_authority_marks_conflicting_values_and_keeps_both_citations():
    identity = _identity()
    public = item("yourstory", identity.entity_id, url="https://yourstory.com/a", title="Funding", metadata={"structured_facts": {"funding": "INR 10 crore"}})
    filing = item("screener", identity.entity_id, url="https://screener.in/company/ACME", title="Filing", published_at="2025-02-01", metadata={"structured_facts": {"funding": "INR 20 crore"}})
    profile = extract_profile(identity, [public, filing])
    assert len(profile.conflicts) == 1
    assert set(profile.conflicts[0].values) == {"INR 10 crore", "INR 20 crore"}
    assert all(fact.conflict_group for fact in profile.facts)
    assert profile.conflicts[0].selected_evidence_id in {ref.evidence_id for ref in profile.evidence}


def test_cross_entity_items_are_quarantined_from_profile():
    first, second = _identity("Alpha"), _identity("Beta")
    leaked = item("yourstory", second.entity_id, url="https://yourstory.com/b", title="Beta", metadata={"structured_facts": {"product": "Beta product"}})
    profile = extract_profile(first, [leaked])
    assert profile.facts == []
    assert profile.evidence == []


def test_failure_text_is_not_a_company_fact():
    identity = _identity()
    failed = item("the-ken", identity.entity_id, url="https://the-ken.com/a", title="Access limitation", body="No results: login required", metadata={"claim_type": "access-limitation", "access_state": "paywalled"})
    assert extract_profile(identity, [failed]).facts == []
