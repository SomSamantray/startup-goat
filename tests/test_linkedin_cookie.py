"""Tests for the user-supplied-cookie LinkedIn adapter (linkedin_cookie.py)."""
import unittest
from unittest import mock

from lib.linkedin_cookie import (
    LinkedInCookieAdapter,
    _name_matches,
    _post_items,
    _slugify,
)

COOKIES = {"li_at": "dummy-li-at-secret-123", "JSESSIONID": "ajax:123456", "bcookie": "dummy-bcookie-456"}

_COMPANY_HTML = """<html><head><title>Inc42 Media | LinkedIn</title></head>
<body>
<p>The Authoritative Voice On The Indian Startup Ecosystem</p>
<p>Technology, Information and Media New Delhi, Delhi 692K followers 51-200 employees</p>
<p>Overview</p>
<p>Inc42 is India's largest tech media platform.</p>
<p>Page posts</p>
<div class="feed-shared-update-v2">
<p>Inc42 Media</p>
<p>1h • Edited</p>
<p>Ola Electric Expands Into Energy Storage With Three New Products</p>
</div>
</body></html>"""


def response(status=200, body=_COMPANY_HTML, url="https://www.linkedin.com/company/inc42"):
    return (status, body, url)


def response_acme(status=200, body=_COMPANY_HTML):
    return (status, body, "https://www.linkedin.com/company/acme")


class TestFetch(unittest.TestCase):
    def _adapter(self, calls):
        def fetcher(url, headers, timeout):
            calls.append((url, headers, timeout))
            return response()
        return LinkedInCookieAdapter(fetcher=fetcher), calls

    def test_happy_path_extracts_profile_and_posts(self):
        calls = []
        adapter, calls = self._adapter(calls)
        result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
        self.assertEqual("ok", result.outcome.state)
        self.assertEqual(2, len(result.items))  # profile + 1 post
        profile = result.items[0]
        self.assertEqual("company-profile", profile.metadata["claim_type"])
        self.assertEqual("Inc42 Media", profile.title)
        self.assertIn("Technology, Information and Media", profile.body)
        self.assertIn("692K followers", profile.body)
        self.assertIn("51-200 employees", profile.body)
        self.assertEqual("private-session", profile.metadata["access_state"])
        self.assertEqual("cookie-session", profile.metadata["access_mode"])
        # The Cookie header was assembled and sent.
        self.assertIn("li_at=dummy-li-at-secret-123", calls[0][1]["Cookie"])

    def test_no_cookies_skipped_without_network(self):
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: (_ for _ in ()).throw(AssertionError("must not call")))
        result = adapter.fetch(entity_id="e1", query="Acme", cookies={})
        self.assertEqual("skipped-unconfigured", result.outcome.state)

    def test_reads_cookies_from_env_when_not_passed(self):
        calls = []
        adapter, calls = self._adapter(calls)
        with mock.patch.dict("os.environ", {"LINKEDIN_LI_AT": "env-li-at", "LINKEDIN_JSESSIONID": "ajax:1", "LINKEDIN_BCOOKIE": "env-bc"}):
            result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42")
        self.assertEqual("ok", result.outcome.state)
        self.assertIn("li_at=env-li-at", calls[0][1]["Cookie"])

    def test_http_999_and_429_rate_limited_no_retry(self):
        for status in (999, 429):
            calls = []
            adapter = LinkedInCookieAdapter(fetcher=lambda *a: (calls.append(a), response(status))[1])
            result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
            self.assertEqual("rate-limited", result.outcome.state)
            self.assertEqual(1, len(calls))

    def test_http_401_403_auth_failed(self):
        for status in (401, 403):
            calls = []
            adapter = LinkedInCookieAdapter(fetcher=lambda *a: (calls.append(a), response(status))[1])
            result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
            self.assertEqual("auth-failed", result.outcome.state)
            self.assertEqual(1, len(calls))

    def test_authwall_marker_in_body_auth_failed(self):
        body = "<html><body>Sign in to view full profile. Join LinkedIn.</body></html>"
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: response(200, body))
        result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
        self.assertEqual("auth-failed", result.outcome.state)

    def test_redirect_rejected_no_cookie_forwarded(self):
        calls = []
        adapter = LinkedInCookieAdapter(
            fetcher=lambda url, headers, timeout: (calls.append((url, headers)), response(200, _COMPANY_HTML, "https://evil.example/company/inc42"))[1]
        )
        result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)
        self.assertEqual(1, len(calls))

    def test_missing_name_schema_drift(self):
        body = "<html><body><p>no title here at all</p></body></html>"
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: response_acme(200, body))
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)

    def test_empty_body_no_results(self):
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: response_acme(200, ""))
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("no-results", result.outcome.state)

    def test_name_mismatch_schema_drift(self):
        # The slug resolved to a differently-named company: reject the evidence.
        body = "<html><head><title>Some Other Company | LinkedIn</title></head><body><p>Overview</p><p>about text</p></body></html>"
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: response(200, body))
        result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)
        self.assertEqual([], result.items)

    def test_cookie_values_redacted_from_items_and_repr(self):
        echo = _COMPANY_HTML + f"<p>token leaked: {COOKIES['li_at']}</p>"
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: response(200, echo))
        result = adapter.fetch(entity_id="e1", query="Inc42 Media", slug="inc42", cookies=COOKIES)
        self.assertEqual("ok", result.outcome.state)
        for item in result.items:
            self.assertNotIn(COOKIES["li_at"], item.body)
            self.assertNotIn(COOKIES["li_at"], item.title)
        self.assertNotIn(COOKIES["li_at"], repr(result))

    def test_network_error_maps_to_unreachable(self):
        import urllib.error
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: (_ for _ in ()).throw(urllib.error.URLError("boom")))
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("unreachable", result.outcome.state)

    def test_timeout_maps_to_timeout(self):
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: (_ for _ in ()).throw(TimeoutError("slow")))
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("timeout", result.outcome.state)

    def test_unsafe_slug_rejected(self):
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: response())
        result = adapter.fetch(entity_id="e1", query="Acme", slug="../../etc/passwd", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)


class TestSlugify(unittest.TestCase):
    def test_display_name_to_slug(self):
        self.assertEqual("inc42-media", _slugify("Inc42 Media"))
        self.assertEqual("acme", _slugify("Acme"))
        self.assertEqual("flipkart-pvt-ltd", _slugify("Flipkart Pvt Ltd"))


class TestSlugify(unittest.TestCase):
    def test_display_name_to_slug(self):
        self.assertEqual("inc42-media", _slugify("Inc42 Media"))
        self.assertEqual("acme", _slugify("Acme"))
        self.assertEqual("flipkart-pvt-ltd", _slugify("Flipkart Pvt Ltd"))


class TestNameMatch(unittest.TestCase):
    def test_exact_and_contained(self):
        self.assertTrue(_name_matches("Inc42 Media", "Inc42 Media", "e"))
        self.assertTrue(_name_matches("Inc42 Media", "what is Inc42 Media building", "e"))

    def test_mismatch(self):
        self.assertFalse(_name_matches("Some Other Company", "Inc42 Media", "e"))

    def test_single_word_fuzzy_allowed(self):
        # Single-word names fall back to exact comparison to avoid false hits.
        self.assertFalse(_name_matches("Acme", "Apple", "e"))
        self.assertTrue(_name_matches("Acme", "Acme", "e"))


class TestPostItems(unittest.TestCase):
    def _html(self, *posts):
        blocks = "".join(
            f'<div class="feed-shared-update-v2"><p>Inc42 Media</p><p>1h</p><p>{p}</p></div>'
            for p in posts
        )
        return f"<html><body><p>Page posts</p>{blocks}</body></html>"

    def test_parses_bounded_posts(self):
        html = self._html(
            "Ola Electric Expands Into Energy Storage With Three New Products",
            "Zomato raises a fresh round to expand its delivery network",
        )
        items = _post_items(html, max_posts=2, secrets=())
        self.assertEqual(2, len(items))
        self.assertEqual("post", items[0].metadata["claim_type"])
        self.assertIn("Ola Electric", items[0].body)

    def test_no_post_block_returns_empty(self):
        self.assertEqual([], _post_items("<html><body><p>no posts here</p></body></html>", max_posts=2, secrets=()))

    def test_redacts_cookie_echo_in_posts(self):
        html = self._html(f"leaked token {COOKIES['li_at']} inside the post body")
        items = _post_items(html, max_posts=1, secrets=(COOKIES["li_at"],))
        self.assertEqual(1, len(items))
        self.assertNotIn(COOKIES["li_at"], items[0].body)


if __name__ == "__main__":
    unittest.main()
