from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RepositoryContractTests(unittest.TestCase):
    def test_required_layer_files_exist(self) -> None:
        required = {
            ".editorconfig",
            ".gitignore",
            "AGENTS.md",
            "local/README.md",
            "configs/common/base.config",
            "configs/common/packages.config",
            "configs/distributions/openwrt.config",
            "configs/distributions/immortalwrt.config",
            "configs/devices/tr3000.config",
            "configs/devices/x86-64.config",
            "configs/devices/raspberry-pi.config",
            "feeds/common.conf",
            "feeds/openwrt.conf",
            "feeds/immortalwrt.conf",
            "overlays/README.md",
            "patches/README.md",
        }

        missing = sorted(path for path in required if not (ROOT / path).is_file())

        self.assertEqual([], missing)

    def test_generated_and_private_paths_are_ignored(self) -> None:
        ignored = [
            "work/example",
            "output/example",
            "cache/example",
            "local/private.config",
            ".env",
            "secret.key",
        ]
        results = {
            path: subprocess.run(
                ["git", "check-ignore", "--quiet", path],
                cwd=ROOT,
                check=False,
            ).returncode
            for path in ignored
        }

        self.assertEqual({path: 0 for path in ignored}, results)

    def test_local_readme_remains_trackable(self) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "local/README.md"],
            cwd=ROOT,
            check=False,
        )

        self.assertEqual(1, result.returncode)

    def test_operating_documents_exist(self) -> None:
        documents = [
            "README.md",
            "docs/architecture.md",
            "docs/configuration-layers.md",
            "docs/adding-a-device.md",
        ]

        self.assertEqual([], [path for path in documents if not (ROOT / path).is_file()])

    def test_readme_local_links_resolve(self) -> None:
        readme = ROOT / "README.md"
        links = re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", readme.read_text(encoding="utf-8"))
        local_links = [link.split("#", 1)[0] for link in links if "://" not in link]

        missing = sorted(link for link in local_links if link and not (ROOT / link).exists())

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
