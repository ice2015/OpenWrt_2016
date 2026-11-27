from pathlib import Path
import json
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
                "build-nx30pro-uboot.yml",
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

    def nx30pro_uboot_lock(self) -> dict:
        return json.loads(
            (ROOT / "devices/nx30pro/uboot/uboot-source-lock.json").read_text(encoding="utf-8")
        )

    def test_nx30pro_uboot_workflow_has_only_a_manual_trigger(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")
        triggers = re.search(r"(?m)^on:\n((?:(?:[ \t].*|)\n)+?)\n(?=\S)", workflow)

        self.assertIsNotNone(triggers, "the workflow does not declare its triggers")
        block = triggers.group(1)
        self.assertIn("workflow_dispatch:", block)
        for forbidden in ("push:", "pull_request:", "schedule:", "release:", "issues:"):
            self.assertNotIn(forbidden, block)
        self.assertNotIn("workflow_dispatch:", "")  # documentation of intent

    def test_nx30pro_uboot_workflow_pins_every_action_by_sha(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")
        uses = re.findall(r"(?m)^\s*uses:\s*(\S+)", workflow)

        self.assertNotEqual([], uses)
        for reference in uses:
            self.assertRegex(
                reference,
                r"^[^@]+@[0-9a-f]{40}$",
                "%s is not pinned to a commit sha" % reference,
            )

    def test_nx30pro_uboot_workflow_installs_the_dependencies_the_lock_names(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")
        lock = self.nx30pro_uboot_lock()

        for package in lock["host_packages"]:
            self.assertIn(package, workflow)
        # build.sh minifies the failsafe web assets with npm before compiling.
        self.assertIn("npm", workflow)

    def test_nx30pro_uboot_workflow_runs_repository_checks_before_the_build(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")

        build_at = workflow.index("devices/nx30pro/build/build-uboot.sh")
        validate_at = workflow.index("bash scripts/validate.sh")
        # The preflight is device scoped: another device's test set must not
        # decide whether this boot loader may be built.
        tests_at = workflow.index("tests.structure.test_nx30pro_uboot_contract")
        self.assertIn("tests.scripts.test_nx30pro_uboot_build", workflow)
        self.assertIn("tests.workflows.test_workflows", workflow)
        self.assertNotIn("discover -s tests", workflow)
        self.assertLess(validate_at, build_at)
        self.assertLess(tests_at, build_at)
        # The static gate of the lock itself runs before any source is fetched.
        preflight_at = workflow.index("check --lock")
        self.assertLess(preflight_at, workflow.index("git clone"))

    def test_nx30pro_uboot_workflow_clones_the_locked_commit_only(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")
        lock = self.nx30pro_uboot_lock()

        self.assertIn(lock["source"]["repository"], workflow)
        self.assertIn(lock["source"]["commit"], workflow)
        # The ref name is informational; a moving branch is never a build input.
        self.assertNotRegex(workflow, r"clone[^\n]*\b(master|main)\b")
        self.assertNotRegex(workflow, r"checkout[^\n]*--branch")
        self.assertRegex(workflow, r"rev-parse HEAD[^\n]*UBOOT_SHA|UBOOT_SHA[^\n]*rev-parse")

    def test_nx30pro_uboot_workflow_has_no_flash_commands_and_no_other_device(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")

        for forbidden in (
            "mtd write",
            "nandwrite",
            "flash_erase",
            "dd if=",
            "/dev/mtd",
            "mtd_debug",
            "sysupgrade",
        ):
            self.assertNotIn(forbidden, workflow)
        for other_device in ("devices/tr3000", "scripts/build-uboot.sh", "build-lite.sh"):
            self.assertNotIn(other_device, workflow)
        self.assertNotIn("secrets:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertRegex(workflow, r"permissions:\s*\n\s+contents: read")

    def test_nx30pro_uboot_workflow_builds_the_locked_candidate(self) -> None:
        workflow = self.workflow("build-nx30pro-uboot.yml")
        lock = self.nx30pro_uboot_lock()

        self.assertIn("concurrency:", workflow)
        self.assertIn("devices/nx30pro/build/build-uboot.sh", workflow)
        self.assertIn("devices/nx30pro/uboot/uboot-source-lock.json", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertNotIn("secrets:", workflow)
        # The build entry point of the plan is called with its exact interface.
        self.assertRegex(
            workflow,
            r"sh devices/nx30pro/build/build-uboot\.sh \\\n"
            r"\s+--lock devices/nx30pro/uboot/uboot-source-lock\.json \\\n"
            r"\s+--source-dir [^\n]+\\\n"
            r"\s+--artifact-dir [^\n]+\n",
        )
        self.assertIn(lock["board"]["name"], workflow)
        # Images are published only when the build and both inspections
        # succeeded; the logs are always kept for diagnosis.
        self.assertRegex(workflow, r"(?s)- name: Upload boot loader candidates.*?if: success\(\)")
        self.assertRegex(workflow, r"(?s)- name: Upload build logs.*?if: always\(\)")
        self.assertIn("uboot-artifact/images/", workflow)
        self.assertIn("uboot-artifact/logs/", workflow)
        self.assertIn("uboot-artifact/build-report.json", workflow)
        self.assertIn("uboot-artifact/FLASH-TARGETS.txt", workflow)
        self.assertIn("if-no-files-found: error", workflow)

    def test_nx30pro_firmware_workflow_builds_the_locked_candidate(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        lock = json.loads(
            (ROOT / "devices/nx30pro/source-lock.json").read_text(encoding="utf-8")
        )

        self.assertIn("workflow_dispatch:", workflow)
        self.assertRegex(workflow, r"permissions:\s*\n\s+contents: read")
        self.assertIn("concurrency:", workflow)
        self.assertIn(lock["source"]["revision"], workflow)
        self.assertIn("devices/nx30pro/build/build.sh", workflow)
        self.assertIn("devices/nx30pro/source-lock.json", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertNotIn("secrets:", workflow)
        # The images are published only when the build and the checks
        # succeeded; the logs are always kept for diagnosis.
        self.assertRegex(workflow, r"(?s)- name: Upload firmware candidates.*?if: success\(\)")
        self.assertRegex(workflow, r"(?s)- name: Upload build logs.*?if: always\(\)")
        self.assertIn("firmware-artifact/images/", workflow)
        self.assertIn("firmware-artifact/logs/", workflow)

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
