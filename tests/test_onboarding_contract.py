"""Onboarding and consent contract for Startup India GOAT."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "startup-india-goat" / "SKILL.md"


def test_contract_precedes_retrieval() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    contract = text.index("## Required pre-retrieval contract")
    retrieval = text.index("## Source coverage")
    assert contract < retrieval
    assert "entities" in text[contract:retrieval]
    assert "expected gaps" in text[contract:retrieval]


def test_public_default_and_gated_consent_are_distinct() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Public-only research is the default" in text
    assert "Ask for explicit consent" in text
    assert "Never bypass authentication, paywalls, CAPTCHA, quotas" in text


def test_artifact_contract_covers_single_and_group_runs() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "single-company run saves Markdown" in text
    assert "A group run additionally saves a comparison index" in text
    assert "STARTUP_GOAT_MEMORY_DIR" in text
    assert "manifest" in text
