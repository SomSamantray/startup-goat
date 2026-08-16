import json

from lib.linkedin_token import LinkedInTokenAdapter


TOKEN = "dummy-linkedin-token-123456"


def response(status=200, body=None, url="https://api.linkedin.com/v2/organizations/startup_1"):
    return (status, json.dumps(body if body is not None else {"name": "Acme", "industry": "Software"}), url)


def test_linkedin_sends_bearer_only_in_memory_and_maps_profile():
    calls = []

    def fetcher(url, headers, timeout):
        calls.append((url, headers, timeout))
        return response()

    result = LinkedInTokenAdapter(fetcher=fetcher).fetch(entity_id="startup_1", token=TOKEN)
    assert result.outcome.state == "ok"
    assert calls[0][0] == "https://api.linkedin.com/v2/organizations/startup_1"
    assert calls[0][1]["Authorization"] == f"Bearer {TOKEN}"
    assert "?" not in calls[0][0]
    assert TOKEN not in repr(result)


def test_linkedin_does_not_retry_auth_quota_or_redirect():
    for status, expected in ((401, "auth-failed"), (403, "auth-failed"), (429, "rate-limited")):
        calls = []
        result = LinkedInTokenAdapter(fetcher=lambda *args: (calls.append(args), response(status))[1]).fetch(entity_id="startup_1", token=TOKEN)
        assert result.outcome.state == expected
        assert len(calls) == 1
    result = LinkedInTokenAdapter(fetcher=lambda *args: response(200, {"name": "Acme"}, "https://evil.example/x")).fetch(entity_id="startup_1", token=TOKEN)
    assert result.outcome.state == "schema-drift"


def test_linkedin_redacts_provider_token_echo():
    result = LinkedInTokenAdapter(fetcher=lambda *args: response(200, {"name": "Acme", "description": TOKEN})).fetch(entity_id="startup_1", token=TOKEN)
    assert result.outcome.state == "ok"
    assert TOKEN not in repr(result)


def test_linkedin_schema_drift_and_bad_endpoint_fail_closed():
    result = LinkedInTokenAdapter(fetcher=lambda *args: response(200, {"not_a_company": True})).fetch(entity_id="startup_1", token=TOKEN)
    assert result.outcome.state == "schema-drift"
    result = LinkedInTokenAdapter(endpoint="https://evil.example/api/{entity_id}").fetch(entity_id="startup_1", token=TOKEN)
    assert result.outcome.state == "schema-drift"
    assert TOKEN not in repr(result)


def test_linkedin_missing_token_is_skipped():
    result = LinkedInTokenAdapter(fetcher=lambda *args: response()).fetch(entity_id="startup_1", token="")
    assert result.outcome.state == "skipped-unconfigured"
