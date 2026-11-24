import os
import io
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tarfile
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
    "configure-full.sh",
    "build-lite.sh",
    "build-full.sh",
    "verify-image.sh",
    "service-toggle.sh",
    "singbox-rollback.sh",
    "build-uboot.sh",
    "preflight.sh",
    "plant-profile.sh",
    "plant-access.sh",
    "lite-uplink-watch.sh",
    "tr3000-lite-uplink-watch.sh",
    "tr3000-lite-uplink-changed.sh",
    "tr3000-lite-uplink-status.sh",
    "tr3000-lite-remote.sh",
    "tr3000-lite-remote-boot-close.sh",
    "tr3000-lite-ddns-status.sh",
    "tr3000-lite-ddns-event.sh",
    "tr3000-lite-enroll.sh",
    "tr3000-lite-plant.sh",
    "tr3000-lite-plant-lib.sh",
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
        "ca-bundle", "coreutils-stat", "curl", "ip-full", "iputils-arping", "kmod-usb-net",
        "kmod-usb-net-cdc-ether", "kmod-usb-net-rndis", "kmod-wireguard",
        "luci", "luci-app-tr3000-lite", "luci-i18n-base-zh-cn", "luci-proto-wireguard",
        "luci-ssl-openssl", "openssh-server", "openssh-sftp-server",
        "tcpdump-mini", "ubi-utils", "wireguard-tools", "wpad-openssl",
        "ddns-scripts", "ddns-scripts-cloudflare", "luci-app-ddns",
    )
    lines = [
        "CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y",
        'CONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"',
        'CONFIG_CCACHE_DIR="/workdir/.ccache"',
        "CONFIG_BUSYBOX_CUSTOM=y",
        "CONFIG_BUSYBOX_CONFIG_TIMEOUT=y",
    ]
    lines.extend(f"CONFIG_PACKAGE_{package}=y" for package in required_packages)
    return "\n".join(lines) + "\n"


def uci_sections(contents: str) -> list[dict]:
    """Read the sections/options emitted in an installed UCI config."""
    sections = []
    for line in contents.splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        if tokens[0] == "config":
            section = {".type": tokens[1], ".name": tokens[2] if len(tokens) > 2 else None}
            sections.append(section)
        elif tokens[0] == "option":
            section[tokens[1]] = tokens[2]
        elif tokens[0] == "list":
            section.setdefault(tokens[1], []).append(tokens[2])
        else:
            raise ValueError(f"Unsupported UCI line: {line}")
    return sections


def run_lite_configure(
    base_contents: str,
    *,
    seed_contents: str | None = None,
    ccache_dir: str | None = None,
    repo_root: Path = ROOT,
) -> tuple[subprocess.CompletedProcess[str], str, dict[str, str]]:
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
        fake_make.write_text("#!/bin/sh\n" + (
            "test -f package/luci-app-tr3000-lite/Makefile || exit 19\n"
            if (repo_root / "packages/luci-app-tr3000-lite").is_dir() else ""
        ) + "exit 0\n", encoding="utf-8")
        fake_make.chmod(0o755)
        environment = dict(os.environ)
        environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
        arguments = [
            bash_executable(),
            (repo_root / "scripts/configure-lite.sh").as_posix(),
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
        installed_assets = {
            path.relative_to(source).as_posix(): path.read_text(encoding="utf-8")
            for path in source.rglob("*")
            if path.is_file() and path.relative_to(source).parts[0] in ("files", "package")
        }
    return result, generated_config, installed_assets


def full_base_config() -> str:
    required_packages = (
        "ca-bundle", "curl", "ip-full", "iputils-arping", "kmod-tun",
        "kmod-usb-net", "kmod-usb-net-cdc-ether", "kmod-usb-net-rndis",
        "kmod-wireguard", "luci", "luci-app-tr3000-full",
        "luci-i18n-base-zh-cn", "luci-proto-wireguard", "luci-ssl-openssl",
        "luci-theme-bootstrap", "openssh-server", "openssh-sftp-server",
        "tcpdump-mini", "ubi-utils", "wireguard-tools",
        "luci-app-homeproxy", "luci-i18n-homeproxy-zh-cn", "ucode-mod-digest",
        "luci-app-ddns", "ddns-scripts", "ddns-scripts-cloudflare",
        "luci-i18n-ddns-zh-cn", "luci-app-cloudflared", "luci-i18n-cloudflared-zh-cn",
        "luci-theme-argon", "luci-app-argon-config", "luci-i18n-argon-config-zh-cn",
        "wpad-openssl", "sing-box",
    )
    lines = [
        "CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y",
        'CONFIG_CCACHE_DIR="/workdir/.ccache"',
        "CONFIG_BUSYBOX_CUSTOM=y",
        "CONFIG_BUSYBOX_CONFIG_TIMEOUT=y",
    ]
    lines.extend(f"CONFIG_PACKAGE_{package}=y" for package in required_packages)
    return "\n".join(lines) + "\n"


def run_full_configure(
    base_contents: str,
    *,
    seed_contents: str | None = None,
    ccache_dir: str | None = None,
    include_tailscale: str | None = None,
    include_singbox: str | None = None,
    include_cloudflared: str | None = None,
    dts_contents: str = "reg = <0x5c0000 0x7000000>;\n",
) -> tuple[subprocess.CompletedProcess[str], str, dict[str, str]]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        (source / "scripts").mkdir(parents=True)
        dts = source / "target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
        dts.parent.mkdir(parents=True)
        dts.write_text(dts_contents, encoding="utf-8")
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
            (ROOT / "scripts/configure-full.sh").as_posix(),
            "--source-dir", source.as_posix(),
            "--base-config", base_config.as_posix(),
        ]
        if seed_contents is not None:
            seed = root / "full.seed"
            seed.write_text(seed_contents, encoding="utf-8")
            arguments.extend(("--seed", seed.as_posix()))
        for option, value in (
            ("--ccache-dir", ccache_dir),
            ("--include-tailscale", include_tailscale),
            ("--include-singbox", include_singbox),
            ("--include-cloudflared", include_cloudflared),
        ):
            if value is not None:
                arguments.extend((option, value))

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
        installed_assets = {
            path.relative_to(source).as_posix(): path.read_text(encoding="utf-8")
            for path in source.rglob("*")
            if path.is_file()
        }
    return result, generated_config, installed_assets


class ScriptInterfaceTests(unittest.TestCase):
    def test_lite_selects_hard_ddns_worker_timeout_applet(self):
        result, config, _ = run_lite_configure(lite_base_config())
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertIn('CONFIG_BUSYBOX_CUSTOM=y',config)
        self.assertIn('CONFIG_BUSYBOX_CONFIG_TIMEOUT=y',config)

    def test_lite_requires_only_pinned_wpad_provider(self):
        result, config, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('CONFIG_PACKAGE_wpad-openssl=y', config)
        self.assertIn('files/etc/uci-defaults/91-tr3000-lite-management-ap', assets)
        for provider in ('wpad-basic-mbedtls', 'wpad-mbedtls', 'wpad-basic-openssl', 'wpad-wolfssl'):
            with self.subTest(provider=provider):
                result, _, _ = run_lite_configure(lite_base_config()+'CONFIG_PACKAGE_'+provider+'=y\n')
                self.assertNotEqual(0, result.returncode)
        result, _, _ = run_lite_configure(lite_base_config().replace('CONFIG_PACKAGE_wpad-openssl=y\n', ''), seed_contents='')
        self.assertNotEqual(0, result.returncode)

    def test_lite_config_installs_and_requires_industrial_lan_package(self) -> None:
        result, config, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("package/luci-app-tr3000-lite/Makefile", list(assets))
        self.assertEqual(1, config.splitlines().count("CONFIG_PACKAGE_luci-app-tr3000-lite=y"))
        self.assertNotIn("package/luci-app-tr3000-full/Makefile", assets)
        result, _, _ = run_lite_configure(lite_base_config().replace("CONFIG_PACKAGE_luci-app-tr3000-lite=y\n", ""), seed_contents="")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("required Lite package was not selected: luci-app-tr3000-lite", result.stderr)

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
            "configure-full.sh",
            "build-lite.sh",
            "build-full.sh",
            "verify-image.sh",
            "service-toggle.sh",
            "singbox-rollback.sh",
            "build-uboot.sh",
            "preflight.sh",
            "plant-profile.sh",
            "plant-access.sh",
            "lite-common.sh",
            "lite-uplink-watch.sh",
            "tr3000-lite-plant.sh",
            "tr3000-lite-plant-lib.sh",
            "tr3000-lite-usbwan-lib.sh",
            "tr3000-lite-uplink-watch.sh",
            "tr3000-lite-uplink-lib.sh",
            "tr3000-lite-uplink-changed.sh",
            "tr3000-lite-uplink-status.sh",
            "tr3000-lite-remote-lib.sh",
            "tr3000-lite-remote.sh",
            "tr3000-lite-remote-boot-close.sh",
            "tr3000-lite-ddns-status.sh",
            "tr3000-lite-ddns-lib.sh",
            "../overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-remote",
            "../overlays/devices/tr3000-lite/files/etc/hotplug.d/iface/96-tr3000-lite-remote-sync",
            "../overlays/devices/tr3000-lite/files/etc/hotplug.d/iface/95-tr3000-lite-uplink-reconcile",
            "../overlays/devices/tr3000-lite/files/etc/init.d/lite-uplink-watch",
            "../overlays/devices/tr3000-lite/files/etc/hotplug.d/net/90-tr3000-lite-usbwan",
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

    def test_verify_image_accepts_only_gated_ubootmod_sysupgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            dts = source / "target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
            dts.parent.mkdir(parents=True)
            dts.write_text("reg = <0x5c0000 0x7000000>;\n", encoding="utf-8")
            (source / ".config").write_text(
                "CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y\n",
                encoding="utf-8",
            )
            image = root / "immortalwrt-cudy_tr3000-v1-ubootmod-squashfs-sysupgrade.bin"
            with tarfile.open(image, "w") as archive:
                payload = b"BOARD=cudy_tr3000-v1-ubootmod\n"
                info = tarfile.TarInfo("sysupgrade-cudy_tr3000-v1-ubootmod/CONTROL")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

            result = run_script(
                "verify-image.sh",
                "--source-dir", source.as_posix(),
                "--image", image.as_posix(),
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("verified", result.stdout.lower())

    def test_verify_image_rejects_wrong_name_invalid_archive_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            dts = source / "target/linux/mediatek/dts/mt7981b-cudy-tr3000-v1-ubootmod.dts"
            dts.parent.mkdir(parents=True)
            dts.write_text("reg = <0x5c0000 0x7000000>;\n", encoding="utf-8")
            (source / ".config").write_text(
                "CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3000-v1-ubootmod=y\n",
                encoding="utf-8",
            )
            wrong_name = root / "factory.bin"
            wrong_name.write_bytes(b"not-a-sysupgrade")
            invalid_archive = root / "cudy_tr3000-v1-ubootmod-sysupgrade.bin"
            invalid_archive.write_bytes(b"not-a-tar")
            oversized = root / "other-cudy_tr3000-v1-ubootmod-sysupgrade.bin"
            oversized.write_bytes(b"x" * 33)

            wrong_name_result = run_script(
                "verify-image.sh", "--source-dir", source.as_posix(),
                "--image", wrong_name.as_posix(),
            )
            archive_result = run_script(
                "verify-image.sh", "--source-dir", source.as_posix(),
                "--image", invalid_archive.as_posix(), "--max-bytes", "64",
            )
            size_result = run_script(
                "verify-image.sh", "--source-dir", source.as_posix(),
                "--image", oversized.as_posix(), "--max-bytes", "32",
            )

        self.assertNotEqual(0, wrong_name_result.returncode)
        self.assertIn("filename", wrong_name_result.stderr.lower())
        self.assertNotEqual(0, archive_result.returncode)
        self.assertIn("archive", archive_result.stderr.lower())
        self.assertNotEqual(0, size_result.returncode)
        self.assertIn("size", size_result.stderr.lower())

    def test_lite_config_merge_handles_hyphenated_package_symbols(self) -> None:
        base_config = (
            lite_base_config()
            + "CONFIG_PACKAGE_luci-app-openclash=y\n"
        )
        seed = (
            "# CONFIG_PACKAGE_luci-app-openclash is not set\n"
            "CONFIG_PACKAGE_luci-i18n-base-zh-cn=y\n"
        )
        result, generated_config, _ = run_lite_configure(
            base_config,
            seed_contents=seed,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CONFIG_PACKAGE_luci-i18n-base-zh-cn=y", generated_config)
        self.assertNotIn("CONFIG_PACKAGE_luci-app-openclash=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_luci=y", generated_config)

    def test_lite_config_uses_requested_ccache_directory(self) -> None:
        requested_cache = "/tmp/openwrt-test-ccache"
        result, generated_config, _ = run_lite_configure(
            lite_base_config(),
            ccache_dir=requested_cache,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(f'CONFIG_CCACHE_DIR="{requested_cache}"', generated_config)
        self.assertNotIn('CONFIG_CCACHE_DIR="/workdir/.ccache"', generated_config)

    def test_lite_config_selects_cloudflare_ddns_packages(self) -> None:
        packages=("ddns-scripts", "ddns-scripts-cloudflare", "luci-app-ddns")
        base=lite_base_config()
        for package in packages:
            base=base.replace(f"CONFIG_PACKAGE_{package}=y\n", "")
        result, config, assets=run_lite_configure(base)
        self.assertEqual(0,result.returncode,result.stderr)
        for package in packages:
            self.assertIn(f"CONFIG_PACKAGE_{package}=y",config.splitlines())
        self.assertIn("files/etc/config/ddns",assets)
        sections=uci_sections(assets["files/etc/config/ddns"])
        self.assertEqual(1,len(sections))
        service=sections[0]
        self.assertEqual("service",service[".type"])
        self.assertEqual("tr3000_direct",service[".name"])
        self.assertEqual("0",service["enabled"])
        self.assertEqual("0",service["use_ipv6"])
        self.assertEqual("1",service["use_https"])
        self.assertEqual("cloudflare.com-v4",service["service_name"])
        self.assertEqual({".type",".name","enabled","use_ipv6","use_https","service_name"},set(service),
                         "generic DDNS must contain no hostname/token/zone or credential placeholders")

    def test_lite_config_requires_each_pinned_ddns_package_after_defconfig(self) -> None:
        for package in ("ddns-scripts", "ddns-scripts-cloudflare", "luci-app-ddns"):
            with self.subTest(package=package):
                result,_,_=run_lite_configure(
                    lite_base_config().replace(f"CONFIG_PACKAGE_{package}=y\n", ""), seed_contents="")
                self.assertNotEqual(0,result.returncode)
                self.assertIn(f"required Lite package was not selected: {package}",result.stderr)

    def test_lite_config_installs_lite_overlay_after_shared_files(self) -> None:
        result, _, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        network = {s[".name"]: s for s in uci_sections(assets["files/etc/config/network"])}
        self.assertEqual("static", network["lan"]["proto"])
        self.assertEqual("br-lan", network["lan"]["device"])
        self.assertEqual("192.168.10.1", network["lan"]["ipaddr"])
        self.assertEqual("255.255.255.0", network["lan"]["netmask"])
        self.assertEqual("none", network["plant"]["proto"])
        self.assertNotIn("device", network["plant"])
        self.assertNotIn("mgmt", network)
        bridges = [s for s in network.values() if s[".type"] == "device"]
        self.assertEqual(1, len(bridges))
        self.assertEqual("br_lan", bridges[0][".name"])
        self.assertEqual("br-lan", bridges[0]["name"])
        self.assertEqual("bridge", bridges[0]["type"])
        self.assertEqual(["eth1"], bridges[0]["ports"])
        dhcp = {s[".name"]: s for s in uci_sections(assets["files/etc/config/dhcp"])}
        self.assertEqual("1", dhcp["plant"]["ignore"])
        for service in ("dhcpv4", "dhcpv6", "ra", "ndp"):
            self.assertEqual("disabled", dhcp["plant"][service])
        self.assertEqual("100", dhcp["lan"]["start"])
        self.assertEqual("150", dhcp["lan"]["limit"])
        self.assertNotIn("mgmt", dhcp)
        # The retired policy file is gone; the firewall sections carry the policy.
        self.assertNotIn("files/etc/config/tr3000-lite", assets)
        firewall = uci_sections(assets["files/etc/config/firewall"])
        sections = {s[".name"]: s for s in firewall if s[".name"]}
        luci = sections["tr3000_lite_plant_luci"]
        for option, value in (("src", "plant"), ("proto", "tcp"), ("dest_port", "443"), ("enabled", "0"), ("target", "ACCEPT")):
            self.assertEqual(value, luci[option])
        self.assertNotIn("dest", luci)
        zones = {s["name"]: s for s in firewall if s[".type"] == "zone"}
        self.assertIn("plant", zones)
        self.assertEqual("REJECT", zones["plant"]["input"])
        self.assertEqual("REJECT", zones["plant"]["forward"])
        self.assertEqual("REJECT", zones["plant"]["output"])
        self.assertFalse(any(s[".type"] == "forwarding" and s["src"] == "plant" for s in firewall))
        self.assertEqual(
            [],
            [s for s in firewall if s[".type"] == "rule" and s.get("src") == "plant"
             and s.get("target") == "ACCEPT" and s.get("enabled", "1") != "0"],
        )
        # The Full-era single-tunnel helpers bypass the paired transaction and
        # must not reach the Lite image; only the read-only preflight ships.
        self.assertNotIn("files/root/scripts/plant-profile.sh", assets)
        self.assertNotIn("files/root/scripts/plant-access.sh", assets)
        self.assertNotIn("files/etc/uci-defaults/95-tr3000-full-services", assets)
        self.assertIn("files/root/scripts/preflight.sh", assets)
        self.assertIn("files/etc/ssh/sshd_config.d/99-tr3000-lite.conf", assets)
        self.assertNotIn("files/etc/config/tr3000-lite", assets)
        self.assertEqual((ROOT / "files/etc/config/ubihealthd").read_text(encoding="utf-8"), assets["files/etc/config/ubihealthd"])

        full_result, _, full_assets = run_full_configure(full_base_config())
        self.assertEqual(0, full_result.returncode, full_result.stderr)
        for config in ("network", "dhcp", "firewall"):
            self.assertEqual((ROOT / f"overlays/devices/tr3000-full/files/etc/config/{config}").read_text(encoding="utf-8"), full_assets[f"files/etc/config/{config}"])
        self.assertNotIn("files/etc/config/tr3000-lite", full_assets)
        self.assertFalse(any("tr3000-lite" in path for path in full_assets))
        for retired in ("plant-profile.sh", "plant-access.sh", "singbox-rollback.sh"):
            self.assertNotIn(f"files/root/scripts/{retired}", full_assets)

    def test_lite_config_installs_reachable_access_segment(self) -> None:
        result, _, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        network = assets["files/etc/config/network"]
        self.assertIn("config interface 'lan'", network)
        self.assertIn("option ipaddr '192.168.10.1'", network)
        self.assertIn("config device 'br_lan'", network)
        self.assertIn("list ports 'eth1'", network)
        dhcp = assets["files/etc/config/dhcp"]
        self.assertIn("config dhcp 'lan'", dhcp)
        self.assertIn("option limit '150'", dhcp)
        self.assertNotIn("mgmt", network)
        self.assertNotIn("mgmt", dhcp)

    def test_lite_config_rejects_missing_device_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for subdir in ("scripts", "configs", "files"):
                shutil.copytree(ROOT / subdir, repo / subdir)
            result, _, assets = run_lite_configure(lite_base_config(), repo_root=repo)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Lite overlay not found", result.stderr)
        self.assertEqual({}, assets)

    def test_lite_installs_the_wireless_self_healing_controller(self) -> None:
        result, _, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        for path in ("files/usr/sbin/tr3000-lite-wifi",
                     "files/usr/sbin/tr3000-lite-wifi-ap",
                     "files/etc/init.d/tr3000-lite-wifi"):
            self.assertIn(path, assets, "missing wireless self-healing asset: " + path)
        self.assertIn("tr3000-lite-wifi repair", assets["files/etc/init.d/tr3000-lite-wifi"])

    def test_lite_installs_fixed_plant_controller(self) -> None:
        result, _, assets = run_lite_configure(lite_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("files/usr/sbin/tr3000-lite-plant", assets)
        self.assertIn("files/usr/lib/tr3000-lite/plant-lib.sh", assets)

    def test_full_config_defaults_include_singbox_and_cloudflared_only(self) -> None:
        base = (
            full_base_config()
            + "CONFIG_PACKAGE_tailscale=y\n"
            + "CONFIG_PACKAGE_sing-box=y\n"
            + "CONFIG_PACKAGE_cloudflared=y\n"
            + "CONFIG_PACKAGE_luci-theme-aurora=y\n"
            + "CONFIG_PACKAGE_luci-app-openclash=y\n"
        )

        result, generated_config, _ = run_full_configure(base)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("CONFIG_PACKAGE_tailscale=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_sing-box=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_cloudflared=y", generated_config)
        self.assertNotIn("CONFIG_PACKAGE_luci-theme-aurora=y", generated_config)
        self.assertNotIn("CONFIG_PACKAGE_luci-app-openclash=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_luci-theme-bootstrap=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_luci-theme-argon=y", generated_config)

    def test_full_config_selects_the_home_router_package_set(self) -> None:
        result, config, _ = run_full_configure(full_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        for package in ("luci-app-homeproxy", "ucode-mod-digest", "ddns-scripts-cloudflare",
                        "luci-theme-argon", "wpad-openssl", "sing-box"):
            self.assertIn(f"CONFIG_PACKAGE_{package}=y", config)
        self.assertNotIn("CONFIG_PACKAGE_luci-theme-aurora=y", config)

    def test_full_config_requires_each_home_router_package_after_defconfig(self) -> None:
        for package in ("ucode-mod-digest", "ddns-scripts-cloudflare",
                        "luci-theme-argon", "wpad-openssl"):
            with self.subTest(package=package):
                result, _, _ = run_full_configure(
                    full_base_config().replace(f"CONFIG_PACKAGE_{package}=y\n", ""),
                    seed_contents="")
                self.assertNotEqual(0, result.returncode)
                self.assertIn(f"required Full package was not selected: {package}", result.stderr)

    def test_full_singbox_switch_off_also_removes_homeproxy(self) -> None:
        # HomeProxy depends on sing-box; with the switch off, defconfig would
        # drop it, so the seed/gates must not hard-require it.
        result, config, _ = run_full_configure(full_base_config(), include_singbox="false")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("CONFIG_PACKAGE_sing-box=y", config)
        self.assertNotIn("CONFIG_PACKAGE_luci-app-homeproxy=y", config)
        self.assertNotIn("CONFIG_PACKAGE_luci-i18n-homeproxy-zh-cn=y", config)
        result, config, _ = run_full_configure(full_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CONFIG_PACKAGE_luci-app-homeproxy=y", config)

    def test_full_tailscale_defaults_off_and_switch_overrides(self) -> None:
        result, config, _ = run_full_configure(full_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("CONFIG_PACKAGE_tailscale=y", config)
        result, config, _ = run_full_configure(full_base_config(), include_tailscale="true")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CONFIG_PACKAGE_tailscale=y", config)

    def test_full_cloudflared_defaults_on_and_false_removes_it(self) -> None:
        result, config, _ = run_full_configure(full_base_config())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CONFIG_PACKAGE_cloudflared=y", config)
        result, config, _ = run_full_configure(
            full_base_config().replace("CONFIG_PACKAGE_cloudflared=y\n", ""),
            include_cloudflared="false")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("CONFIG_PACKAGE_cloudflared=y", config)

    def test_full_config_optional_switches_override_hyphenated_packages(self) -> None:
        base = full_base_config() + "CONFIG_PACKAGE_sing-box=y\n"

        result, generated_config, _ = run_full_configure(
            base,
            include_tailscale="false",
            include_singbox="false",
            include_cloudflared="true",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("CONFIG_PACKAGE_tailscale=y", generated_config)
        self.assertNotIn("CONFIG_PACKAGE_sing-box=y", generated_config)
        self.assertIn("CONFIG_PACKAGE_cloudflared=y", generated_config)

    def test_full_config_rejects_invalid_boolean_before_writing_config(self) -> None:
        result, generated_config, _ = run_full_configure(
            full_base_config(),
            include_tailscale="yes",
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("true or false", result.stderr)
        self.assertEqual("", generated_config)

    def test_full_config_uses_requested_ccache_directory(self) -> None:
        requested_cache = "/tmp/tr3000-full-ccache"

        result, generated_config, _ = run_full_configure(
            full_base_config(),
            ccache_dir=requested_cache,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(f'CONFIG_CCACHE_DIR="{requested_cache}"', generated_config)
        self.assertNotIn('CONFIG_CCACHE_DIR="/workdir/.ccache"', generated_config)

    def test_full_config_rejects_wrong_layout_before_writing_config(self) -> None:
        result, generated_config, _ = run_full_configure(
            full_base_config(),
            dts_contents="reg = <0x5c0000 0x7a40000>;\n",
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("112 MiB", result.stderr)
        self.assertEqual("", generated_config)

    def test_full_config_rejects_multiple_filogic_profiles(self) -> None:
        base = (
            full_base_config()
            + "CONFIG_TARGET_mediatek_filogic_DEVICE_other-device=y\n"
        )

        result, _, _ = run_full_configure(base)

        self.assertEqual(1, result.returncode)
        self.assertIn("exactly one", result.stderr)

    def test_full_config_installs_only_expected_runtime_management_assets(self) -> None:
        result, _, installed_assets = run_full_configure(full_base_config())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("files/usr/sbin/tr3000-full-service", installed_assets)
        self.assertIn("files/etc/uci-defaults/95-tr3000-full-services", installed_assets)
        self.assertIn("files/etc/tr3000-full/examples/cloudflared.yml.example", installed_assets)
        for retired in (
            "files/root/scripts/plant-access.sh",
            "files/root/scripts/plant-profile.sh",
            "files/root/scripts/singbox-rollback.sh",
            "files/etc/tr3000-full/examples/sing-box.json.example",
        ):
            self.assertNotIn(retired, installed_assets)
        self.assertIn(
            "package/luci-app-tr3000-full/Makefile",
            installed_assets,
        )

    def test_service_toggle_rejects_unknown_service_without_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-exist"
            result = run_script(
                "service-toggle.sh",
                "enable",
                f"../../bin/sh -c touch {marker.as_posix()}",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("unknown service", result.stderr.lower())
            self.assertFalse(marker.exists())

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
