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
    "configure-lite.sh",
    "build-lite.sh",
    "build-uboot.sh",
    "preflight.sh",
    "plant-profile.sh",
    "plant-access.sh",
    "lite-uplink-watch.sh",
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


def lite_base_config() -> str:
    required_packages = (
        "ca-bundle", "curl", "ip-full", "iputils-arping", "kmod-usb-net",
        "kmod-usb-net-cdc-ether", "kmod-usb-net-rndis", "kmod-wireguard",
        "luci", "luci-i18n-base-zh-cn", "luci-proto-wireguard",
        "luci-ssl-openssl", "openssh-server", "openssh-sftp-server",
        "tcpdump-mini", "ubi-utils", "wireguard-tools",
    )
    lines = [
        "CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y",
        'CONFIG_CCACHE_DIR="/workdir/.ccache"',
    ]
    lines.extend(f"CONFIG_PACKAGE_{package}=y" for package in required_packages)
    return "\n".join(lines) + "\n"


def run_lite_configure(
    base_contents: str,
    *,
    seed_contents: str | None = None,
    ccache_dir: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        (source / "scripts").mkdir(parents=True)
        dts = source / "target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
        dts.parent.mkdir(parents=True)
        dts.write_text("reg = <0x5c0000 0x7000000>;\n", encoding="utf-8")
        base_config = root / "base.config"
        base_config.write_text(base_contents, encoding="utf-8")
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake_make = fake_bin / "make"
        fake_make.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_make.chmod(0o755)
        environment = dict(os.environ)
        environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
        arguments = [
            bash_executable(),
            (ROOT / "scripts/configure-lite.sh").as_posix(),
            "--source-dir", source.as_posix(),
            "--base-config", base_config.as_posix(),
        ]
        if seed_contents is not None:
            seed = root / "lite.seed"
            seed.write_text(seed_contents, encoding="utf-8")
            arguments.extend(("--seed", seed.as_posix()))
        if ccache_dir is not None:
            arguments.extend(("--ccache-dir", ccache_dir))

        result = subprocess.run(
            arguments,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        generated_path = source / ".config"
        generated_config = (
            generated_path.read_text(encoding="utf-8")
            if generated_path.is_file()
            else ""
        )
    return result, generated_config


class ScriptInterfaceTests(unittest.TestCase):
    def test_every_script_supports_help(self) -> None:
        results = {name: run_script(name, "--help") for name in SCRIPTS}

        self.assertEqual(
            {name: 0 for name in SCRIPTS},
            {name: result.returncode for name, result in results.items()},
        )
        for result in results.values():
            self.assertIn("Usage:", result.stdout)

    def test_lite_shell_scripts_are_posix_syntax(self) -> None:
        scripts = (
            "configure-lite.sh",
            "build-lite.sh",
            "build-uboot.sh",
            "preflight.sh",
            "plant-profile.sh",
            "plant-access.sh",
            "lite-common.sh",
            "lite-uplink-watch.sh",
        )
        for name in scripts:
            with self.subTest(script=name):
                result = subprocess.run(
                    [bash_executable(), "-n", (ROOT / "scripts" / name).as_posix()],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_lite_config_merge_handles_hyphenated_package_symbols(self) -> None:
        base_config = (
            lite_base_config()
            + "CONFIG_PACKAGE_luci-app-openclash=y\n"
        )
        seed = (
            "# CONFIG_PACKAGE_luci-app-openclash is not set\n"
            "CONFIG_PACKAGE_luci-i18n-base-zh-cn=y\n"
        )
        result, generated_config = run_lite_configure(
            base_config,
            seed_contents=seed,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CONFIG_PACKAGE_luci-i18n-base-zh-cn=y", generated_config)
        self.assertNotIn("CONFIG_PACKAGE_luci-app-openclash=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_luci=y", generated_config)

    def test_lite_config_uses_requested_ccache_directory(self) -> None:
        requested_cache = "/tmp/openwrt-test-ccache"
        result, generated_config = run_lite_configure(
            lite_base_config(),
            ccache_dir=requested_cache,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(f'CONFIG_CCACHE_DIR="{requested_cache}"', generated_config)
        self.assertNotIn('CONFIG_CCACHE_DIR="/workdir/.ccache"', generated_config)

    def test_lite_network_input_validation(self) -> None:
        helper = (ROOT / "scripts" / "lite-common.sh").as_posix()
        command = (
            f'. "{helper}"; '
            'lite_valid_ipv4 192.168.10.254 && '
            'lite_valid_cidr 192.168.10.254/24 && '
            'lite_cidr_contains 192.168.10.0/24 192.168.10.254 && '
            'lite_cidr_matches_netmask 192.168.10.0/24 255.255.255.0 && '
            'lite_check_address_not_network_or_broadcast 192.168.10.254 24 && '
            'lite_valid_port 65535 && '
            '! lite_valid_ipv4 224.0.0.1 && '
            '! lite_valid_ipv4 192.168.010.1 && '
            '! lite_valid_cidr 192.168.10.0/08 && '
            '! lite_valid_port 0'
        )
        result = subprocess.run(
            [bash_executable(), "-c", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

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
