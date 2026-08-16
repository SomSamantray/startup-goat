import re
import unittest
from pathlib import Path

from lib.skill_meta import read_skill_version

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "startup-india-goat"


class TestVersionConsistency(unittest.TestCase):
    def test_skill_md_uses_double_quoted_version(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r'^version:\s*"[^"]+"\s*$', re.MULTILINE))

    def test_skill_metadata_and_header_are_startup_specific(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        version = read_skill_version(SKILL_ROOT / "SKILL.md")
        self.assertEqual("3.21.0", version)
        self.assertIn("# Startup India GOAT", text)
        self.assertIn("STARTUP_GOAT_MEMORY_DIR", text)
        self.assertIn("default `~/Documents/StartupIndiaGOAT/`", text)

    def test_compare_script_does_not_skip_permissions(self) -> None:
        compare_text = (SKILL_ROOT / "scripts" / "compare.sh").read_text(encoding="utf-8")
        self.assertNotIn("--dangerously-skip-permissions", compare_text)


if __name__ == "__main__":
    unittest.main()
