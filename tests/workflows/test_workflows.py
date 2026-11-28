from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"


class WorkflowContractTests(unittest.TestCase):
    def workflow(self, name: str) -> str:
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def workflow_step(self, workflow: str, name: str) -> str:
        """Return the body of one named step, up to the next step."""
        match = re.search(
            r"(?s)- name: %s\n(.*?)(?=\n      - name: |\Z)" % re.escape(name),
            workflow,
        )
        self.assertIsNotNone(match, "the workflow has no %r step" % name)
        return match.group(1)

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
                "build-nx30pro.yml",
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

    def nx30pro_firmware_lock(self) -> dict:
        return json.loads(
            (ROOT / "devices/nx30pro/source-lock.json").read_text(encoding="utf-8")
        )

    def test_nx30pro_firmware_workflow_names_the_candidate_and_its_acceptance_boundary(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        header = workflow.split("\non:\n", 1)[0]

        self.assertIn("name: NX30 Pro 112M firmware candidate", workflow)
        # The header states both boundaries of this workflow: a candidate is
        # never accepted here, and the lock gate stops the job while any fact
        # of the source lock is still UNRESOLVED.
        self.assertRegex(header, r"(?i)accepting a candidate is a separate")
        self.assertIn("devices/nx30pro/docs/TEST-REPORT.md", header)
        self.assertIn("--check-only", header)
        self.assertIn("build-not-ready status 3", header)

    def test_nx30pro_firmware_workflow_has_only_a_manual_trigger(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        triggers = re.search(r"(?m)^on:\n((?:(?:[ \t].*|)\n)+?)\n(?=\S)", workflow)

        self.assertIsNotNone(triggers, "the workflow does not declare its triggers")
        block = triggers.group(1)
        self.assertIn("workflow_dispatch:", block)
        for forbidden in (
            "push:",
            "pull_request:",
            "pull_request_target:",
            "schedule:",
            "release:",
            "issues:",
            "workflow_call:",
            "workflow_run:",
        ):
            self.assertNotIn(forbidden, block)
        # The only dispatch input is the authorized defconfig probe. The lock,
        # not an operator, still picks the source, the feeds and the packages,
        # so no input may name any of them.
        inputs = re.search(
            r"(?m)^    inputs:\n((?:      .+\n|        .+\n)+)", block
        )
        self.assertIsNotNone(inputs, "the probe input is not declared")
        declared = re.findall(r"(?m)^      ([a-z_]+):", inputs.group(1))
        self.assertEqual(["probe_defconfig"], declared)
        for forbidden_input in ("source", "revision", "feed", "package", "device"):
            self.assertNotIn(forbidden_input, " ".join(declared))

    def test_nx30pro_firmware_workflow_pins_every_action_by_sha(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        uses = re.findall(r"(?m)^\s*uses:\s*(\S+)", workflow)

        self.assertNotEqual([], uses)
        for reference in uses:
            self.assertRegex(
                reference,
                r"^[^@]+@[0-9a-f]{40}$",
                "%s is not pinned to a commit sha" % reference,
            )

    def test_nx30pro_firmware_workflow_frees_runner_disk_before_it_builds(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        cleanup = self.workflow_step(workflow, "Free runner disk space")
        build_at = workflow.index("devices/nx30pro/build/build.sh")

        # A full buildroot build of this base peaks around 35 to 45 GB on a
        # runner that ships with about 20 GB free, so the documented failure is
        # "No space left on device" in the middle of the compile stage. Every
        # space hog the repository documents has to go, and all of it has to go
        # before the build starts.
        for hog in (
            "/usr/local/lib/android",
            "/usr/share/dotnet",
            "/opt/ghc",
            "/opt/hostedtoolcache",
            "docker image prune",
            "apt-get -qq clean",
        ):
            self.assertIn(hog, cleanup)
            self.assertLess(workflow.index(hog), build_at)
        # The freed space is evidence, and a runner that is still too small
        # stops here instead of dying in the middle of the compile stage.
        self.assertIn("df -h", cleanup)
        self.assertIn('available_kb=$(df --output=avail -k "$RUNNER_TEMP" | tail -1)', cleanup)
        self.assertIn('-lt 41943040', cleanup)
        self.assertIn("exit 1", cleanup)

    def test_nx30pro_firmware_workflow_installs_the_prerequisites_of_the_locked_source(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        step = self.workflow_step(workflow, "Install the build prerequisites")
        # Only the install command counts: a package named in a comment is not
        # installed.
        lines = step.splitlines()
        start = next(
            index for index, line in enumerate(lines) if "apt-get install" in line
        )
        command = []
        for line in lines[start:]:
            command.append(line.strip().rstrip("\\"))
            if not line.rstrip().endswith("\\"):
                break
        self.assertIn("--no-install-recommends", " ".join(command))
        packages = set(" ".join(command).split("--no-install-recommends", 1)[1].split())

        # include/prereq-build.mk of the locked source commit checks these host
        # commands, and its TestHostCommand for python3-distutils is a hard
        # gate: without that module the buildroot refuses to start at all.
        for package in (
            "build-essential",
            "bison",
            "bzip2",
            "ccache",
            "file",
            "flex",
            "gawk",
            "gettext",
            "git",
            "libelf-dev",
            "libncurses-dev",
            "libssl-dev",
            "patch",
            "python3",
            "python3-distutils",
            "python3-setuptools",
            "rsync",
            "tar",
            "unzip",
            "wget",
            "xz-utils",
            "zlib1g-dev",
        ):
            self.assertIn(package, packages)
        # The source and the feeds are fetched from GitHub over HTTPS.
        self.assertIn("ca-certificates", packages)

    def test_nx30pro_firmware_workflow_records_the_host_toolchain_identity(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        identity = self.workflow_step(workflow, "Record the host toolchain identity")

        for probe in (
            "gcc --version",
            "g++ --version",
            "make --version",
            "python3 --version",
            "git --version",
            "ccache --version",
        ):
            self.assertIn(probe, identity)
        # The identity lands in the log directory, so it survives a failed
        # build and is uploaded with the diagnostics.
        self.assertIn("firmware-artifact/logs/host-toolchain.txt", identity)
        self.assertLess(
            workflow.index("host-toolchain.txt"),
            workflow.index("--source-dir"),
        )

    def test_nx30pro_workflows_do_not_pipe_into_head_under_pipefail(self) -> None:
        """`cmd | head -1` kills the run when pipefail is on.

        Observed in the authorized probe run 46100116171: `make --version`
        wrote more than the pipe buffer holds, `head` closed it, make reported
        "write error: stdout" and the step exited 1 before the lock gate ran.
        `awk 'NR==1'` reads the whole input, so no writer gets SIGPIPE.
        """
        for name in ("build-nx30pro.yml", "build-nx30pro-uboot.yml"):
            workflow = self.workflow(name)
            self.assertNotIn("| head -", workflow, name)
            self.assertIn("set -Eeuo pipefail", workflow, name)

    def test_nx30pro_workflows_only_use_expressions_github_accepts(self) -> None:
        """The `runner` context is not available in a job level `env:`.

        A workflow that uses it there does not merely misbehave: GitHub fails to
        parse the file, rejects every dispatch with HTTP 422 and records a
        zero second failed run for each push. Steps that need the runner temp
        directory read the `$RUNNER_TEMP` shell variable instead.
        """
        for name in ("build-nx30pro.yml", "build-nx30pro-uboot.yml"):
            workflow = self.workflow(name)
            self.assertNotIn("${{ runner.", workflow, name)
            self.assertNotIn("${{ secrets.", workflow, name)

    def test_nx30pro_firmware_workflow_caps_ccache_and_pins_no_foreign_cache_dir(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")

        # An uncapped ccache is the second documented way this build fills the
        # runner disk. The documented TR3000 failure was a CONFIG_CCACHE_DIR
        # baked into the configuration that did not equal the runner's real
        # cache directory, so this workflow names exactly one cache directory
        # and no configuration layer pins another one.
        self.assertRegex(
            workflow,
            r"CCACHE_DIR: \$\{\{ github\.workspace \}\}/\.ccache-nx30pro",
        )
        self.assertIn('mkdir -p "$CCACHE_DIR"', workflow)
        self.assertIn("ccache -M 5G", workflow)
        self.assertNotIn("CONFIG_CCACHE_DIR", workflow)
        for layer in (
            "configs/common/base.config",
            "configs/common/packages.config",
            "devices/nx30pro/config.config",
        ):
            self.assertNotIn(
                "CONFIG_CCACHE_DIR",
                (ROOT / layer).read_text(encoding="utf-8"),
                layer,
            )

    def test_nx30pro_firmware_workflow_runs_repository_checks_before_the_build(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        build_at = workflow.index("--source-dir")

        validate_at = workflow.index("bash scripts/validate.sh")
        # The preflight is device scoped: another device's test set must not
        # decide whether this firmware may be built, and the repository wide
        # suite runs in validate.yml.
        tests_at = workflow.index("tests.structure.test_nx30pro_firmware_contract")
        self.assertIn("tests.scripts.test_nx30pro_firmware_build", workflow)
        self.assertIn("tests.workflows.test_workflows", workflow)
        self.assertNotIn("discover -s tests", workflow)
        self.assertLess(validate_at, build_at)
        self.assertLess(tests_at, build_at)
        # The lock gate renders the build plan before any source or feed is
        # fetched, and the plan has to name the locked source and profile.
        gate_at = workflow.index("--check-only")
        self.assertLess(gate_at, build_at)
        # The rendered plan is kept and every locked fact of this job is read
        # back from it, so the gate cannot be reduced to a no-op.
        plan_file = "$RUNNER_TEMP/firmware-build-plan.json"
        self.assertIn('--check-only $PROBE_FLAG | tee "%s"' % plan_file, workflow)
        # The probe flag comes from the dispatch input as environment data, and
        # it defaults to off, so an ordinary dispatch is a full candidate build.
        self.assertIn('PROBE_DEFCONFIG: ${{ inputs.probe_defconfig }}', workflow)
        self.assertIn('if [ "$PROBE_DEFCONFIG" = "true" ]', workflow)
        self.assertIn("default: false", workflow)
        greps = re.findall(
            r'(?m)^\s*grep -q .+ "%s"$' % re.escape(plan_file), workflow
        )
        self.assertEqual(5, len(greps))
        lock = self.nx30pro_firmware_lock()
        self.assertIn(lock["source"]["repository"], workflow)
        self.assertIn(lock["target"]["profile"], workflow)
        # The plan has to carry the 112M partition contract of the boot loader,
        # so the gate reads the locked ubi partition instead of a constant.
        ubi = next(
            entry
            for entry in lock["partition_contract"]["partitions"]
            if entry["label"] == "ubi"
        )
        self.assertIn('"label": "ubi"', workflow)
        self.assertIn('"size": %d' % ubi["size"], workflow)
        # build.sh owns the buildroot: the workflow runs no buildroot target,
        # no feed script and no configuration generation of its own.
        self.assertNotIn("scripts/feeds", workflow)
        self.assertNotIn("make defconfig", workflow)
        self.assertNotIn("make download", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s*make\s+-j")

    def test_nx30pro_firmware_workflow_pins_the_revision_as_an_argument(self) -> None:
        """The drift guard is an explicit flag, never an ambient variable.

        build.sh used to read $SOURCE_REVISION from the environment, which made
        every test that ran inside this workflow inherit the pin and fail.
        """
        workflow = self.workflow("build-nx30pro.yml")

        self.assertEqual(
            2,
            workflow.count('--pinned-revision "$SOURCE_REVISION"'),
            "both the lock gate and the build step have to pass the pin",
        )
        self.assertIn("SOURCE_REVISION: 740103d655bcee6da7bc3b49b1cfdfdee4cd5bb6", workflow)

    def test_nx30pro_firmware_workflow_calls_the_exact_build_interface(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")

        # The interface of the build script: its four required arguments plus
        # the explicit revision pin, and nothing else. No flag may change the
        # parallelism or the repository root the device patches are read from.
        self.assertRegex(
            workflow,
            r"sh devices/nx30pro/build/build\.sh \\\n"
            r"\s+--lock devices/nx30pro/source-lock\.json \\\n"
            r"\s+--source-dir [^\n]+\\\n"
            r"\s+--feed-dir [^\n]+\\\n"
            r"\s+--pinned-revision \"\$SOURCE_REVISION\" \\\n"
            r"\s+--artifact-dir [^\n]+\n",
        )
        for flag in ("--jobs", "--repo-root"):
            self.assertNotIn(flag, workflow)

    def test_nx30pro_firmware_workflow_uploads_the_whole_evidence_set_on_success_only(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        candidates = self.workflow_step(
            workflow, "Upload firmware candidates and provenance"
        )

        self.assertIn("if: success()", candidates)
        self.assertIn("nx30pro-firmware-candidate-112m", candidates)
        self.assertIn("if-no-files-found: error", candidates)
        # A green job without its evidence is not a candidate: the images, the
        # report, both locks, the image roles, the FINAL configuration, the
        # package manifest and the feed lock are all required.
        for evidence in (
            "firmware-artifact/images/",
            "firmware-artifact/build-report.json",
            "firmware-artifact/source-lock.json",
            "firmware-artifact/IMAGE-ROLES.txt",
            "firmware-artifact/final.config",
            "firmware-artifact/packages.txt",
            "firmware-artifact/feeds-lock.json",
        ):
            self.assertIn(evidence, candidates)

        diagnostics = self.workflow_step(workflow, "Upload build logs and diagnostics")
        self.assertIn("if: always()", diagnostics)
        self.assertIn("nx30pro-firmware-candidate-logs", diagnostics)
        self.assertIn("firmware-artifact/logs/", diagnostics)

    def test_nx30pro_firmware_workflow_has_no_flash_or_deploy_command(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")

        for forbidden in (
            "mtd write",
            "mtd_debug",
            "nandwrite",
            "flash_erase",
            "dd if=",
            "/dev/mtd",
            "ubiformat",
            "ubiupdatevol",
            "ubidetach",
            "tftp ",
            "scp ",
            "ssh ",
        ):
            self.assertNotIn(forbidden, workflow)
        # An image role may be named in prose; it may never be a command.
        self.assertNotRegex(workflow, r"(?m)(?:^|[;&|]\s*|\bsudo\s+)sysupgrade\b")
        self.assertNotIn("secrets:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertRegex(workflow, r"permissions:\s*\n\s+contents: read")

    def test_nx30pro_firmware_workflow_never_moves_a_source_or_feed_branch(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        lock = self.nx30pro_firmware_lock()

        # build.sh fetches the locked commits; the workflow performs no git
        # operation of its own and names no feed repository that could drift.
        self.assertNotRegex(
            workflow, r"\bgit\s+(?:clone|checkout|fetch|pull|reset|merge)\b"
        )
        self.assertNotIn("src-git", workflow)
        self.assertNotRegex(workflow, r"\b(?:master|main|openwrt-21\.02)\b")
        for feed in lock["feeds"]:
            self.assertNotIn(feed["repository"], workflow)
        # The one revision the workflow pins is the locked 40 character commit.
        pinned = re.search(r"SOURCE_REVISION: ([0-9a-f]{40})", workflow)
        self.assertIsNotNone(pinned)
        self.assertEqual(lock["source"]["revision"], pinned.group(1))

    def test_nx30pro_firmware_workflow_writes_only_inside_its_own_artifact_tree(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")

        # work/, output/ and cache/ hold generated content: a workflow that
        # writes there edits something the repository does not own.
        for generated in ("work", "output", "cache"):
            self.assertNotRegex(workflow, rf"(?m)(?:^|[\s\"'/]){generated}/")
        for target in re.findall(r"(?m)^\s*(?:sudo\s+)?mkdir -p (.+)$", workflow):
            self.assertIn(
                target.strip(),
                ('"$GITHUB_WORKSPACE/firmware-artifact/logs"', '"$CCACHE_DIR"'),
            )
        for target in re.findall(r"\btee (\S+)", workflow):
            self.assertRegex(
                target, r'^"\$(?:RUNNER_TEMP|GITHUB_WORKSPACE/firmware-artifact)'
            )

    def test_nx30pro_firmware_workflow_builds_no_other_device_and_no_boot_loader(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")

        for forbidden in (
            "devices/tr3000",
            "build-lite.sh",
            "build-full.sh",
            "build-uboot.sh",
            "uboot-source-lock.json",
            "devices/nx30pro/uboot",
            "reusable-build.yml",
            "scripts/build.sh",
        ):
            self.assertNotIn(forbidden, workflow)

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

    def test_nx30pro_firmware_workflow_offers_a_default_off_defconfig_probe(self) -> None:
        """The probe is opt-in: a normal dispatch must never run it."""
        workflow = self.workflow("build-nx30pro.yml")
        block = re.search(
            r"\n      probe_defconfig:\n(?P<body>(?:        .+\n)+)", workflow
        )

        self.assertIsNotNone(block, "the firmware workflow offers no defconfig probe input")
        self.assertIn("type: boolean", block.group("body"))
        self.assertIn("default: false", block.group("body"))

    def test_nx30pro_firmware_workflow_passes_the_probe_input_as_data(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")
        run_blocks = re.findall(r"run: \|\n((?:          .*\n)+)", workflow)

        self.assertIn("PROBE_DEFCONFIG: ${{ inputs.probe_defconfig }}", workflow)
        self.assertIn("--probe-defconfig", workflow)
        self.assertNotIn("${{ inputs.", "\n".join(run_blocks))

    def test_nx30pro_firmware_workflow_keeps_probe_evidence_and_candidate_apart(self) -> None:
        workflow = self.workflow("build-nx30pro.yml")

        # Probe evidence is kept even when the audit fails: that is its purpose.
        self.assertRegex(
            workflow,
            r"(?s)- name: Upload defconfig probe evidence.*?if: always\(\)",
        )
        self.assertIn("firmware-artifact/probe/", workflow)
        # The candidate upload stays success only, so a probe publishes no image.
        self.assertRegex(
            workflow,
            r"(?s)- name: Upload firmware candidates.*?if: success\(\)",
        )


if __name__ == "__main__":
    unittest.main()
