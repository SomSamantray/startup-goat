"""Focused contract checks for the Startup India GOAT fork."""

import json
import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "startup-india-goat" / "SKILL.md"


def _frontmatter() -> str:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[0]


def test_startup_skill_metadata_and_contract() -> None:
    text = SKILL.read_text(encoding="utf-8")
    frontmatter = _frontmatter()
    assert "name: startup-india-goat" in frontmatter
    assert 'version: "3.21.0"' in frontmatter
    for phrase in (
        "pre-retrieval contract",
        "Public-only research is the default",
        "explicit consent",
        "YourStory",
        "Startup India",
        "Qualitative GOAT rubric",
        "versioned JSON",
        "run manifest",
    ):
        assert phrase in text


def test_fork_has_self_contained_engine_and_no_stale_skill_path() -> None:
    assert (ROOT / "skills" / "startup-india-goat" / "scripts" / "last30days.py").is_file()
    assert not (ROOT / "skills" / "last30days").exists()
    assert "skills/last30days" not in (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")


def test_startup_manifest_names_and_versions_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "startup-india-goat-skill"
    version = pyproject["project"]["version"]
    for relative in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".grok-plugin/plugin.json", "gemini-extension.json"):
        manifest = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert manifest["name"] == "startup-india-goat"
        assert manifest["version"] == version


def test_contract_references_secrets_without_sample_values() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert re.search(r"LINKEDIN_ACCESS_TOKEN|TRACXN_ACCESS_TOKEN", text)
    assert not re.search(r"(?:sk|ghp|xai|AIza)[-_][A-Za-z0-9_-]{12,}", text)
    assert "Authorization headers" in text
