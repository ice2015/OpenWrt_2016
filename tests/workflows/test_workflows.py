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
        self.assertNotIn("paths:", workflow)
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

    def test_reusable_build_passes_inputs_as_data_not_shell_source(self) -> None:
        workflow = self.workflow("reusable-build.yml")
        run_blocks = re.findall(r"run: \|\n((?:          .*\n)+)", workflow)

        self.assertNotEqual([], run_blocks)
        self.assertNotIn("${{ inputs.", "\n".join(run_blocks))
        self.assertIn("DISTRIBUTION: ${{ inputs.distribution }}", workflow)
        self.assertIn("DEVICE: ${{ inputs.device }}", workflow)
        self.assertIn("SOURCE_REVISION: ${{ inputs.source_revision }}", workflow)
        self.assertIn('--distribution "$DISTRIBUTION"', workflow)
        self.assertIn('--device "$DEVICE"', workflow)
        self.assertIn('--revision "$SOURCE_REVISION"', workflow)

    def test_workflows_delegate_native_build_logic_to_scripts(self) -> None:
        combined = "\n".join(
            self.workflow(name)
            for name in (
                "validate.yml",
                "build.yml",
                "reusable-build.yml",
                "build-lite.yml",
                "build-uboot.yml",
            )
        )

        self.assertNotIn("pull_request_target", combined)
        self.assertNotRegex(combined, r"(?m)^\s+run: (?:make|git clone|\./scripts/feeds)")
        self.assertNotIn("secrets:", combined)

    def test_lite_workflow_pins_source_and_gates_firmware_outputs(self) -> None:
        workflow = self.workflow("build-lite.yml")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("runs-on: ubuntu-22.04", workflow)
        self.assertIn("cc777dfa3c1964518ddb2c310e8570830b11e954", workflow)
        self.assertIn("ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8", workflow)
        self.assertIn("devices/tr3000/build/build-lite.sh", workflow)
        self.assertIn("actions/cache@", workflow)
        self.assertIn("actions/cache@", workflow)
        self.assertIn("actions/upload-artifact@", workflow)

    def test_uboot_workflow_is_independent_and_pinned(self) -> None:
        workflow = self.workflow("build-uboot.yml")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("f6b361ed80012244b1ed33be1b5080b4d65e83fb", workflow)
        self.assertIn("devices/tr3000/build/build-uboot.sh", workflow)
        self.assertIn("MULTI_LAYOUT=1", (ROOT / "devices/tr3000/build/build-uboot.sh").read_text(encoding="utf-8"))
        self.assertNotIn("256mb", workflow.lower())

    def test_full_workflow_has_typed_options_and_pinned_build_inputs(self) -> None:
        workflow = self.workflow("build-full.yml")

        self.assertIn("workflow_dispatch:", workflow)
        defaults = {
            "include_tailscale": "false",
            "include_singbox": "true",
            "include_cloudflared": "true",
            "release": "false",
        }
        for input_name, default in defaults.items():
            block = re.search(
                rf"\n      {input_name}:\n(?P<body>(?:        .+\n)+)",
                workflow,
            )
            self.assertIsNotNone(block, input_name)
            self.assertIn("type: boolean", block.group("body"))
            self.assertIn(f"default: {default}", block.group("body"))
        self.assertRegex(workflow, r"permissions:\s*\n\s+contents: read")
        self.assertIn("cc777dfa3c1964518ddb2c310e8570830b11e954", workflow)
        self.assertIn("ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8", workflow)
        self.assertIn("devices/tr3000/build/build-full.sh", workflow)
        self.assertIn("actions/cache@", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertIn("TR3000-128M-112M-Full", workflow)

    def test_full_workflow_passes_dispatch_values_as_environment_data(self) -> None:
        workflow = self.workflow("build-full.yml")
        run_blocks = re.findall(r"run: \|\n((?:          .*\n)+)", workflow)

        self.assertNotIn("${{ inputs.", "\n".join(run_blocks))
        self.assertIn("INCLUDE_TAILSCALE: ${{ inputs.include_tailscale }}", workflow)
        self.assertIn("INCLUDE_SINGBOX: ${{ inputs.include_singbox }}", workflow)
        self.assertIn("INCLUDE_CLOUDFLARED: ${{ inputs.include_cloudflared }}", workflow)
        self.assertIn('--include-tailscale "$INCLUDE_TAILSCALE"', workflow)
        self.assertIn('--include-singbox "$INCLUDE_SINGBOX"', workflow)
        self.assertIn('--include-cloudflared "$INCLUDE_CLOUDFLARED"', workflow)


if __name__ == "__main__":
    unittest.main()
