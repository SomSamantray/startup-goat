from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from lib.browser_capture import BrowserCaptureEnvelope, BrowserCaptureError, parse_browser_capture


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def payload(**overrides):
    value = {
        "schema_version": "1.0",
        "source": "tracxn",
        "entity_id": "startup_1",
        "page_url": "https://platform.tracxn.com/a/d/company/1/acme",
        "page_title": "Acme profile",
        "visible_fields": {"name": "Acme", "stage": "Series A", "employee_count": 42},
        "visible_rows": [{"label": "Revenue", "value": "₹10 crore"}],
        "public_links": ["https://platform.tracxn.com/a/d/company/1/acme"],
        "access_state": "private-session",
        "captured_at": NOW.isoformat(),
        "ttl_seconds": 900,
        "session_classification": "private-session",
    }
    value.update(overrides)
    return value


def test_valid_envelope_is_projection_only():
    envelope = parse_browser_capture(payload(), expected_source="tracxn", expected_entity_id="startup_1")
    assert envelope.fresh
    assert "visible_fields" in envelope.to_dict()
    assert "cookie" not in repr(envelope).lower()


def test_sanitized_valid_fixture_is_accepted():
    fixture = Path(__file__).parent / "fixtures/startup_sources/browser_capture_valid.json"
    envelope = parse_browser_capture(json.loads(fixture.read_text()), expected_source="tracxn", expected_entity_id="startup_1")
    assert envelope.visible_fields["name"] == "Acme"


@pytest.mark.parametrize("bad", [
    {"cookies": {"sid": "dummy"}},
    {"headers": {"Authorization": "Bearer dummy"}},
    {"raw_html": "<script>secret</script>"},
    {"unknown": True},
])
def test_secret_or_unknown_top_level_fields_rejected(bad):
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(**bad))


def test_hidden_field_html_and_jwt_rejected():
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(visible_fields={"hidden_input": "x"}))
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(visible_fields={"description": "<script>secret</script>"}))
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(visible_fields={"description": "aaa.bbbbbbbb.cccccccc"}))


def test_unsafe_url_expired_and_entity_mismatch_rejected():
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(page_url="http://platform.tracxn.com/x"))
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(captured_at=(NOW - timedelta(hours=2)).isoformat(), ttl_seconds=60))
    with pytest.raises(BrowserCaptureError):
        parse_browser_capture(payload(), expected_entity_id="startup_2")


def test_private_session_is_default_when_omitted():
    value = payload()
    value.pop("access_state")
    value.pop("session_classification")
    assert parse_browser_capture(value).access_state == "private-session"
