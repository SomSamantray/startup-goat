from __future__ import annotations

import json

import pytest

from lib.startup_identity import build_identity
from lib.startup_schema import (
    EvidenceReference,
    GroupProfile,
    QueryDimensions,
    StartupFact,
    StartupProfile,
    StartupQuery,
    to_dict,
)


def test_profile_keeps_entity_binding_and_dated_facts() -> None:
    identity = build_identity("Acme", state="resolved", confidence="high")
    profile = StartupProfile(
        identity=identity,
        facts=[
            StartupFact(
                entity_id=identity.entity_id,
                field="funding.total",
                value=42,
                evidence_refs=[EvidenceReference("ev-1", item_id="item-1")],
                confidence="medium",
                as_of_date="2026-01-01",
                is_evergreen=False,
            )
        ],
    )
    payload = to_dict(profile)
    assert payload["identity"]["entity_id"] == identity.entity_id
    assert payload["facts"][0]["evidence_refs"][0]["item_id"] == "item-1"
    json.dumps(payload)


def test_profile_rejects_cross_entity_fact_and_ambiguous_comparison() -> None:
    first = build_identity("Acme", state="resolved", confidence="high")
    second = build_identity("Other", state="resolved", confidence="high")
    with pytest.raises(ValueError):
        StartupProfile(identity=first, facts=[StartupFact(entity_id=second.entity_id, field="x", value=1)])
    with pytest.raises(ValueError):
        StartupQuery(raw_query="compare", entities=(first,), comparison=True)


def test_group_profile_preserves_order_and_rejects_duplicate_ids() -> None:
    first = StartupProfile(build_identity("First", domains=["first.example"]))
    second = StartupProfile(build_identity("Second", domains=["second.example"]))
    group = GroupProfile(profiles=[first, second], query="First vs Second")
    assert group.entity_ids == [first.identity.entity_id, second.identity.entity_id]
    with pytest.raises(ValueError):
        GroupProfile(profiles=[first, StartupProfile(first.identity)])


def test_query_dimensions_are_unique_and_horizon_is_explicit() -> None:
    assert QueryDimensions(values=("traction",), horizon_months=24).horizon_months == 24
    with pytest.raises(ValueError):
        QueryDimensions(values=("traction", "traction"))
    with pytest.raises(ValueError):
        StartupFact(entity_id="id", field="event", value="x", is_evergreen=False)
