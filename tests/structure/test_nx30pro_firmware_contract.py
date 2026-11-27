"""Contract for the NX30 Pro firmware requirement document and source lock.

The requirement document is the human readable source of the approved design;
these tests keep it from drifting away from the design again. The source lock
is the only thing that ties a firmware build to a verified upstream commit and
to the feed commits it consumed. These tests keep the newly pinned hanwckf
base and its feeds reproducible, keep the rejected Galaxian base out of the
active source, keep the partition contract equal to the one the boot loader
locks, and keep the package table honest: a package that only exists in a feed
index is a candidate, never an available one, until a real ``make defconfig``
proved it.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEVICE = ROOT / "devices" / "nx30pro"
LOCK = DEVICE / "source-lock.json"
UBOOT_LOCK = DEVICE / "uboot" / "uboot-source-lock.json"
CONFIG = DEVICE / "config.config"
FEEDS = DEVICE / "feeds.conf"
MANIFEST = ROOT / "manifests" / "devices" / "nx30pro.json"
SOURCES = ROOT / "manifests" / "sources.json"
REQUIREMENT_DOC = DEVICE / "docs" / "Command_fix.md"
COMPATIBILITY_DOC = DEVICE / "docs" / "nx30pro-firmware-compatibility.md"
VALIDATION_DOC = DEVICE / "docs" / "nx30pro-firmware-install-and-validation.md"

COMMIT = re.compile(r"^[0-9a-f]{40}$")

SOURCE_REPOSITORY = "https://github.com/hanwckf/immortalwrt-mt798x"
# The 2023 tree the earlier failed Action built from. It is port reference
# evidence for the 112M profile and nothing else.
REJECTED_REPOSITORY = "https://github.com/jerryhan77/immortalwrt-mt798x.git"
REJECTED_REVISION = "78cf22edddf07443d8f0506c9f361d3498475189"

FEED_IDS = ("packages", "luci", "routing", "telephony")
PACKAGE_STATUSES = ("candidate", "available", "partial", "unavailable", "UNRESOLVED")

# The release hard gates of the approved design. Every one of them has to
# survive a real `make defconfig`, otherwise the source/feed combination is
# rejected before compilation.
HARD_GATE_PACKAGES = (
    "luci",
    "luci-ssl-openssl",
    "luci-i18n-base-zh-cn",
    "luci-theme-argon",
    "luci-theme-bootstrap",
    "luci-app-passwall",
    "xray-core",
    "xray-plugin",
    "ddns-scripts",
    "luci-app-ddns",
    "tailscale",
    "zerotier",
    "luci-app-zerotier",
    "dockerd",
    "docker",
    "luci-app-docker",
    "fuse-overlayfs",
    "cloudflared",
)

# Must be investigated and reported, but may be deferred on this old base.
OPTIONAL_PACKAGES = (
    "ddns-scripts-cloudflare",
    "frpc",
    "dnsmasq-full",
    "sqm-scripts",
    "nlbwmon",
    "etherwake",
    "ttyd",
    "openssh-sftp-server",
    "tcpdump-mini",
    "iperf3",
    "mtr",
)

# Managers the first version must not ship.
EXCLUDED_MANAGERS = (
    "luci-app-homeproxy",
    "sing-box",
    "luci-app-openclash",
    "luci-app-passwall2",
    "luci-app-adguardhome",
)

CONFIG_SYMBOL = re.compile(r"^CONFIG_[A-Za-z0-9_-]+$")


def section(text, heading):
    """Return the body of one markdown section, up to the next same level."""
    level = len(heading) - len(heading.lstrip("#"))
    pattern = re.compile(
        r"^%s\n(.*?)(?=^#{1,%d} |\Z)" % (re.escape(heading), level),
        re.S | re.M,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def bullets(body):
    """Return the list items of a section, without the surrounding prose."""
    return [line[2:].strip() for line in body.splitlines() if line.startswith("- ")]


def squash(text):
    """Compare prose without caring where the markdown wraps a line.

    The requirement document wraps its Chinese prose at a fixed column, so a
    sentence is split across lines. Both sides are squashed the same way.
    """
    return re.sub(r"\s+", "", text)


class Nx30ProRequirementDocumentTests(unittest.TestCase):
    """Command_fix.md is the requirement source; it must match the design."""

    @classmethod
    def setUpClass(cls):
        cls.text = REQUIREMENT_DOC.read_text(encoding="utf-8")
        cls.hard_gate_section = section(cls.text, "### 发布硬门禁")
        cls.hard_gates = squash(" ".join(bullets(cls.hard_gate_section)))
        cls.optional_section = section(cls.text, "### 必须调查并报告、允许延期")
        cls.optional = squash(" ".join(bullets(cls.optional_section)))
        cls.uboot = squash(section(cls.text, "## U-Boot 路线"))
        cls.layouts = squash(section(cls.text, "### 分区布局"))
        cls.actions = squash(section(cls.text, "## GitHub Actions"))
        cls.acceptance = squash(section(cls.text, "## 验收层级"))
        cls.flat = squash(cls.text)

    def assertSquashedIn(self, needle, haystack, message=None):
        self.assertIn(squash(needle), squash(haystack), message or needle)

    def assertSquashedNotIn(self, needle, haystack, message=None):
        self.assertNotIn(squash(needle), squash(haystack), message or needle)

    def test_document_sections_are_found(self):
        for name, body in (
            ("### 发布硬门禁", self.hard_gate_section),
            ("### 必须调查并报告、允许延期", self.optional_section),
            ("## U-Boot 路线", self.uboot),
            ("### 分区布局", self.layouts),
            ("## GitHub Actions", self.actions),
            ("## 验收层级", self.acceptance),
        ):
            self.assertTrue(body.strip(), "section not found: %s" % name)

    def test_hard_gates_name_the_approved_stack(self):
        for required in (
            "PassWall **4.68**",
            "Xray Core",
            "Xray Plugin",
            "Docker",
            "cloudflared",
            "LuCI",
            "HTTPS",
            "简体中文",
            "Argon",
            "Bootstrap",
            "DDNS",
            "Tailscale",
            "ZeroTier",
        ):
            self.assertSquashedIn(required, self.hard_gates)

    def test_hard_gates_stop_the_build_when_a_package_is_missing(self):
        self.assertSquashedIn("必须拒绝该源码/feeds组合", self.hard_gate_section)
        self.assertSquashedIn("不生成正式候选固件", self.hard_gate_section)
        self.assertSquashedIn("缺失", self.hard_gate_section)

    def test_boot_loader_is_the_yuzhii_fork_with_the_two_layout_whitelist(self):
        self.assertSquashedIn(
            "https://github.com/Yuzhii0718/bl-mt798x-dhcpd", self.uboot
        )
        self.assertSquashedIn("h3c_magic-nx30-pro", self.uboot)
        self.assertSquashedIn("MULTI_LAYOUT=1", self.layouts)
        self.assertSquashedIn("FIXED_MTDPARTS=1", self.layouts)
        self.assertSquashedIn("immortalwrt-112m", self.layouts)
        self.assertSquashedIn("白名单布局选择器", self.layouts)
        self.assertSquashedIn("只能选择上述两个标签", self.layouts)
        self.assertSquashedIn("不得开放任意", self.layouts)

    def test_actions_are_manual_only_and_never_flash(self):
        self.assertSquashedIn("workflow_dispatch", self.actions)
        self.assertSquashedIn("不得由push、PR或schedule自动触发", self.actions)
        self.assertSquashedIn("只有用户另行明确授权后才能触发", self.actions)
        self.assertSquashedIn("workflow不包含刷写、NAND擦除或部署命令", self.actions)
        self.assertSquashedIn("不自动执行真机刷写", self.flat)

    def test_document_does_not_require_homeproxy_or_sing_box(self):
        self.assertSquashedIn(
            "不使用HomeProxy、sing-box、OpenClash、PassWall2或AdGuardHome。",
            self.flat,
        )
        for name in ("HomeProxy", "sing-box", "PassWall2", "AdGuardHome"):
            self.assertSquashedNotIn(name, self.hard_gates, name)
            self.assertSquashedNotIn(name, self.optional, name)

    def test_document_does_not_exclude_docker(self):
        self.assertSquashedIn("Docker", self.hard_gates)
        for line in self.text.splitlines():
            if "不使用" in line or "排除" in line:
                self.assertNotIn("Docker", line, line)

    def test_document_defers_the_optional_tools_instead_of_dropping_them(self):
        for required in (
            "Cloudflare DDNS",
            "FRPC",
            "dnsmasq-full",
            "SQM",
            "NLBWMon",
            "WOL",
            "TTYD",
            "SFTP",
            "tcpdump",
            "iperf3",
            "MTR",
        ):
            self.assertSquashedIn(required, self.optional)
        self.assertSquashedIn("不能删除记录来隐藏不兼容", self.flat)

    def test_document_pins_the_hanwckf_candidate_and_rejects_the_galaxian_base(self):
        source = squash(section(self.text, "## 固件源码路线"))
        self.assertSquashedIn(
            "https://github.com/hanwckf/immortalwrt-mt798x", source
        )
        self.assertSquashedIn("openwrt-21.02", source)
        self.assertSquashedIn(
            "https://github.com/Galaxian-Explosion/nx30pro-imm-112M-nmbm", source
        )
        self.assertSquashedIn("移植证据", source)
        self.assertSquashedIn("不直接沿用其2023年commit作为构建底座", source)
        self.assertSquashedIn("必须经过真实feeds安装和`make defconfig`", source)


class Nx30ProFirmwareSourceLockTests(unittest.TestCase):
    def load_lock(self):
        self.assertTrue(LOCK.is_file(), "missing NX30 Pro source lock: %s" % LOCK)
        return json.loads(LOCK.read_text(encoding="utf-8"))

    def test_lock_pins_the_newly_selected_hanwckf_commit(self):
        source = self.load_lock()["source"]
        self.assertEqual(SOURCE_REPOSITORY, source["repository"])
        self.assertRegex(source["revision"], COMMIT)
        self.assertEqual("openwrt-21.02", source["branch"])
        self.assertTrue(source.get("commit_date"))
        self.assertTrue(source.get("selection_evidence"))

    def test_lock_rejects_the_galaxian_base_as_the_active_source(self):
        lock = self.load_lock()
        source = lock["source"]
        self.assertNotEqual(REJECTED_REVISION, source["revision"])
        self.assertNotEqual(REJECTED_REPOSITORY, source["repository"])
        rejected = {
            entry.get("repository"): entry for entry in source["rejected_sources"]
        }
        self.assertIn(REJECTED_REPOSITORY, rejected)
        entry = rejected[REJECTED_REPOSITORY]
        self.assertEqual(REJECTED_REVISION, entry["commit"])
        self.assertEqual("rejected-evidence-only", entry["status"])
        self.assertTrue(entry["reason"])
        # The port reference keeps its own record so Task 2 can cite it.
        self.assertEqual(
            REJECTED_REVISION, source["port_reference"]["revision"]
        )
        self.assertIn("Galaxian", source["port_reference"]["repository"])

    def test_lock_records_the_branch_as_informational_only(self):
        source = self.load_lock()["source"]
        note = source["branch_note"]
        self.assertIn("informational", note.lower())
        self.assertIn("never", note.lower())
        for feed in self.load_lock()["feeds"]:
            self.assertIn("informational", feed["branch_note"].lower())

    def test_lock_records_the_kernel_with_its_source_evidence(self):
        source = self.load_lock()["source"]
        self.assertEqual("5.4", source["kernel"])
        self.assertIn("KERNEL_PATCHVER", source["kernel_evidence"])
        self.assertIn("target/linux/mediatek/Makefile", source["kernel_evidence"])

    def test_every_feed_pins_a_repository_and_a_full_commit(self):
        lock = self.load_lock()
        feeds = {feed["id"]: feed for feed in lock["feeds"]}
        self.assertEqual(set(FEED_IDS), set(feeds))
        for feed_id in FEED_IDS:
            feed = feeds[feed_id]
            self.assertRegex(feed["revision"], COMMIT, feed_id)
            self.assertTrue(feed["repository"].startswith("https://"), feed_id)
            self.assertTrue(feed.get("role"), feed_id)
            self.assertTrue(feed.get("commit_date"), feed_id)
        # The old lock pinned feed commits that are not the heads of the
        # frozen 21.02 branches; a drifting or foreign commit is refused.
        self.assertNotEqual(
            "c494d5269421c94090b56a971b9796c21f808a55", feeds["packages"]["revision"]
        )
        self.assertNotEqual(
            "97b019be0a676c48ec2d804f0aace49cefcbb365", feeds["luci"]["revision"]
        )

    def test_feed_selection_records_why_these_commits_belong_to_the_source(self):
        selection = self.load_lock()["feed_selection"]
        self.assertTrue(selection["method"])
        self.assertTrue(selection["api_generation"])
        self.assertIn("frozen", selection["drift_note"].lower())

    def test_lock_stays_build_blocked_until_a_defconfig_probe_is_authorized(self):
        lock = self.load_lock()
        readiness = lock["build_readiness"]
        self.assertIs(False, readiness["ready"])
        self.assertTrue(readiness["blocking"])
        self.assertIn("defconfig", readiness["required_evidence"])
        # Nothing may claim a proven package before the probe ran.
        for entry in lock["packages"]:
            self.assertNotEqual(
                "available",
                entry["status"],
                "%s claims to be available without defconfig evidence"
                % entry["package"],
            )

    def test_lock_uses_the_same_partition_contract_as_the_boot_loader(self):
        lock = self.load_lock()
        uboot_lock = json.loads(UBOOT_LOCK.read_text(encoding="utf-8"))
        firmware = [
            (entry["label"], entry["offset"], entry["size"])
            for entry in lock["partition_contract"]["partitions"]
        ]
        boot_loader = [
            (entry["label"], entry["offset"], entry["size"])
            for entry in uboot_lock["partition_contract"]["partitions"]
        ]
        self.assertEqual(boot_loader, firmware)

    def test_partition_contract_matches_the_locked_112m_layout_table(self):
        lock = self.load_lock()
        uboot_lock = json.loads(UBOOT_LOCK.read_text(encoding="utf-8"))
        layouts = uboot_lock["layouts"]
        self.assertEqual("immortalwrt-112m", layouts["default_label"])
        self.assertEqual(
            ("default", "immortalwrt-112m"), tuple(sorted(layouts["entries"]))
        )
        locked = layouts["entries"]["immortalwrt-112m"]
        self.assertEqual(
            "nmbm0:1024k(bl2),512k(u-boot-env),2048k(Factory),2048k(fip),112M(ubi)",
            locked["mtdparts"],
        )
        contract = lock["partition_contract"]
        self.assertEqual("nmbm-logical", contract["address_space"])
        self.assertEqual(locked["end_offset"], contract["ubi_end_offset"])
        # The label case differs between the boot loader device tree and the
        # system device tree; the offsets and sizes may not.
        self.assertEqual(
            [(p["offset"], p["size"]) for p in locked["partitions"]],
            [(p["offset"], p["size"]) for p in contract["partitions"]],
        )
        self.assertEqual(
            [p["label"].lower() for p in locked["partitions"]],
            [p["label"].lower() for p in contract["partitions"]],
        )
        # The stock table is reference only and must not be the system layout.
        stock = layouts["entries"]["default"]
        self.assertEqual(67108864, stock["partitions"][4]["size"])
        self.assertNotEqual(
            [(p["offset"], p["size"]) for p in stock["partitions"]],
            [(p["offset"], p["size"]) for p in contract["partitions"]],
        )

    def test_lock_records_the_target_profile_as_a_ported_candidate(self):
        lock = self.load_lock()
        target = lock["target"]
        self.assertEqual("mediatek", target["target"])
        self.assertEqual("mt7981", target["subtarget"])
        self.assertEqual("h3c_nx30pro_112M", target["profile"])
        self.assertEqual(
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
            target["profile_symbol"],
        )
        # The profile does not exist in the pinned upstream tree yet; it is
        # ported by the device patch and stays unverified until then.
        self.assertIn("not-in-locked-source", target["verification"])
        self.assertTrue(target["evidence"])

    def test_unresolved_items_stay_listed(self):
        lock = self.load_lock()
        self.assertTrue(lock["unresolved"])
        topics = []
        for item in lock["unresolved"]:
            self.assertTrue(item.get("topic"))
            self.assertEqual("UNRESOLVED", item.get("status"))
            self.assertTrue(item.get("needed"))
            topics.append(item["topic"])
        self.assertTrue(any("WireGuard" in topic for topic in topics), topics)
        self.assertTrue(any("defconfig" in topic for topic in topics), topics)


class Nx30ProFirmwarePackageGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cls.packages = {
            entry["package"]: entry for entry in cls.lock["packages"]
        }
        cls.index = cls.lock["dependency_index"]

    def test_every_hard_gate_of_the_design_is_recorded(self):
        for name in HARD_GATE_PACKAGES:
            self.assertIn(name, self.packages, name)
            self.assertEqual("hard", self.packages[name]["gate"], name)
        for name in OPTIONAL_PACKAGES:
            self.assertIn(name, self.packages, name)
            self.assertEqual("optional", self.packages[name]["gate"], name)

    def test_no_unapproved_gate_sneaks_into_the_hard_gate_list(self):
        for name, entry in self.packages.items():
            if entry["gate"] == "hard":
                self.assertIn(name, HARD_GATE_PACKAGES, name)
            else:
                self.assertEqual("optional", entry["gate"], name)

    def test_every_package_names_exact_symbols_and_its_provider(self):
        for name, entry in self.packages.items():
            self.assertTrue(entry.get("requirement"), name)
            self.assertIn(entry["status"], PACKAGE_STATUSES, name)
            symbols = entry.get("symbols") or []
            if entry["status"] in ("unavailable", "UNRESOLVED"):
                continue
            self.assertTrue(symbols, "%s names no config symbol" % name)
            for symbol in symbols:
                self.assertRegex(symbol, CONFIG_SYMBOL, name)
            self.assertIn(entry["feed"], ("base",) + FEED_IDS, name)

    def test_every_package_pins_the_commit_that_provides_it(self):
        feeds = {feed["id"]: feed["revision"] for feed in self.lock["feeds"]}
        source_revision = self.lock["source"]["revision"]
        for name, entry in self.packages.items():
            if entry["status"] in ("unavailable", "UNRESOLVED"):
                self.assertIsNone(entry.get("feed_revision"), name)
                continue
            expected = (
                source_revision if entry["feed"] == "base" else feeds[entry["feed"]]
            )
            self.assertEqual(expected, entry["feed_revision"], name)
            self.assertTrue(entry.get("provider_path"), name)

    def test_pinned_versions_carry_their_makefile_evidence(self):
        for name, entry in self.packages.items():
            if entry.get("version_pinned"):
                self.assertTrue(entry.get("version"), name)
                self.assertIn("PKG_VERSION", entry["version_evidence"], name)
            elif entry.get("version"):
                self.assertTrue(entry.get("version_evidence"), name)

    def test_passwall_is_pinned_to_the_required_4_68_version(self):
        entry = self.packages["luci-app-passwall"]
        self.assertTrue(entry["version"].startswith("4.68"), entry["version"])
        self.assertTrue(entry["version_pinned"])
        self.assertIn("luci-app-passwall/Makefile", entry["version_evidence"])
        self.assertIn(
            "CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray", entry["symbols"]
        )
        self.assertIn(
            "CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray_Plugin", entry["symbols"]
        )

    def test_every_named_dependency_resolves_in_the_dependency_index(self):
        for name, entry in self.packages.items():
            for dependency in entry.get("dependencies") or []:
                self.assertIn(
                    dependency,
                    self.index,
                    "%s depends on %s, which no locked feed provides"
                    % (name, dependency),
                )

    def test_dependency_index_entries_are_pinned_to_a_locked_commit(self):
        feeds = {feed["id"]: feed["revision"] for feed in self.lock["feeds"]}
        source_revision = self.lock["source"]["revision"]
        for name, entry in self.index.items():
            self.assertIn(entry["provider"], ("base",) + FEED_IDS, name)
            self.assertTrue(entry.get("path"), name)
            expected = (
                source_revision if entry["provider"] == "base" else feeds[entry["provider"]]
            )
            self.assertEqual(expected, entry["revision"], name)

    def test_optional_tools_keep_a_reportable_status_and_their_gaps(self):
        for name in OPTIONAL_PACKAGES:
            entry = self.packages[name]
            self.assertIn(entry["status"], PACKAGE_STATUSES, name)
            if entry["status"] in ("partial", "unavailable", "UNRESOLVED"):
                self.assertTrue(entry.get("detail"), name)

    def test_tailscale_records_the_missing_luci_application(self):
        entry = self.packages["tailscale"]
        self.assertIn("luci-app-tailscale", entry["detail"])

    def test_rejected_managers_are_excluded_with_a_reason(self):
        excluded = {
            entry["package"]: entry for entry in self.lock["excluded_packages"]
        }
        for name in EXCLUDED_MANAGERS:
            self.assertIn(name, excluded, name)
            self.assertTrue(excluded[name]["reason"], name)
        for name in ("ruby", "libruby"):
            self.assertIn(name, excluded, name)
        for entry in self.lock["excluded_packages"]:
            self.assertTrue(entry.get("package"))
            self.assertTrue(entry.get("reason"), entry.get("package"))

    def test_wireguard_stays_unresolved_with_its_real_evidence(self):
        entry = self.packages["wireguard"]
        self.assertEqual("UNRESOLVED", entry["status"])
        # The old lock claimed the 5.4 base carries no wireguard module. The
        # pinned hanwckf tree does carry the backport, so the record has to
        # name it instead of repeating the wrong claim.
        self.assertIn("backport-5.4", entry["detail"])
        self.assertIn("kmod-wireguard", " ".join(entry["symbols"]))

    def test_services_that_are_selected_stay_disabled_by_default(self):
        defaults = DEVICE / "files" / "etc" / "uci-defaults" / "90-nx30pro-defaults"
        self.assertTrue(defaults.is_file(), "missing NX30 Pro first boot defaults")
        for entry in self.lock["packages"]:
            if entry["status"] in ("unavailable", "UNRESOLVED"):
                continue
            self.assertFalse(
                entry.get("enabled_by_default"),
                "%s must not be enabled by default" % entry["package"],
            )


class Nx30ProFirmwareDeviceLayerTests(unittest.TestCase):
    def test_device_config_selects_only_this_target_and_profile(self):
        text = CONFIG.read_text(encoding="utf-8")
        targets = [
            line
            for line in text.splitlines()
            if line.startswith("CONFIG_TARGET_")
        ]
        self.assertTrue(targets)
        for line in targets:
            self.assertTrue(line.startswith("CONFIG_TARGET_mediatek"), line)
        self.assertIn(
            "CONFIG_TARGET_mediatek_mt7981_DEVICE_h3c_nx30pro_112M=y",
            text,
        )

    def test_device_config_requires_the_packages_of_the_requirement_table(self):
        text = CONFIG.read_text(encoding="utf-8")
        for symbol in (
            "CONFIG_PACKAGE_luci-app-passwall=y",
            "CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray=y",
            "CONFIG_PACKAGE_xray-core=y",
            "CONFIG_PACKAGE_cloudflared=y",
            "CONFIG_PACKAGE_ddns-scripts=y",
            "CONFIG_PACKAGE_luci-app-ddns=y",
            "CONFIG_PACKAGE_tailscale=y",
            "CONFIG_PACKAGE_zerotier=y",
            "CONFIG_PACKAGE_luci-app-zerotier=y",
            "CONFIG_PACKAGE_dockerd=y",
            "CONFIG_PACKAGE_luci-app-docker=y",
            "CONFIG_PACKAGE_fuse-overlayfs=y",
            "CONFIG_PACKAGE_luci-theme-argon=y",
            "CONFIG_PACKAGE_luci-theme-bootstrap=y",
            "CONFIG_PACKAGE_luci-i18n-base-zh-cn=y",
        ):
            self.assertIn(symbol, text, symbol)

    def test_device_config_excludes_the_documented_packages(self):
        text = CONFIG.read_text(encoding="utf-8")
        for symbol in (
            "# CONFIG_PACKAGE_sing-box is not set",
            "# CONFIG_PACKAGE_luci-app-openclash is not set",
            "# CONFIG_PACKAGE_luci-app-wireguard is not set",
            "# CONFIG_PACKAGE_ruby is not set",
            "# CONFIG_PACKAGE_libruby is not set",
        ):
            self.assertIn(symbol, text, symbol)

    def test_feed_layer_matches_the_locked_feed_revisions(self):
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        text = FEEDS.read_text(encoding="utf-8")
        for feed in lock["feeds"]:
            self.assertIn(feed["revision"], text, feed["id"])
            self.assertIn(feed["repository"], text, feed["id"])
        # No drifting branch reference may survive in the feed layer.
        self.assertNotIn(";openwrt-21.02", text)
        self.assertNotIn(REJECTED_REVISION, text)

    def test_device_patch_carries_the_mac_provisioning(self):
        patches = sorted((DEVICE / "patches").glob("*.patch"))
        self.assertTrue(patches)
        text = patches[0].read_text(encoding="utf-8")
        self.assertIn("pdt_data_1", text)
        self.assertIn("/etc/nx30pro/wan-mac", text)
        self.assertIn("02_network", text)

    def test_overlay_keeps_every_service_switched_off(self):
        defaults = DEVICE / "files" / "etc" / "uci-defaults" / "90-nx30pro-defaults"
        self.assertTrue(defaults.is_file(), "missing NX30 Pro first boot defaults")
        text = defaults.read_text(encoding="utf-8")
        for service in ("passwall", "ddns", "tailscale", "zerotier", "docker"):
            self.assertRegex(text, r"uci -q set %s\.enabled='0'" % service, service)
        self.assertIn("/etc/nx30pro", text)

    def test_manifest_registers_the_device_with_its_own_source(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("nx30pro", manifest["id"])
        self.assertEqual(["immortalwrt-mt798x"], manifest["supported_distributions"])
        self.assertEqual("mediatek", manifest["target"])
        self.assertEqual("mt7981", manifest["subtarget"])
        self.assertEqual("h3c_nx30pro_112M", manifest["profile"])
        self.assertEqual(["devices/nx30pro/config.config"], manifest["config_layers"])
        self.assertEqual(["devices/nx30pro/feeds.conf"], manifest["feed_layers"])

    def test_manifest_keeps_the_unproven_candidate_build_blocked(self):
        """The generic build entry point must not accept an unproven source.

        `manifests/sources.json` becomes equal to the device source lock only
        after a defconfig probe proved every hard gate. Until then it keeps the
        repository wide UNRESOLVED gate closed, so `scripts/build.sh` and
        `tools/manifest.py resolve --require-build-ready` stop with status 3
        instead of downloading the rejected or unproven source.
        """
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        source = {entry["id"]: entry for entry in sources["sources"]}
        self.assertIn("immortalwrt-mt798x", source)
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        entry = source["immortalwrt-mt798x"]
        self.assertEqual(SOURCE_REPOSITORY, entry["repository"])
        if lock["build_readiness"]["ready"]:
            self.assertEqual(lock["source"]["revision"], entry["revision"])
        else:
            self.assertEqual("UNRESOLVED", entry["revision"])
            self.assertNotEqual(REJECTED_REVISION, entry["revision"])


class Nx30ProFirmwareDocumentTests(unittest.TestCase):
    def test_compatibility_document_states_the_facts_and_the_gaps(self):
        self.assertTrue(
            COMPATIBILITY_DOC.is_file(),
            "missing NX30 Pro firmware compatibility document: %s" % COMPATIBILITY_DOC,
        )
        text = COMPATIBILITY_DOC.read_text(encoding="utf-8")
        for topic in ("UNRESOLVED", "候选", "h3c_nx30pro_112M", "pdt_data_1", "sing-box"):
            self.assertIn(topic, text)
        self.assertNotIn("真机验证通过", text)

    def test_validation_document_plans_the_device_test_without_authorizing_a_flash(self):
        self.assertTrue(
            VALIDATION_DOC.is_file(),
            "missing NX30 Pro firmware validation document: %s" % VALIDATION_DOC,
        )
        text = VALIDATION_DOC.read_text(encoding="utf-8")
        for topic in ("备份", "回退", "验证", "UNRESOLVED", "授权", "wan-mac"):
            self.assertIn(topic, text)
        for forbidden in ("mtd write", "nandwrite", "flash_erase", "dd of="):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
