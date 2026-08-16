from lib.startup_facts import extract_profile
from lib.startup_html import render_html
from lib.startup_identity import build_identity
from lib.startup_public_base import item


def test_html_uses_shared_sanitizer_and_preserves_markdown_facts_and_citations():
    identity = build_identity("HTML Co", state="resolved", confidence="high")
    source = item("yourstory", identity.entity_id, url="https://yourstory.com/html", title="HTML Co", body="Product: safe value <img src=x onerror=alert(1)>", metadata={"structured_facts": {"product": "safe value"}})
    profile = extract_profile(identity, [source])
    rendered = render_html(profile)
    assert "safe value" in rendered
    assert profile.evidence[0].evidence_id in rendered
    assert "<script" not in rendered.lower()
    assert "onerror" not in rendered.lower()
    assert "javascript:" not in rendered.lower()
    assert "rel=\"noopener noreferrer\"" in rendered
