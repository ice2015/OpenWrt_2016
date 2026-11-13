import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "openwrt-firmware-config"
SKILL_FILE = SKILL_DIR / "SKILL.md"


class OpenWrtFirmwareConfigSkillTests(unittest.TestCase):
    def read_skill(self):
        self.assertTrue(SKILL_FILE.is_file(), f"missing project skill: {SKILL_FILE}")
        text = SKILL_FILE.read_text(encoding="utf-8")
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must have YAML frontmatter")
        metadata = {}
        for line in match.group(1).splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip().strip('"\'')
        return text, metadata, match.group(2)

    def test_skill_frontmatter_and_structure(self):
        text, metadata, _ = self.read_skill()
        self.assertEqual("openwrt-firmware-config", metadata.get("name"))
        description = metadata.get("description", "")
        self.assertTrue(description.startswith("Use when"), description)
        self.assertLessEqual(len(description), 1024)
        self.assertLessEqual(len(text.splitlines()), 300)
        self.assertFalse((SKILL_DIR / "references").exists())

    def test_skill_covers_project_configuration_contract(self):
        text, _, body = self.read_skill()
        required = (
            "common → distribution → device → local",
            "UNRESOLVED",
            "AGENTS.md",
            "docs/configuration-layers.md",
            "bash scripts/validate.sh",
            "python -m unittest discover -s tests -v",
            "Raspberry Pi",
            "TR3000 Lite",
            "TR3000 U-Boot",
            "x86_64",
            "m4 `cannot compute suffix of object files`",
            "带连字符的软件包配置",
            "ninja: No such file or directory",
            "通用目标被 `UNRESOLVED` 主动阻止",
        )
        for item in required:
            with self.subTest(item=item):
                self.assertIn(item, body)

        self.assertNotIn("mtd write", text.lower())
        self.assertIsNone(
            re.search(r"(?:^|\n)\s*(?:sudo\s+)?dd\s+if=", text, re.IGNORECASE),
            "Skill must not contain an executable raw dd flashing recipe",
        )

    def test_skill_is_discoverable_from_repository_guides(self):
        skill_path = ".agents/skills/openwrt-firmware-config/SKILL.md"
        for guide in ("README.md", "AGENTS.md"):
            with self.subTest(guide=guide):
                text = (ROOT / guide).read_text(encoding="utf-8")
                self.assertIn(skill_path, text)
                self.assertRegex(
                    text,
                    r"(?is)(OpenWrt|ImmortalWrt).{0,160}(配置|firmware configuration)",
                )


if __name__ == "__main__":
    unittest.main()
