from __future__ import annotations

import json

import pytest

from lib.startup_identity import (
    build_group_identities,
    build_identity,
    normalize_domain,
    stable_entity_id,
    normalize_dpiit_id,
    normalize_handle,
    normalize_name,
    normalize_ticker,
    quarantine,
)
from lib.startup_schema import to_dict


def test_name_aliases_and_identifiers_normalize_deterministically() -> None:
    assert normalize_name("  Acme Technologies Pvt. Ltd. ") == "acme technologies"
    assert normalize_domain("https://WWW.Acme.in/products") == "acme.in"
    assert normalize_ticker("$ acme-1") == "ACME-1"
    assert normalize_handle("https://x.com/@Acme_India/") == "acme_india"
    assert normalize_dpiit_id("DPIIT / 123-45") == "DPIIT12345"

    first = build_identity("Acme Technologies Pvt. Ltd.", domains=["acme.in"])
    second = build_identity("ACME Technologies", domains=["https://acme.in"])
    assert first.entity_id == second.entity_id
    assert build_identity("Acme Technologies Pvt Ltd").entity_id == build_identity("Acme Technologies").entity_id
    assert stable_entity_id("Acme Technologies") == build_identity("Acme Technologies").entity_id
    assert first.normalized_name == "acme technologies"


def test_same_name_collisions_are_not_implicitly_joined() -> None:
    identities = build_group_identities(
        [{"display_name": "Mango"}, {"display_name": "Mango"}]
    )
    assert [item.input_position for item in identities] == [0, 1]
    assert identities[0].entity_id != identities[1].entity_id
    assert [item.normalized_name for item in identities] == ["mango", "mango"]


def test_group_order_and_stable_ids_survive_rebuild() -> None:
    payload = [
        {"display_name": "Zepto", "domains": ["zepto.in"]},
        {"display_name": "Blinkit", "domains": ["blinkit.com"]},
    ]
    one = build_group_identities(payload)
    two = build_group_identities(payload)
    assert [item.display_name for item in one] == ["Zepto", "Blinkit"]
    assert [item.entity_id for item in one] == [item.entity_id for item in two]


def test_unresolved_and_quarantine_are_explicit() -> None:
    identity = build_identity("Unknown startup")
    assert identity.state == "unresolved"
    assert identity.confidence == "none"
    assert quarantine("Mango", "same-name collision", input_position=2).reason == "same-name collision"
    with pytest.raises(ValueError):
        build_identity("???")


def test_identity_serialization_is_json_safe_and_has_no_empty_fake_ids() -> None:
    identity = build_identity("Acme", aliases=["ACME"], dpiit_ids=["DPIIT-1"])
    encoded = json.dumps(to_dict(identity), sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["entity_id"] == identity.entity_id
    assert decoded["dpiit_ids"] == ["DPIIT1"]
    assert decoded["entity_id"]
