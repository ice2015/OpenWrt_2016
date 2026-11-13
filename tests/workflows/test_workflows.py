from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"


class WorkflowContractTests(unittest.TestCase):
    def workflow(self, name: str) -> str:
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_validation_is_read_only_and_runs_repository_checks(self) -> None:
        workflow = self.workflow("validate.yml")

        self.assertIn("pull_request:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertRegex(workflow, r"permissions:\s*\n\s+contents: read")
        self.assertIn("bash scripts/validate.sh", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)

    def test_manual_build_constrains_distribution_and_device_inputs(self) -> None:
        workflow = self.workflow("build.yml")

        self.assertIn("workflow_dispatch:", workflow)
        for input_name in ("distribution", "device"):
            block = re.search(rf"\n      {input_name}:\n(?P<body>(?:        .+\n)+)", workflow)
            self.assertIsNotNone(block)
            self.assertIn("type: choice", block.group("body"))
        self.assertIn("source_revision:", workflow)
        self.assertIn("type: string", workflow)
        self.assertIn("uses: ./.github/workflows/reusable-build.yml", workflow)

    def test_reusable_build_declares_typed_inputs_and_safe_limits(self) -> None:
        workflow = self.workflow("reusable-build.yml")

        self.assertIn("workflow_call:", workflow)
        for input_name in ("distribution", "device", "source_revision"):
            self.assertRegex(workflow, rf"(?s)\n      {input_name}:.*?type: string")
        self.assertIn("timeout-minutes:", workflow)
        self.assertIn("concurrency:", workflow)
        self.assertRegex(workflow, r"permissions:\s*\n\s+contents: read")
        self.assertIn("bash scripts/validate.sh", workflow)
        self.assertIn("bash scripts/build.sh", workflow)

    def test_workflows_delegate_native_build_logic_to_scripts(self) -> None:
        combined = "\n".join(
            self.workflow(name)
            for name in ("validate.yml", "build.yml", "reusable-build.yml")
        )

        self.assertNotIn("pull_request_target", combined)
        self.assertNotRegex(combined, r"(?m)^\s+run: (?:make|git clone|\./scripts/feeds)")
        self.assertNotIn("secrets:", combined)


if __name__ == "__main__":
    unittest.main()
