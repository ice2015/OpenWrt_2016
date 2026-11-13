import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "openwrt-firmware-config"
SKILL_FILE = SKILL_DIR / "SKILL.md"


class OpenWrtFirmwareConfigSkillTests(unittest.TestCase):
    def test_frontmatter_parser_rejects_ambiguous_colon_scalars(self):
        malformed = (
            "name: openwrt-firmware-config\n"
            "description: Use when: this is not a valid plain YAML scalar"
        )
        with self.assertRaises(ValueError):
            self.parse_frontmatter(malformed)

    @staticmethod
    def parse_frontmatter(frontmatter):
        metadata = {}
        lines = frontmatter.splitlines()
        if len(lines) != 2:
            raise ValueError("frontmatter must contain exactly name and description")
        for line in lines:
            match = re.fullmatch(r"([a-z][a-z0-9_-]*): ([^:\r\n]+)", line)
            if match is None or match.group(1) in metadata:
                raise ValueError(f"invalid frontmatter scalar: {line}")
            metadata[match.group(1)] = match.group(2)
        if set(metadata) != {"name", "description"}:
            raise ValueError("frontmatter requires name and description only")
        return metadata

    def read_skill(self):
        self.assertTrue(SKILL_FILE.is_file(), f"missing project skill: {SKILL_FILE}")
        text = SKILL_FILE.read_text(encoding="utf-8")
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must have YAML frontmatter")
        metadata = self.parse_frontmatter(match.group(1))
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

    def test_evaluation_viewer_inputs_preserve_verbatim_outputs(self):
        workspace = SKILL_DIR.parent / "openwrt-firmware-config-workspace" / "iteration-1"
        for scenario in workspace.iterdir():
            if not scenario.is_dir():
                continue
            for configuration in ("without_skill", "with_skill"):
                run_dir = scenario / configuration
                direct = run_dir / "output.md"
                viewer = run_dir / "outputs" / "output.md"
                if direct.exists() or viewer.exists():
                    with self.subTest(scenario=scenario.name, configuration=configuration):
                        self.assertTrue(direct.is_file())
                        self.assertTrue(viewer.is_file())
                        self.assertEqual(
                            direct.read_text(encoding="utf-8"),
                            viewer.read_text(encoding="utf-8"),
                        )


if __name__ == "__main__":
    unittest.main()
