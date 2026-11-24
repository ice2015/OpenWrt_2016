"""Contracts for the TR3000-Lite image on real hardware.

Every check in this module was derived from a flashed device, not from the
repository. Static configuration tests cannot see the difference between "the
file says the right thing" and "the device actually works": the missing
loopback interface, the missing ``stat``/``od`` utilities, the empty libuci
delta and the hidden LuCI SSH pages were all invisible until a real unit was
booted.
"""

from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/structure"))

from shell_tools import invocations  # noqa: E402


LITE = ROOT / "overlays/devices/tr3000-lite/files"
SEED = ROOT / "configs/lite.seed"

# Every command the shipped image provides, derived from the verified baseline
# image. "stat" is added by the coreutils-stat package the seed now selects.
IMAGE_COMMANDS = ROOT / "tests/structure/lite-image-commands.txt"

# Tools that OpenWrt's busybox does not provide. A Lite controller may only
# use one of them when the seed selects the package that ships it, or when the
# image provides it another way. The image inventory is the only proof.
NON_BUSYBOX_TOOLS = {
    "stat": "coreutils-stat",
    "od": None,
    "python": None,
    "python3": None,
    "perl": None,
    "jq": None,
    "xxd": None,
    "column": None,
    "realpath": None,
    "tree": None,
    "getent": None,
    "uuidgen": None,
    "diff": None,
    "patch": None,
}


def shipped_scripts():
    """Every shell script that ends up on the device."""
    scripts = sorted((ROOT / "scripts").glob("tr3000-lite-*.sh"))
    scripts += [ROOT / "scripts/lite-common.sh", ROOT / "scripts/lite-uplink-watch.sh"]
    scripts += [LITE / "etc/uci-defaults/91-tr3000-lite-management-ap"]
    scripts += sorted((LITE / "etc/init.d").glob("*"))
    scripts += sorted((LITE / "etc/hotplug.d").rglob("*"))
    scripts += [ROOT / "files/etc/init.d/lite-uplink-watch",
                ROOT / "files/etc/uci-defaults/90-lite-uplink-watch"]
    return [script for script in scripts if script.is_file()]


class LiteDeviceReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = {
            line.strip()
            for line in IMAGE_COMMANDS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        self.scripts = shipped_scripts()

    def test_image_command_inventory_is_present(self) -> None:
        self.assertTrue(IMAGE_COMMANDS.is_file(), "missing the Lite image command inventory")
        for command in ("arping", "awk", "hexdump", "sha256sum", "stat", "uci"):
            self.assertIn(command, self.inventory, command + " is not provided by the Lite image")
        # od is not part of the OpenWrt busybox build.
        self.assertNotIn("od", self.inventory, "the Lite image must not rely on od")

    def test_shipped_scripts_only_use_tools_the_image_provides(self) -> None:
        # A tool that is neither a busybox applet nor shipped by a selected
        # package breaks the moment the controller runs on the device.
        used = {}
        for script in self.scripts:
            for tool in invocations(script.read_text(encoding="utf-8")):
                if tool in NON_BUSYBOX_TOOLS:
                    used.setdefault(tool, []).append(script.name)
        for tool, scripts in sorted(used.items()):
            if tool not in self.inventory:
                self.fail("the Lite image does not provide " + tool +
                          ", used by " + ", ".join(sorted(set(scripts))))
        seed = SEED.read_text(encoding="utf-8")
        for tool, package in sorted(NON_BUSYBOX_TOOLS.items()):
            if package and tool in used:
                self.assertIn("CONFIG_PACKAGE_" + package + "=y", seed,
                              package + " must be selected for " + tool)

    def test_lite_seed_selects_the_tools_the_controllers_call(self) -> None:
        seed = SEED.read_text(encoding="utf-8")
        # stat is not a busybox applet on OpenWrt and 27 controller call sites
        # depend on it for ownership and permission checks.
        self.assertIn("CONFIG_PACKAGE_coreutils-stat=y", seed)
        # od is not shipped at all; the controllers must use busybox instead.
        for script in self.scripts:
            self.assertNotIn("od", invocations(script.read_text(encoding="utf-8")),
                             script.name + " still calls od, which the Lite image does not ship")

    def test_lite_overlay_keeps_the_loopback_interface(self) -> None:
        # Without it dnsmasq cannot bind 127.0.0.1, the router cannot resolve
        # any name, NTP never sets the clock and every TLS download fails.
        network = (LITE / "etc/config/network").read_text(encoding="utf-8")
        self.assertIn("config interface 'loopback'", network)
        self.assertIn("option device 'lo'", network)
        self.assertIn("option ipaddr '127.0.0.1'", network)
        self.assertIn("option netmask '255.0.0.0'", network)
        build = (ROOT / "scripts/build-lite.sh").read_text(encoding="utf-8")
        self.assertIn("config interface 'loopback'", build,
                      "the build must fail before compiling when the loopback interface is missing")

    def test_empty_uci_deltas_are_not_mistaken_for_pending_changes(self) -> None:
        # uci commit leaves a zero-length /tmp/.uci/<package> behind on every
        # boot. Treating its mere presence as a pending change aborted the
        # management AP initialization and every plant transaction.
        for script in (LITE / "etc/uci-defaults/91-tr3000-lite-management-ap",
                       ROOT / "scripts/tr3000-lite-plant.sh"):
            text = script.read_text(encoding="utf-8")
            # A delta only blocks when it carries content.
            self.assertIn("-s ", text,
                          script.name + " must test the size of a libuci delta file")
            # The old guard refused on the mere existence of the file.
            for pattern in (r"!\s*-e\s+\"?/tmp/\.uci", r"!\s*-e\s+\"?\$\w*ROOT/tmp/\.uci"):
                self.assertNotRegex(text, pattern,
                                    script.name + " still refuses on the existence of a libuci delta file")

    def test_lite_ssh_accepts_the_root_password_the_operator_sets(self) -> None:
        # The image ships openssh-server, not dropbear. OpenSSH defaults to
        # "PermitRootLogin prohibit-password", so the password set in LuCI was
        # rejected and the device was reachable only through a serial console.
        dropin = LITE / "etc/ssh/sshd_config.d/99-tr3000-lite.conf"
        self.assertTrue(dropin.is_file(), "missing the Lite sshd drop-in")
        text = dropin.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^PermitRootLogin\s+yes\s*$")
        self.assertRegex(text, r"(?m)^PasswordAuthentication\s+yes\s*$")
        configure = (ROOT / "scripts/configure-lite.sh").read_text(encoding="utf-8")
        self.assertIn("99-tr3000-lite.conf", configure,
                      "the configure step must fail when the SSH drop-in is missing")

    def test_lite_image_ships_no_full_era_helpers(self) -> None:
        configure = (ROOT / "scripts/configure-lite.sh").read_text(encoding="utf-8")
        for legacy in ("plant-profile.sh", "plant-access.sh"):
            self.assertNotRegex(configure, r"install[^\n]*" + legacy.replace(".", r"\."),
                                legacy + " must not be installed into the Lite image")
        self.assertRegex(configure, r"95-tr3000-full-services",
                         "the configure step must drop the Full variant first-boot defaults")
        self.assertFalse((LITE / "etc/config/tr3000-lite").exists(),
                         "the retired /etc/config/tr3000-lite policy file is dead configuration")
        for script in sorted((ROOT / "scripts").glob("tr3000-lite-*.sh")):
            self.assertNotIn("config/tr3000-lite\"", script.read_text(encoding="utf-8"),
                             script.name + " must not read the retired policy file")

    def test_lite_artifact_ships_its_own_package_repository(self) -> None:
        build = (ROOT / "scripts/build-lite.sh").read_text(encoding="utf-8")
        self.assertIn("key-build.pub", build,
                      "the artifact must ship the build signing key")
        self.assertIn("package-repo", build,
                      "the artifact must ship the build's own opkg repository")
        self.assertIn("CONFIG_TARGET_ARCH_PACKAGES", build,
                      "the package architecture must come from the final configuration")


if __name__ == "__main__":
    unittest.main()
