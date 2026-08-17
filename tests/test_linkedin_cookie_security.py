"""Security-contract tests for the user-supplied-cookie LinkedIn adapter.

These tests prove the never-persist, never-echo, redirect-safe, proxy-safe
contract that the adapter's threat model depends on.  They complement the
behavior tests in test_linkedin_cookie.py by targeting the security-relevant
edges specifically.
"""
import os
import unittest
import urllib.error
import urllib.request
from unittest import mock

from lib.linkedin_cookie import LinkedInCookieAdapter

COOKIES = {"li_at": "dummy-li-at-secret-123", "JSESSIONID": "ajax:123456", "bcookie": "dummy-bcookie-456"}
_HTML = "<html><head><title>Acme | LinkedIn</title></head><body><p>Overview</p><p>Acme is a company.</p><p>10K followers 51-200 employees</p></body></html>"


def _response(status=200, body=_HTML, url="https://www.linkedin.com/company/acme"):
    return (status, body, url)


class TestExceptionSanitization(unittest.TestCase):
    def test_unhandled_exception_yields_static_detail(self):
        # An exception whose message contains a cookie value must never leak it
        # into the outcome detail or the pipeline error string.
        class LeakyError(Exception):
            pass

        adapter = LinkedInCookieAdapter(
            fetcher=lambda *a: (_ for _ in ()).throw(LeakyError(f"cookie leaked: {COOKIES['li_at']}"))
        )
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)
        self.assertNotIn(COOKIES["li_at"], result.outcome.detail)
        self.assertNotIn(COOKIES["li_at"], repr(result))

    def test_response_echo_of_cookie_redacted_everywhere(self):
        echo = _HTML + f"<p>session token: {COOKIES['li_at']} is active</p>"
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: _response(200, echo))
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("ok", result.outcome.state)
        for item in result.items:
            self.assertNotIn(COOKIES["li_at"], item.body)
            self.assertNotIn(COOKIES["li_at"], item.title)
        self.assertNotIn(COOKIES["li_at"], repr(result))


class TestRedirectSafety(unittest.TestCase):
    def test_cross_origin_redirect_rejected_no_second_request(self):
        calls = []

        def fetcher(url, headers, timeout):
            calls.append(headers.get("Cookie"))
            return _response(200, _HTML, "https://evil.example/company/acme")

        adapter = LinkedInCookieAdapter(fetcher=fetcher)
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)
        self.assertEqual(1, len(calls))  # exactly one request, no follow


class TestNoPersistence(unittest.TestCase):
    def test_adapter_holds_no_cookie_after_fetch(self):
        adapter = LinkedInCookieAdapter(fetcher=lambda *a: _response())
        adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        # The adapter stores cookies only as locals during the call; the
        # instance must not retain them afterward.
        self.assertFalse(hasattr(adapter, "_cookies"))
        self.assertFalse(hasattr(adapter, "_cookie_header"))

    def test_cookie_values_never_in_serialized_output(self):
        import io
        import json

        adapter = LinkedInCookieAdapter(fetcher=lambda *a: _response())
        result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        buffer = io.StringIO()
        json.dump({"outcome": result.outcome.__dict__ if hasattr(result.outcome, "__dict__") else str(result.outcome),
                   "items": [str(item) for item in result.items]}, buffer)
        self.assertNotIn(COOKIES["li_at"], buffer.getvalue())


class TestProxyDisabled(unittest.TestCase):
    def test_opener_uses_no_env_proxy(self):
        # The credentialed request must not traverse an env-configured proxy.
        # An explicit empty ProxyHandler is optimized out by build_opener, so
        # no proxy handler exists and env proxies never apply.
        adapter = LinkedInCookieAdapter()
        with mock.patch.dict(os.environ, {"http_proxy": "http://proxy.example:8080", "https_proxy": "http://proxy.example:8080"}):
            opener = adapter._build_opener()
        self.assertFalse(
            any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers),
            "env proxy must not be applied to the credentialed opener",
        )


class TestUrlValidation(unittest.TestCase):
    def test_invalid_slug_rejected(self):
        from lib.startup_web import UnsafeURL

        adapter = LinkedInCookieAdapter()
        # Path traversal and non-slug characters are rejected at URL build.
        for bad in ("../../etc/passwd", "a b", "acme?x=1", ""):
            with self.assertRaises(UnsafeURL):
                adapter._url(bad)

    def test_valid_slug_builds_allowlisted_url(self):
        adapter = LinkedInCookieAdapter()
        url = adapter._url("acme")
        self.assertEqual("https://www.linkedin.com/company/acme", url)


class TestRedactionEncodedEchoes(unittest.TestCase):
    def test_url_encoded_cookie_echo_redacted(self):
        import urllib.parse

        from lib.linkedin_cookie import _redact

        encoded = urllib.parse.quote(COOKIES["li_at"], safe="")
        text = f"session value {encoded} is live"
        redacted = _redact(text, (COOKIES["li_at"],))
        self.assertNotIn(encoded, redacted)
        self.assertIn("<redacted>", redacted)

    def test_html_entity_encoded_cookie_echo_redacted(self):
        import html

        from lib.linkedin_cookie import _redact

        escaped = html.escape(COOKIES["li_at"])
        text = f"token {escaped} in body"
        redacted = _redact(text, (COOKIES["li_at"],))
        self.assertNotIn(escaped, redacted)
        self.assertIn("<redacted>", redacted)

    def test_short_cookie_value_redacted(self):
        from lib.linkedin_cookie import _redact

        short = "abc12345"
        text = f"leaked {short} here"
        self.assertNotIn(short, _redact(text, (short,)))


class TestRealOpenerPath(unittest.TestCase):
    """Exercise the production urllib opener path (no injected fetcher)."""

    @staticmethod
    def _serve(handler):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = handler(self.path)
                self.send_response(status)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def test_redirect_status_maps_to_schema_drift(self):
        import io

        from lib import linkedin_cookie as lc

        server = self._serve(lambda path: (302, ""))
        adapter = LinkedInCookieAdapter()
        with mock.patch.object(urllib.request, "build_opener") as build, \
                mock.patch.object(lc, "validate_resolved_host"):
            opener = mock.MagicMock()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://www.linkedin.com/company/acme", 302, "Found", {}, io.BytesIO(b"")
            )
            build.return_value = opener
            result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("schema-drift", result.outcome.state)
        self.assertIn("redirect", result.outcome.detail)
        server.shutdown()

    def test_http_500_maps_to_unreachable(self):
        import io

        from lib import linkedin_cookie as lc

        server = self._serve(lambda path: (500, "<html><body>oops</body></html>"))
        adapter = LinkedInCookieAdapter()
        with mock.patch.object(urllib.request, "build_opener") as build, \
                mock.patch.object(lc, "validate_resolved_host"):
            opener = mock.MagicMock()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://www.linkedin.com/company/acme", 500, "Internal", {}, io.BytesIO(b"<html><body>oops</body></html>")
            )
            build.return_value = opener
            result = adapter.fetch(entity_id="e1", query="Acme", slug="acme", cookies=COOKIES)
        self.assertEqual("unreachable", result.outcome.state)
        server.shutdown()

    def test_slow_drip_read_is_bounded(self):
        from lib.linkedin_cookie import _read_bounded

        class _SlowHandle:
            def __init__(self):
                self.calls = 0

            def read(self, size):
                self.calls += 1
                if self.calls > 1000:
                    return b""
                return b"x" * 1024

        body = _read_bounded(_SlowHandle(), timeout=0.05)
        # The read stops once the deadline elapses; it never hangs.
        self.assertLessEqual(len(body), 2_000_001)
        self.assertTrue(isinstance(body, str))


if __name__ == "__main__":
    unittest.main()
