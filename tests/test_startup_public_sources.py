"""Proof-first tests for public Startup India GOAT adapters."""
from pathlib import Path

import pytest

from lib.startup_sources import get_source, source_registry
from lib.startup_web import FetchResponse, UnsafeURL, canonical_url, classify_access, parse_document, validate_url, WebFetchError
from lib.yourstory import YourStoryAdapter
from lib.startup_india import StartupIndiaAdapter
from lib.screener import ScreenerAdapter
from lib.inc42 import Inc42Adapter
from lib.the_ken import TheKenAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "startup_sources"

def fixture(name, status=200, url=None):
    body = (FIXTURES / name).read_text()
    def fetcher(requested, timeout=15):
        return FetchResponse(url or requested, status, body)
    return fetcher

def test_web_parser_extracts_metadata_jsonld_tables_and_safe_urls():
    doc = parse_document('<title>A</title><meta property="og:url" content="https://yourstory.com/a"><script type="application/ld+json">{"@type":"Article"}</script><table><tr><th>A</th></tr><tr><td>B</td></tr></table>', 'https://yourstory.com/a')
    assert doc.title == "A" and doc.jsonld[0]["@type"] == "Article" and doc.tables[0][1] == ["B"]
    assert canonical_url('https://yourstory.com/a?utm_source=x&x=1', allowed_domains=('yourstory.com',)) == 'https://yourstory.com/a?x=1'
    with pytest.raises(UnsafeURL): validate_url('http://yourstory.com/a', ('yourstory.com',))
    with pytest.raises(UnsafeURL): validate_url('https://evil.example/a', ('yourstory.com',))

def test_access_classification_is_pre_extraction():
    assert classify_access('Please subscribe to read') == 'paywalled'
    assert classify_access('captcha verify you are human') == 'captcha'
    assert classify_access('', status=429) == 'rate-limited'

def test_yourstory_company_fixture():
    result = YourStoryAdapter().fetch(entity_id='e1', query='acme', url='https://yourstory.com/companies/acme', fetcher=fixture('yourstory_company.html'))
    assert result.outcome.state == 'ok' and result.items[0].metadata['entity_id'] == 'e1'
    assert result.items[0].published_at == '2025-02-03'

def test_startup_india_listing_and_profile_fixture():
    result = StartupIndiaAdapter().fetch(entity_id='e1', url='https://www.startupindia.gov.in/content/sih/en/search.html?roles=Startup', fetcher=fixture('startup_india_listing.html'))
    assert result.outcome.state == 'ok' and result.items[0].metadata['profile_id'] == 'abc123'
    profile = StartupIndiaAdapter().fetch(entity_id='e1', url='https://www.startupindia.gov.in/content/sih/en/profile.Startup.abc123.html', fetcher=fixture('startup_india_profile.html'))
    assert profile.items[0].metadata['dpiit_recognized'] == 'true'

def test_screener_requires_verified_identifier_and_preserves_tables():
    skipped = ScreenerAdapter().fetch(entity_id='e1', query='Acme Private Startup')
    assert skipped.metadata['access_state'] == 'not-applicable'
    result = ScreenerAdapter().fetch(entity_id='e1', ticker='ACME', fetcher=fixture('screener_company.html'))
    assert result.outcome.state == 'ok' and result.items[0].metadata['tables']

def test_inc42_and_ken_dates_and_access_limitation():
    inc = Inc42Adapter().fetch(entity_id='e1', query='acme', fetcher=fixture('inc42_article.html'))
    assert inc.items[0].published_at == '2025-01-04'
    ken = TheKenAdapter().fetch(entity_id='e1', query='acme', fetcher=fixture('paywall.html'))
    assert ken.outcome.state == 'partial' and ken.items[0].metadata['access_state'] == 'paywalled' and not ken.items[0].body

def test_no_results_schema_drift_and_unsafe_redirect_are_degraded():
    empty = StartupIndiaAdapter().fetch(entity_id='e1', url='https://www.startupindia.gov.in/content/sih/en/search.html?roles=Startup', fetcher=fixture('no_results.html'))
    assert empty.outcome.state == 'no-results' and not empty.items
    drift = YourStoryAdapter().fetch(entity_id='e1', url='https://yourstory.com/companies/acme', fetcher=fixture('schema_drift.html'))
    assert drift.outcome.state == 'schema-drift'
    with pytest.raises(UnsafeURL):
        from lib.startup_web import fetch_public
        fetch_public('https://yourstory.com/a', allowed_domains=('yourstory.com',), fetcher=fixture('yourstory_company.html', url='https://evil.example/redirect'))


def test_failures_are_outcomes_without_retry_or_unsafe_fetch():
    def rate_limited(url, timeout=15): raise WebFetchError('429', state='rate-limited', status=429)
    result = Inc42Adapter().fetch(entity_id='e1', query='acme', fetcher=rate_limited)
    assert result.outcome.state == 'rate-limited' and result.metadata['access_state'] == 'rate-limited'
    def timeout(url, timeout=15): raise WebFetchError('timeout', state='timeout')
    assert TheKenAdapter().fetch(entity_id='e1', query='acme', fetcher=timeout).outcome.state == 'timeout'

def test_registry_registers_concrete_public_adapters():
    for name in ('yourstory', 'startup-india', 'screener', 'inc42', 'the-ken'):
        adapter = get_source(name).adapter_factory()
        assert callable(adapter.fetch)
    assert len(source_registry()) >= 12
