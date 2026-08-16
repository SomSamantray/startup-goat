from datetime import datetime, timezone

from lib.tracxn import TracxnAdapter


def envelope(**changes):
    value = {
        "schema_version": "1.0", "source": "tracxn", "entity_id": "startup_1",
        "page_url": "https://platform.tracxn.com/a/d/company/1/acme", "page_title": "Acme",
        "visible_fields": {"name": "Acme", "stage": "Series A", "revenue": "₹10 crore"},
        "visible_rows": [], "public_links": [], "access_state": "private-session",
        "captured_at": datetime.now(timezone.utc).isoformat(), "ttl_seconds": 900,
        "session_classification": "private-session",
    }
    value.update(changes)
    return value


def test_tracxn_accepts_validated_visible_envelope_only():
    result = TracxnAdapter().fetch(entity_id="startup_1", browser_envelope=envelope())
    assert result.outcome.state == "ok"
    assert result.items[0].metadata["access_mode"] == "browser-envelope"
    assert result.items[0].metadata["entity_id"] == "startup_1"


def test_tracxn_quota_and_permission_states_are_not_fabricated():
    for state, outcome in (("quota-exhausted", "rate-limited"), ("login-required", "auth-failed"), ("paywalled", "partial")):
        result = TracxnAdapter().fetch(entity_id="startup_1", envelope=envelope(access_state=state))
        assert result.outcome.state == outcome
        assert result.metadata["access_state"] == state


def test_tracxn_rejects_mismatch_and_schema_drift():
    result = TracxnAdapter().fetch(entity_id="startup_2", browser_envelope=envelope())
    assert result.outcome.state == "schema-drift"
    result = TracxnAdapter().fetch(entity_id="startup_1", browser_envelope=envelope(visible_fields={}))
    assert result.outcome.state == "schema-drift"


def test_tracxn_supported_token_response_is_allowlisted_projection():
    result = TracxnAdapter().fetch(entity_id="startup_1", token_response={"data": {"name": "Acme", "stage": "Seed"}})
    assert result.outcome.state == "ok"
    result = TracxnAdapter().fetch(entity_id="startup_1", token_response={"status": 429, "quota_exhausted": True})
    assert result.outcome.state == "rate-limited"
    result = TracxnAdapter().fetch(entity_id="startup_1", token_response={"status": 403})
    assert result.outcome.state == "auth-failed"


def test_tracxn_does_not_accept_raw_credentials_or_bare_token():
    result = TracxnAdapter().fetch(entity_id="startup_1", token="dummy")
    assert result.outcome.state == "skipped-unconfigured"
