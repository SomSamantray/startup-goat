from dataclasses import replace

import pytest

from lib.schema import SourceItem, SourceOutcome
from lib.startup_evidence import (
    EvidenceLedger,
    EvidenceRecord,
    evidence_from_dict,
    group_conflicts,
)


def item(**kwargs):
    values = dict(item_id="i1", source="startup-india", title="Acme", body="DPIIT recognised", url="https://startupindia.gov.in/acme")
    values.update(kwargs)
    return SourceItem(**values)


def test_source_item_projects_to_reference_and_serializes():
    record = EvidenceRecord.from_source_item(item(), entity_id="startup_acme", claim_type="recognition", field_type="dpiit_status")
    payload = record.to_dict()
    assert payload["item_id"] == "i1"
    assert payload["entity_id"] == "startup_acme"
    assert payload["content_hash"]
    assert "body" not in payload
    assert evidence_from_dict(payload) == record
    assert record.reference().item_id == "i1"


def test_access_states_are_validated_without_changing_generic_outcomes():
    record = EvidenceRecord.from_source_item(
        item(), entity_id="e", claim_type="funding", field_type="amount",
        access_state="paywalled", access_mode="browser-capture",
    )
    assert record.access_state == "paywalled"
    assert SourceOutcome(source="x", state="no-results").state == "no-results"
    with pytest.raises(ValueError):
        replace(record, access_state="auth-failed")


def test_entity_binding_and_conflicts_preserve_both_citations():
    first = EvidenceRecord.from_source_item(item(item_id="one", body="₹10 crore"), entity_id="e", claim_type="funding", field_type="funding")
    second = EvidenceRecord.from_source_item(item(item_id="two", body="₹20 crore"), entity_id="e", claim_type="funding", field_type="funding")
    grouped = group_conflicts([first, second], {first.evidence_id: 10, second.evidence_id: 20})
    assert len(grouped) == 2
    assert grouped[0].conflict_group and grouped[0].conflict_group == grouped[1].conflict_group
    assert {record.item_id for record in grouped} == {"one", "two"}


def test_ledger_keeps_typed_facts_and_rejects_secret_like_content():
    ledger = EvidenceLedger()
    ledger.add_item(item(), entity_id="e", claim_type="profile", field_type="name")
    assert ledger.to_dict()["records"][0]["item_id"] == "i1"
    with pytest.raises(ValueError, match="secret-like"):
        EvidenceRecord.from_source_item(item(body="Authorization: Bearer abcdefghijklmnop"), entity_id="e", claim_type="x", field_type="x")
    with pytest.raises(ValueError, match="secret-like"):
        EvidenceRecord.from_source_item(item(metadata={"Cookie": "session=private"}), entity_id="e", claim_type="x", field_type="x")
