import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = (
    "list-targets.sh",
    "validate.sh",
    "bootstrap.sh",
    "prepare.sh",
    "build.sh",
    "clean.sh",
)


def bash_executable() -> str:
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    executable = shutil.which("bash")
    if executable is None:
        raise unittest.SkipTest("Bash is not installed")
    return executable


def run_script(name: str, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHON"] = Path(sys.executable).as_posix()
    return subprocess.run(
        [bash_executable(), (ROOT / "scripts" / name).as_posix(), *arguments],
        cwd=cwd or ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


class ScriptInterfaceTests(unittest.TestCase):
    def test_every_script_supports_help(self) -> None:
        results = {name: run_script(name, "--help") for name in SCRIPTS}

        self.assertEqual(
            {name: 0 for name in SCRIPTS},
            {name: result.returncode for name, result in results.items()},
        )
        for result in results.values():
            self.assertIn("Usage:", result.stdout)

    def test_validation_runs_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_script("validate.sh", cwd=Path(directory))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Manifest catalog is valid.", result.stdout)

    def test_list_targets_runs_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_script("list-targets.sh", cwd=Path(directory))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(6, len(result.stdout.splitlines()))
        self.assertIn("openwrt\ttr3000\tunresolved\tTR3000", result.stdout)

    def test_build_propagates_unsupported_pair_exit_code_before_mutation(self) -> None:
        work = ROOT / "work"
        if work.exists():
            self.fail("test requires work/ to be absent")

        result = run_script("build.sh", "--distribution", "missing", "--device", "tr3000")

        self.assertEqual(2, result.returncode)
        self.assertIn("unsupported distribution/device pair", result.stderr)
        self.assertFalse(work.exists())

    def test_build_rejects_unresolved_target_before_mutation(self) -> None:
        work = ROOT / "work"
        if work.exists():
            self.fail("test requires work/ to be absent")

        result = run_script("build.sh", "--distribution", "openwrt", "--device", "tr3000")

        self.assertEqual(3, result.returncode)
        self.assertIn("UNRESOLVED", result.stderr)
        self.assertFalse(work.exists())

    def test_clean_rejects_target_outside_generated_roots(self) -> None:
        result = run_script("clean.sh", "../outside")

        self.assertEqual(2, result.returncode)
        self.assertIn("expected one of: work, output, cache", result.stderr)


if __name__ == "__main__":
    unittest.main()
