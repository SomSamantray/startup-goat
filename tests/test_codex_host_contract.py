"""Cross-host contract for the Startup India GOAT skill."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "startup-india-goat" / "SKILL.md"


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_non_modal_hosts_can_use_public_only_fallback() -> None:
    text = _text()
    assert "browser-tab tooling is unavailable" in text
    assert "public-only path" in text
    assert "browser-assisted sources as unavailable" in text


def test_gated_sources_require_explicit_consent() -> None:
    text = _text()
    assert "explicit consent" in text
    assert "reading browser cookies" in text
    assert "gated browser session" in text
    assert "paid or third-party provider" in text


def test_browser_capture_is_allowlist_only_and_secret_free() -> None:
    text = _text()
    assert "allowlist-only browser capture" in text
    assert "cookies, browser storage, Authorization headers" in text
    assert "Never request or persist" in text


def test_source_limitations_are_honest() -> None:
    text = _text()
    for outcome in ("auth-failed", "paywalled", "captcha", "quota-exhausted", "schema-drift", "no-results"):
        assert outcome in text
    assert "Unavailable does not mean no activity" in text
