import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".agents" / "skills" / "openwrt-flash"
SKILL = SKILL_DIR / "SKILL.md"
TR3000_REFERENCE = SKILL_DIR / "references" / "cudy-tr3000-project.md"


class OpenWrtFlashSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = SKILL.read_text(encoding="utf-8")
        cls.reference_text = (
            TR3000_REFERENCE.read_text(encoding="utf-8")
            if TR3000_REFERENCE.exists()
            else ""
        )

    def test_description_and_routing_cover_project_tr3000_artifacts(self) -> None:
        self.assertRegex(
            self.skill_text,
            r"(?m)^description: Use when .*Cudy TR3000.*GitHub Actions",
        )
        self.assertIn("references/cudy-tr3000-project.md", self.skill_text)

    def test_reference_names_only_implemented_workflows_and_artifacts(self) -> None:
        expected = (
            "TR3000 Lite firmware",
            "tr3000-lite-128m-ubootmod-112m",
            "TR3000 DHCP U-Boot",
            "tr3000-dhcp-uboot-128m-multilayout",
            "build-lite.yml",
            "build-uboot.yml",
        )
        for value in expected:
            with self.subTest(value=value):
                self.assertIn(value, self.reference_text)

    def test_reference_separates_firmware_from_bootloader_authorization(self) -> None:
        for value in ("sysupgrade", "BL2", "FIP", "分别授权", "Actions"):
            with self.subTest(value=value):
                self.assertIn(value, self.reference_text)
        self.assertRegex(
            self.reference_text,
            r"(?s)Actions.*(?:不证明|不能证明).*(?:兼容|可刷|安全)",
        )

    def test_reference_blocks_unimplemented_or_incompatible_variants(self) -> None:
        for value in (
            "256 MiB",
            "2544",
            "F50L1G41LC",
            "TR3000 Full",
            "UNRESOLVED",
            "112 MiB UBI",
        ):
            with self.subTest(value=value):
                self.assertIn(value, self.reference_text)

    def test_reference_does_not_supply_raw_flash_commands(self) -> None:
        command_line = re.compile(
            r"(?m)^\s*(?:mtd\s+write|dd\s+if=|nandwrite\b|ubiformat\b)"
        )
        self.assertNotRegex(self.reference_text, command_line)


if __name__ == "__main__":
    unittest.main()
