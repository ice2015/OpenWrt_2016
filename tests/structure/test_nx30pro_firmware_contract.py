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

# The device port of Task 2. The profile patch is applied first, so the
# numbering of the patch directory is part of the contract.
PATCHES = DEVICE / "patches"
PROFILE_PATCH = PATCHES / "0001-mediatek-add-nx30pro-112m-profile.patch"
MAC_PATCH = PATCHES / "0002-mediatek-nx30pro-wan-mac-source.patch"
PATCH_NUMBER = re.compile(r"^(\d{4})-[a-z0-9-]+\.patch$")

DEVICE_TREE_FILE = (
    "target/linux/mediatek/files-5.4/arch/arm64/boot/dts/mediatek/"
    "mt7981-h3c-nx30pro-112M.dts"
)
IMAGE_RULES_FILE = "target/linux/mediatek/image/mt7981.mk"
NETWORK_FILE = "target/linux/mediatek/mt7981/base-files/etc/board.d/02_network"

# The 112M partition table, in bytes, exactly as the boot loader locks it.
PORTED_PARTITIONS = (
    ("BL2", 0x000000, 0x100000),
    ("u-boot-env", 0x100000, 0x080000),
    ("Factory", 0x180000, 0x200000),
    ("FIP", 0x380000, 0x200000),
    ("ubi", 0x580000, 0x7000000),
)
# Partitions of the stock 64M table. They are part of the UBI area on the
# 112M layout and must not reappear in the ported device tree.
STOCK_ONLY_LABELS = ("pdt_data", "pdt_data_1", "exp", "plugin")

MAC_ADDRESS = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
# The only MAC literal the device layer may carry: the documented example of
# the deployment README. It is a placeholder, not the MAC of a device.
MAC_PLACEHOLDER = "aa:bb:cc:dd:ee:ff"

# The overlay of this device. It is copied into the rootfs by
# devices/nx30pro/build/configure.sh, so everything in it ships to the device.
OVERLAY = DEVICE / "files"
FIRST_BOOT_DEFAULTS = OVERLAY / "etc" / "uci-defaults" / "90-nx30pro-defaults"
OVERLAY_CONFIG_DIR = OVERLAY / "etc" / "config"
WAN_MAC_README = OVERLAY / "etc" / "nx30pro" / "README"

# Values that belong to one deployment and never to a build. They are scanned
# over the whole overlay, comments included: a commented out credential is
# still a credential in the repository.
IPV4_ADDRESS = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
IPV6_ADDRESS = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![\w:])")
PRIVATE_KEY_BLOCK = re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")
# Tunnel tokens, credentials files and API keys are base64 or hex blobs.
TOKEN_LITERAL = re.compile(
    r"(?<![A-Za-z0-9+/=.-])[A-Za-z0-9+/=]{24,}(?![A-Za-z0-9+/=.-])"
)
# A domain only counts in a value position; a file name such as
# /etc/cloudflared/config.yml is not one.
DOMAIN_LITERAL = re.compile(
    r"(?<![\w./-])[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}(?![\w./-])",
    re.I,
)
# `name=value`, `option name 'value'`, `list name 'value'` and `name: value`.
ASSIGNMENT = re.compile(
    r"""(?xim)
    (?:
        ^\s*(?P<shell>[A-Za-z_][\w]*)\s*=
      | \buci[^\n]*\bset\s+\S*\.(?P<uci>\w+)\s*=
      | ^\s*(?:option|list)\s+(?P<config>\w+)
      | ^\s*(?P<yaml>[A-Za-z_][\w-]*)\s*:
    )
    (?P<value>[^\n]*)
    """,
)
# Option names that only ever hold a deployment value. Writing one of them is
# only allowed with the off switch value 0, which carries no information.
DEPLOYMENT_OPTIONS = frozenset(
    (
        "token",
        "secret",
        "password",
        "passwd",
        "passphrase",
        "key",
        "psk",
        "private_key",
        "credentials_file",
        "origincert",
        "account",
        "api_key",
        "subscription",
        "domain",
        "lookup_host",
        "username",
        "server_addr",
        "ssid",
        "mac",
        "ipaddr",
    )
)

# First boot handling of every selected package that ships a service.
# `init` names the /etc/init.d scripts of the package, `switches` the UCI
# options that gate them as (package, section type, option). Both were read at
# the pinned feed commits recorded in source-lock.json:
#
#   luci-app-passwall  root/etc/init.d/{passwall,passwall_server} and
#                      root/usr/share/passwall/0_default_config
#                      (`config global` / `option enabled '0'`) plus
#                      root/etc/config/passwall_server
#                      (`config global 'global'` / `option enable '0'`).
#   ddns-scripts       files/etc/init.d/ddns, files/etc/config/ddns
#                      (`config service`), read by
#                      files/usr/lib/ddns/dynamic_dns_updater.sh, which
#                      treats a missing `enabled` as 0.
#   tailscale          files/tailscale.init of the tailscaled subpackage and
#                      files/tailscale.conf (`config settings 'settings'`):
#                      no enable option exists, only the init script gates it.
#   zerotier           files/etc/init.d/zerotier (`section_enabled` reads
#                      `enabled` of every `zerotier` section) and
#                      files/etc/config/zerotier.
#   dockerd            files/dockerd.init: no enable option, and its boot()
#                      even adds a network interface, a bridge device and a
#                      firewall zone with input ACCEPT before starting.
#   cloudflared        files/cloudflared.init (`config_get_bool enabled
#                      "config" "enabled"`) and files/cloudflared.config.
#   frpc               files/frpc.init and files/frpc.config: no enable
#                      option, and the shipped config forwards local port 22.
#   nlbwmon            files/nlbwmon.init and files/nlbwmon.config: no enable
#                      option.
#   ttyd               files/ttyd.init validates `enable:bool:1`, i.e. the web
#                      terminal is ON unless the option says otherwise.
#   sqm-scripts        section type `queue` and option `enabled`, read from
#                      luci-app-sqm/htdocs/luci-static/resources/view/network/
#                      sqm.js at the pinned luci commit; the sqm-scripts
#                      tarball itself is not part of the feed checkout.
#   etherwake          files/etherwake.init: wakes every `target` section with
#                      `wakeonboot` on, and its config template carries a MAC
#                      and a password field, so it stays off.
SELECTED_SERVICES = {
    "luci-app-passwall": {
        "init": ("passwall", "passwall_server"),
        "switches": (
            ("passwall", "global", "enabled"),
            ("passwall_server", "global", "enable"),
        ),
    },
    "ddns-scripts": {
        "init": ("ddns",),
        "switches": (("ddns", "service", "enabled"),),
    },
    "tailscale": {"init": ("tailscale",), "switches": ()},
    "zerotier": {
        "init": ("zerotier",),
        "switches": (("zerotier", "zerotier", "enabled"),),
    },
    "dockerd": {"init": ("dockerd",), "switches": ()},
    "cloudflared": {
        "init": ("cloudflared",),
        "switches": (("cloudflared", "cloudflared", "enabled"),),
    },
    "frpc": {"init": ("frpc",), "switches": ()},
    "nlbwmon": {"init": ("nlbwmon",), "switches": ()},
    "ttyd": {"init": ("ttyd",), "switches": (("ttyd", "ttyd", "enable"),)},
    "sqm-scripts": {"init": ("sqm",), "switches": (("sqm", "queue", "enabled"),)},
    "etherwake": {"init": ("etherwake",), "switches": ()},
}

# Selected packages that are not services. Each one needs a reason, so a new
# package in the lock has to be classified deliberately instead of silently
# escaping the first boot defaults.
SELECTED_NON_SERVICES = {
    "luci": "web framework, no init script of its own",
    "luci-ssl-openssl": "TLS collector of luci, no init script of its own",
    "luci-i18n-base-zh-cn": "translation package, no init script",
    "luci-theme-argon": "theme; its own uci-defaults sets luci.main.mediaurlbase",
    "luci-theme-bootstrap": "fallback theme, registered by its own uci-defaults",
    "luci-app-ddns": "LuCI view of ddns-scripts, no init script",
    "luci-app-zerotier": "LuCI view of zerotier, no init script",
    "luci-app-docker": "LuCI view of dockerd, no init script",
    "xray-core": "backend binary that passwall starts, no init script",
    "xray-plugin": "backend plugin that passwall starts, no init script",
    "docker": "command line client of dockerd, no init script",
    "fuse-overlayfs": "storage backend of dockerd, no init script",
    "ddns-scripts-cloudflare": "provider plugin of ddns-scripts, no init script",
    "openssh-sftp-server": "installs /usr/lib/sftp-server only, no init script",
    "tcpdump-mini": "command line tool, no init script",
    "iperf3": "command line tool, no init script",
    "mtr": "command line tool, no init script",
    # The baseline DNS/DHCP server is essential: an image without it has no
    # resolver, and the documented Lite failure showed how far that reaches.
    "dnsmasq-full": "baseline DNS/DHCP server, must stay enabled",
}

# UCI packages the first boot defaults must never write to: they carry the
# baseline network, wireless, firewall and management configuration.
UNTOUCHABLE_UCI_PACKAGES = (
    "network",
    "wireless",
    "firewall",
    "dhcp",
    "system",
    "dropbear",
    "uhttpd",
    "luci",
    "ucitrack",
)

# Init scripts that must not be disabled: they are the baseline of the image.
UNTOUCHABLE_SERVICES = (
    "dnsmasq",
    "network",
    "firewall",
    "system",
    "log",
    "dropbear",
    "uhttpd",
    "cron",
    "rpcd",
    "boot",
)

# Commands the target image provides. busybox of the pinned base commit
# enables mkdir, sed, echo and test and does NOT enable stat or od
# (package/utils/busybox/Config-defaults.in), which a development host has;
# uci comes from package/system/uci and is always in the image. The list is
# deliberately minimal: a new command needs new evidence, because no NX30 Pro
# image exists yet to export a verified command list from.
IMAGE_COMMANDS = frozenset(("uci", "mkdir", "sed", "echo", "["))

SHELL_BUILTINS = frozenset(
    (
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "in",
        "do",
        "done",
        "while",
        "until",
        "case",
        "esac",
        "local",
        "return",
        "set",
        "exit",
        "export",
        "unset",
        "shift",
        "read",
        "eval",
        "exec",
        "break",
        "continue",
        "true",
        "false",
        ".",
        ":",
    )
)
SEGMENT_SEPARATOR = re.compile(
    r"[;|]|\$\(|&&|\|\||\bthen\b|\bdo\b|\belse\b|\belif\b|\bif\b|\bwhile\b|\bfor\b"
)
# A word in one of these shapes is data of the script, not a command.
DATA_WORD = re.compile(r"""^[-$'"`<>(){}*?@&\d]|=""")


def shell_commands(text):
    """Return every command name a POSIX shell script runs.

    Only command positions are read: the first word of a segment after a line
    start, `;`, `|`, `&&`, `||`, `$(`, `then`, `do`, `else` or a control
    keyword. Shell builtins, the script's own functions and variables and
    expansions such as `"$script" disable` are not commands.
    """
    functions = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)", text, re.M))
    variables = set(re.findall(r"\b([A-Za-z_]\w*)=", text))
    variables.update(re.findall(r"\blocal\s+([A-Za-z_]\w*)", text))
    found = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0]
        if not line.strip():
            continue
        for segment in SEGMENT_SEPARATOR.split(line):
            words = segment.strip().split()
            while words and words[0] == "!":
                words.pop(0)
            if not words:
                continue
            word = words[0]
            if word in SHELL_BUILTINS or word in functions or word in variables:
                continue
            if "(" in word or ")" in word:
                continue
            if DATA_WORD.search(word):
                continue
            found.add(word)
    return found, functions


def patch_targets(patch_text):
    """Return the (left, right) source paths of every file a patch touches."""
    return re.findall(r"^diff --git a/(\S+) b/(\S+)$", patch_text, re.M)


def added_lines(patch_text, source_path):
    """Return the lines one patch adds to one source file, in patch order."""
    chunks = re.split(r"^diff --git ", patch_text, flags=re.M)[1:]
    for chunk in chunks:
        header = chunk.splitlines()[0]
        if not header.endswith(" b/%s" % source_path):
            continue
        return [
            line[1:]
            for line in chunk.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
    raise AssertionError("the patch does not touch %s" % source_path)


def removed_lines(patch_text, source_path):
    """Return the lines one patch removes from one source file."""
    chunks = re.split(r"^diff --git ", patch_text, flags=re.M)[1:]
    for chunk in chunks:
        header = chunk.splitlines()[0]
        if not header.endswith(" b/%s" % source_path):
            continue
        return [
            line[1:]
            for line in chunk.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
    raise AssertionError("the patch does not touch %s" % source_path)


def device_tree_partitions(dts_text):
    """Parse (label, offset, size) of every NMBM partition, in file order.

    The unit address of the node has to agree with the offset of its `reg`,
    otherwise an approximate table would still parse.
    """
    pattern = re.compile(
        r"partition@([0-9a-fA-F]+)\s*\{\s*"
        r'label\s*=\s*"([^"]+)";\s*'
        r"reg\s*=\s*<\s*([^>]+?)\s*>;\s*\};",
        re.S,
    )
    found = []
    for unit, label, register in pattern.findall(dts_text):
        values = register.split()
        assert len(values) == 2, "reg of %s is not one <offset size> pair" % label
        offset, size = int(values[0], 0), int(values[1], 0)
        assert int(unit, 16) == offset, "partition@%s is not at %#x" % (unit, offset)
        found.append((label, offset, size))
    return tuple(found)


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
        # The profile does not exist in the pinned upstream tree; it is
        # ported by the device patch and stays unproven until a build ran.
        self.assertEqual("ported-by-device-patch", target["verification"])
        self.assertIn(PROFILE_PATCH.name, target["evidence"])
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
        self.assertTrue(MAC_PATCH.is_file(), "missing %s" % MAC_PATCH)
        text = MAC_PATCH.read_text(encoding="utf-8")
        self.assertIn("pdt_data_1", text)
        self.assertIn("/etc/nx30pro/wan-mac", text)
        self.assertIn("02_network", text)

    def test_overlay_is_the_documented_first_boot_contract(self):
        """The overlay contract itself lives in Nx30ProFirmwareFirstBootOverlayTests.

        This row only keeps the two facts the device layer table states: the
        overlay is registered in the manifest and the deployment directory of
        the WAN MAC is documented.
        """
        self.assertTrue(FIRST_BOOT_DEFAULTS.is_file())
        self.assertTrue(WAN_MAC_README.is_file())
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(["devices/nx30pro/files"], manifest["overlay_layers"])

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


class Nx30ProFirmwareDevicePortTests(unittest.TestCase):
    """The 112M device port: one profile, one device tree, two image roles.

    Every assertion below reads the device patch, never a build output. The
    patch is the only place that may define the NX30 Pro 112M profile, so a
    profile copied from another device, an approximate partition size or the
    stock 64M table has to fail here.
    """

    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cls.profile_patch = PROFILE_PATCH.read_text(encoding="utf-8")
        cls.mac_patch = MAC_PATCH.read_text(encoding="utf-8")
        cls.device_tree = "\n".join(
            added_lines(cls.profile_patch, DEVICE_TREE_FILE)
        )
        cls.image_rules = "\n".join(
            added_lines(cls.profile_patch, IMAGE_RULES_FILE)
        )

    def test_patch_ordering_is_deterministic_and_unique(self):
        patches = sorted(path.name for path in PATCHES.glob("*.patch"))
        self.assertEqual(
            [PROFILE_PATCH.name, MAC_PATCH.name],
            patches,
            "the patch directory must hold exactly these two numbered patches",
        )
        numbers = []
        for name in patches:
            match = PATCH_NUMBER.match(name)
            self.assertIsNotNone(match, name)
            numbers.append(match.group(1))
        self.assertEqual(len(set(numbers)), len(numbers), "duplicate patch number")
        self.assertEqual(sorted(numbers), numbers, "the numbering is not sorted")

    def test_profile_patch_touches_only_the_nx30pro_port_files(self):
        targets = patch_targets(self.profile_patch)
        self.assertTrue(targets)
        for left, right in targets:
            self.assertEqual(left, right, "the port may not rename a source file")
        self.assertEqual(
            sorted({left for left, _ in targets}),
            sorted([DEVICE_TREE_FILE, IMAGE_RULES_FILE]),
        )

    def test_mac_patch_touches_only_the_board_network_script(self):
        targets = patch_targets(self.mac_patch)
        self.assertEqual(
            sorted({left for left, _ in targets}), [NETWORK_FILE]
        )

    def test_profile_patch_defines_exactly_one_nx30pro_profile(self):
        added = self.image_rules
        self.assertEqual(1, added.count("define Device/h3c_nx30pro_112M"))
        self.assertEqual(1, added.count("TARGET_DEVICES += h3c_nx30pro_112M"))
        self.assertEqual(1, len(re.findall(r"^\+?define Device/", added, re.M)))
        # A profile copied from another device keeps its own DTS or its own
        # supported devices; neither may appear in this port.
        self.assertNotIn("cmcc", added.lower())
        self.assertNotIn("rax3000m", added.lower())
        self.assertIn("DEVICE_DTS := mt7981-h3c-nx30pro-112M", added)
        self.assertIn("SUPPORTED_DEVICES := h3c,nx30pro", added)
        self.assertIn("DEVICE_VENDOR := H3C", added)

    def test_profile_patch_does_not_change_the_stock_64m_profile(self):
        self.assertNotIn("IMAGE_SIZE := 65536k", self.image_rules)
        for line in removed_lines(self.profile_patch, IMAGE_RULES_FILE):
            self.assertNotIn("Device/h3c_nx30pro\n", line)
        self.assertEqual([], removed_lines(self.profile_patch, DEVICE_TREE_FILE))

    def test_device_tree_carries_the_exact_112m_partition_table(self):
        self.assertEqual(
            PORTED_PARTITIONS, device_tree_partitions(self.device_tree)
        )
        contract = tuple(
            (entry["label"], entry["offset"], entry["size"])
            for entry in self.lock["partition_contract"]["partitions"]
        )
        self.assertEqual(contract, device_tree_partitions(self.device_tree))
        boot = json.loads(UBOOT_LOCK.read_text(encoding="utf-8"))
        locked = tuple(
            (entry["label"], entry["offset"], entry["size"])
            for entry in boot["layouts"]["entries"]["immortalwrt-112m"]["partitions"]
        )
        self.assertEqual(
            [(label.lower(), offset, size) for label, offset, size in locked],
            [
                (label.lower(), offset, size)
                for label, offset, size in device_tree_partitions(self.device_tree)
            ],
        )

    def test_device_tree_binds_the_partitions_to_the_nmbm_logical_device(self):
        tree = self.device_tree
        nmbm = tree.index("nmbm_spim_nand")
        self.assertIn('compatible = "generic,nmbm";', tree)
        self.assertIn("lower-mtd-device = <&spi_nand>;", tree)
        self.assertIn("forced-create;", tree)
        partitions = tree.index("partitions {")
        self.assertLess(nmbm, partitions, "the partitions are not inside the NMBM node")
        self.assertIn('compatible = "fixed-partitions";', tree[partitions:])
        # The offsets are logical NMBM addresses, so exactly one partition
        # table exists and it hangs off the NMBM device, never off the raw
        # spi-nand chip node.
        self.assertEqual(1, tree.count("partitions {"))
        self.assertLess(tree.index("lower-mtd-device = <&spi_nand>;"), partitions)

    def test_device_tree_rejects_the_stock_64m_table(self):
        tree = self.device_tree
        for label in STOCK_ONLY_LABELS:
            self.assertNotIn('label = "%s"' % label, tree, label)
        partitions = device_tree_partitions(tree)
        self.assertEqual(5, len(partitions))
        self.assertNotIn(
            0x4000000,
            [size for _, _, size in partitions],
            "the stock 64 MiB UBI size is not the 112M one",
        )
        # The table has to cover the whole 112M area without a gap.
        self.assertEqual(
            self.lock["partition_contract"]["ubi_end_offset"],
            partitions[-1][1] + partitions[-1][2],
        )

    def test_image_rules_carry_the_explicit_limit_and_distinct_roles(self):
        rules = self.image_rules
        self.assertIn("IMAGE_SIZE := 110592k", rules)
        self.assertIn("BLOCKSIZE := 128k", rules)
        self.assertIn("PAGESIZE := 2048", rules)
        self.assertIn("UBINIZE_OPTS := -E 5", rules)
        self.assertIn("KERNEL_IN_UBI := 1", rules)
        self.assertIn("IMAGES += factory.bin", rules)
        factory = "IMAGE/factory.bin := append-ubi | check-size $$$$(IMAGE_SIZE)"
        sysupgrade = "IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata"
        self.assertIn(factory, rules)
        self.assertIn(sysupgrade, rules)
        # The two roles stay distinct: a factory image is a raw UBI image with
        # a size check, a sysupgrade image is a metadata archive.
        self.assertNotEqual(factory, sysupgrade)
        self.assertNotIn("IMAGE/factory.bin := sysupgrade-tar", rules)
        self.assertNotIn("IMAGE/sysupgrade.bin := append-ubi", rules)
        image = self.lock["image"]
        self.assertEqual(110592, image["image_size_kib"])
        self.assertEqual("factory.bin", image["factory_image"])
        self.assertEqual("sysupgrade.bin", image["sysupgrade_image"])
        self.assertEqual("append-ubi | check-size $$$$(IMAGE_SIZE)", image["factory_rule"])
        self.assertEqual("sysupgrade-tar | append-metadata", image["sysupgrade_rule"])

    def test_lock_records_the_port_with_its_source_and_its_reference(self):
        port = self.lock["device_port"]
        source = self.lock["source"]
        self.assertEqual(source["revision"], port["applies_to"])
        self.assertEqual(source["port_reference"]["revision"], port["derived_from"])
        self.assertEqual(
            [PROFILE_PATCH.name, MAC_PATCH.name],
            [Path(entry["path"]).name for entry in port["patches"]],
        )
        expected_files = {
            PROFILE_PATCH.name: [DEVICE_TREE_FILE, IMAGE_RULES_FILE],
            MAC_PATCH.name: [NETWORK_FILE],
        }
        for entry in port["patches"]:
            path = ROOT / entry["path"]
            self.assertTrue(path.is_file(), entry["path"])
            self.assertEqual(source["revision"], entry["applies_to_commit"])
            self.assertTrue(entry["purpose"])
            patch_text = path.read_text(encoding="utf-8")
            self.assertEqual(
                sorted(entry["upstream_files"]),
                sorted({left for left, _ in patch_targets(patch_text)}),
                entry["path"],
            )
            self.assertEqual(
                sorted(expected_files[path.name]), sorted(entry["upstream_files"])
            )

    def test_port_stays_a_static_check_and_never_a_build_result(self):
        port = self.lock["device_port"]
        self.assertEqual("static-source-check", port["verification"])
        self.assertIn("not", port["verification_note"].lower())
        self.assertFalse(self.lock["build_readiness"]["ready"])

    def test_mac_patch_documents_a_source_that_survives_the_missing_pdt_data_1(self):
        added = added_lines(self.mac_patch, NETWORK_FILE)
        body = "\n".join(added)
        self.assertIn("/etc/nx30pro/wan-mac", body)
        # The stock source stays reachable for a device that still has it, but
        # only as a read-only fallback after the provisioned file.
        self.assertIn("mtd_get_mac_ascii pdt_data_1 ethaddr", body)
        self.assertLess(
            body.index("/etc/nx30pro/wan-mac"), body.index("pdt_data_1 ethaddr")
        )
        self.assertIn("mtd_get_mac_ascii Factory ethaddr", body)
        self.assertIn("h3c,nx30pro", body)
        # Without a MAC the interfaces keep the boot loader address and the
        # case is logged instead of deriving a wrong one.
        self.assertIn("logger", body)
        self.assertIn("provision", body)
        self.assertEqual([], [line for line in added if "ethaddr" in line and "=" not in line])
        readme = (DEVICE / "files" / "etc" / "nx30pro" / "README").read_text(
            encoding="utf-8"
        )
        self.assertIn("/etc/nx30pro/wan-mac", readme)
        self.assertIn("pdt_data_1", readme)

    def test_mac_patch_preserves_the_factory_partition(self):
        added = "\n".join(added_lines(self.mac_patch, NETWORK_FILE))
        removed = "\n".join(removed_lines(self.mac_patch, NETWORK_FILE))
        # The stock script writes a derived Wi-Fi MAC into Factory; the port
        # drops that write and keeps the calibration partition read only.
        self.assertIn("mtk_facrory_write_mac", removed)
        self.assertNotIn("mtk_facrory_write_mac", added)
        self.assertIn('mtk_factory_get_byte "Factory" 4 2', removed)
        for forbidden in ("mtd_write", "nandwrite", "flash_erase", "dd if=", "> /dev/mtd"):
            self.assertNotIn(forbidden, added, forbidden)

    def test_no_device_mac_is_embedded_in_the_device_layer(self):
        for path in (PROFILE_PATCH, MAC_PATCH, LOCK, MANIFEST, CONFIG):
            text = path.read_text(encoding="utf-8")
            self.assertEqual([], MAC_ADDRESS.findall(text), path.name)
        for path in sorted((DEVICE / "files").rglob("*")):
            if not path.is_file():
                continue
            found = MAC_ADDRESS.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(
                [MAC_PLACEHOLDER] * len(found),
                found,
                "%s carries a MAC that is not the documented placeholder" % path,
            )

    def test_wan_mac_and_calibration_facts_stay_unresolved(self):
        topics = {item["topic"]: item for item in self.lock["unresolved"]}
        self.assertTrue(
            any("WAN MAC" in topic for topic in topics), sorted(topics)
        )
        self.assertTrue(
            any("calibration" in topic.lower() for topic in topics), sorted(topics)
        )
        for topic, item in topics.items():
            self.assertEqual("UNRESOLVED", item["status"], topic)
            self.assertTrue(item["needed"], topic)

    def test_manifest_artifact_roles_match_the_ported_image_rules(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        roles = manifest["artifact_roles"]
        self.assertEqual({"factory", "sysupgrade"}, set(roles))
        image = self.lock["image"]
        self.assertEqual(image["factory_image"], roles["factory"]["suffix"])
        self.assertEqual(image["sysupgrade_image"], roles["sysupgrade"]["suffix"])
        self.assertEqual(image["factory_rule"], roles["factory"]["rule"])
        self.assertEqual(image["sysupgrade_rule"], roles["sysupgrade"]["rule"])
        self.assertNotEqual(roles["factory"]["purpose"], roles["sysupgrade"]["purpose"])
        patterns = manifest["artifact_patterns"]
        self.assertEqual(2, len(patterns))
        factory = [item for item in patterns if item.endswith("-factory.bin")]
        sysupgrade = [item for item in patterns if item.endswith("-sysupgrade.bin")]
        self.assertEqual(1, len(factory))
        self.assertEqual(1, len(sysupgrade))
        for pattern in patterns:
            self.assertIn("bin/targets/mediatek/mt7981/", pattern)
            self.assertIn("h3c_nx30pro_112M", pattern)
        # The exact file name prefix depends on build time version variables,
        # so the pattern keeps a wildcard and the lock records why.
        self.assertTrue(factory[0].startswith("bin/targets/mediatek/mt7981/*"))
        self.assertIn("UNRESOLVED", image["artifact_naming"]["exact_name"])
        self.assertIn("IMAGE_NAME", image["artifact_naming"]["rule"])


class Nx30ProDeviceConfigLayerTests(unittest.TestCase):
    """The device layer selects exactly what the lock can account for.

    `devices/nx30pro/config.config` is a seed fragment: it is merged over the
    common and the distribution layer, fed to the real `make defconfig`, and
    only the final `.config` is audited. It still has to be honest, because
    every symbol in it becomes a claim about the pinned source and feeds. A
    symbol the lock cannot account for is a guess, and a hard gate the seed
    does not select can never survive `defconfig`.
    """

    def setUp(self):
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.text = CONFIG.read_text(encoding="utf-8")
        self.enabled = set(re.findall(r"^(CONFIG_[A-Za-z0-9_-]+)=y$", self.text, re.M))
        self.disabled = set(
            re.findall(r"^# (CONFIG_[A-Za-z0-9_-]+) is not set$", self.text, re.M)
        )
        self.packages = {
            entry["package"]: entry for entry in self.lock["packages"]
        }
        self.excluded = {
            entry["package"]: entry for entry in self.lock["excluded_packages"]
        }

    def test_device_config_selects_every_hard_gate_symbol(self):
        for name in HARD_GATE_PACKAGES:
            entry = self.packages[name]
            self.assertEqual("hard", entry["gate"], name)
            self.assertTrue(entry["symbols"], name)
            for symbol in entry["symbols"]:
                self.assertIn(symbol, self.enabled, "%s of %s" % (symbol, name))
                self.assertNotIn(symbol, self.disabled, symbol)

    def test_device_config_selects_the_simplified_chinese_language_switch(self):
        """The i18n packages are HIDDEN and default to the language symbol.

        luci.mk defines `config LUCI_LANG_$(lang)` inside `Package/luci-base/
        config` and generates `luci-i18n-<base>-zh-cn` with
        `DEFAULT:=LUCI_LANG_zh_Hans||(ALL&&m)`, so the translation of every
        installed LuCI package follows the language switch.
        """
        entry = self.packages["luci-i18n-base-zh-cn"]
        self.assertIn("CONFIG_LUCI_LANG_zh_Hans", entry["symbols"])
        self.assertIn("CONFIG_LUCI_LANG_zh_Hans=y", self.text)

    def test_device_config_passwall_symbols_are_the_xray_contract(self):
        entry = self.packages["luci-app-passwall"]
        self.assertEqual(
            [
                "CONFIG_PACKAGE_luci-app-passwall",
                "CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray",
                "CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray_Plugin",
            ],
            entry["symbols"],
        )
        self.assertEqual("4.68-1", entry["version"])
        self.assertTrue(entry["version_pinned"])
        self.assertIn("PKG_VERSION", entry["version_evidence"])
        for symbol in ("CONFIG_PACKAGE_xray-core", "CONFIG_PACKAGE_xray-plugin"):
            self.assertIn(symbol, self.enabled)

    def test_device_config_attempts_every_reported_optional_tool(self):
        """The design requires the optional tools to be attempted and reported.

        An optional tool that is present in the pinned feeds is selected here,
        so `defconfig` gets the chance to drop it and the report can state the
        real outcome instead of a package nobody asked for.
        """
        for entry in self.lock["packages"]:
            if entry["gate"] != "optional" or not entry["symbols"]:
                continue
            if entry["status"] in ("unavailable", "UNRESOLVED"):
                continue
            for symbol in entry["symbols"]:
                self.assertIn(
                    symbol,
                    self.enabled,
                    "%s is reported but never attempted" % entry["package"],
                )

    def test_device_config_switches_off_every_unproven_package(self):
        """An unproven package may not ride along into the image.

        WireGuard stays UNRESOLVED on Linux 5.4 and sing-box is not in the
        pinned packages feed, so their symbols are explicit overrides instead
        of being left to whatever the upstream baseline enables.
        """
        for entry in self.lock["packages"]:
            if entry["status"] not in ("unavailable", "UNRESOLVED"):
                continue
            for symbol in entry["symbols"]:
                self.assertIn(
                    symbol,
                    self.disabled,
                    "%s is %s but not switched off" % (symbol, entry["status"]),
                )
                self.assertNotIn(symbol, self.enabled)

    def test_device_config_explicitly_overrides_every_excluded_package(self):
        for name, entry in self.excluded.items():
            symbol = "CONFIG_PACKAGE_%s" % name
            self.assertIn(
                symbol,
                self.disabled,
                "%s is excluded but not switched off" % name,
            )
            self.assertNotIn(symbol, self.enabled)
            self.assertTrue(entry["reason"], name)

    def test_device_config_resolves_both_documented_rootfs_clashes(self):
        """tcpdump and dnsmasq each install a file their full variant also installs.

        The repository documents the `check_data_file_clashes` failure for
        /usr/bin/tcpdump; `Package/dnsmasq-full` PROVIDES dnsmasq and both
        install /usr/sbin/dnsmasq, so the same clash applies. The mini/full
        variant is selected, the baseline one is switched off, and the lock
        records the replacement so a dropped replacement fails the audit
        instead of silently leaving the image without the tool.
        """
        self.assertIn("CONFIG_PACKAGE_tcpdump-mini", self.enabled)
        self.assertIn("CONFIG_PACKAGE_tcpdump", self.disabled)
        self.assertIn("CONFIG_PACKAGE_dnsmasq-full", self.enabled)
        self.assertIn("CONFIG_PACKAGE_dnsmasq", self.disabled)
        for provider, replacement in (("tcpdump", "tcpdump-mini"), ("dnsmasq", "dnsmasq-full")):
            entry = self.excluded[provider]
            self.assertEqual("CONFIG_PACKAGE_%s" % replacement, entry["replaced_by"])
            self.assertIn(replacement, entry["reason"])

    def test_device_config_names_no_symbol_the_lock_cannot_account_for(self):
        """No invented packages: every package symbol has lock evidence.

        A symbol is accounted for when it belongs to a package entry, to an
        excluded package, or to the dependency index that names its provider
        path at a pinned feed commit.
        """
        accounted = set()
        for entry in self.lock["packages"]:
            accounted.update(entry["symbols"])
        for name in self.excluded:
            accounted.add("CONFIG_PACKAGE_%s" % name)
        for dependency in self.lock["dependency_index"]:
            accounted.add("CONFIG_PACKAGE_%s" % dependency)
        accounted.update(
            {
                "CONFIG_TARGET_mediatek",
                "CONFIG_TARGET_mediatek_mt7981",
                self.lock["target"]["profile_symbol"].split("=")[0],
                "CONFIG_LUCI_LANG_zh_Hans",
            }
        )
        for symbol in sorted(self.enabled | self.disabled):
            self.assertIn(
                symbol,
                accounted,
                "%s has no evidence in the source lock" % symbol,
            )

    def test_device_config_stays_inside_the_device_target(self):
        for line in self.text.splitlines():
            if line.startswith("CONFIG_TARGET_") or line.startswith("# CONFIG_TARGET_"):
                self.assertTrue(
                    line.startswith("CONFIG_TARGET_mediatek")
                    or line.startswith("# CONFIG_TARGET_mediatek"),
                    line,
                )
        self.assertIn(self.lock["target"]["profile_symbol"], self.text)
        self.assertNotIn("tr3000", self.text.lower())

    def test_device_config_carries_no_secret_and_no_deployment_value(self):
        for forbidden in ("password", "passwd", "token", "secret", "private_key"):
            self.assertNotIn(forbidden, self.text.lower())
        self.assertNotRegex(self.text, r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

    def test_device_config_explains_its_intentional_overrides(self):
        """Native CONFIG_ syntax, and a reason next to every override."""
        for line in self.text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.assertRegex(
                line,
                r"^(CONFIG_[A-Za-z0-9_-]+)=(y|m|\"[^\"]*\"|[0-9]+)$",
                "not native OpenWrt syntax: %r" % line,
            )
        # Every `is not set` override sits under a comment that says why.
        lines = self.text.splitlines()
        for index, line in enumerate(lines):
            if not line.startswith("# CONFIG_"):
                continue
            explaining = [
                item
                for item in lines[max(0, index - 12):index]
                if item.startswith("#") and not item.startswith("# CONFIG_")
            ]
            self.assertTrue(
                explaining,
                "the override %r has no explaining comment above it" % line,
            )


class Nx30ProFirmwareFirstBootOverlayTests(unittest.TestCase):
    """First boot state of the image: services off, no deployment value.

    Everything here reads the overlay of this device and the package table of
    its source lock. No image was built and no device was touched: the
    assertions are static, and the runtime behaviour of a service stays
    UNRESOLVED until a device test says otherwise.
    """

    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cls.packages = {
            entry["package"]: entry for entry in cls.lock["packages"]
        }
        cls.text = FIRST_BOOT_DEFAULTS.read_text(encoding="utf-8")

    def selected_packages(self):
        """Every package the lock selects for this image."""
        return [
            name
            for name, entry in self.packages.items()
            if entry["status"] not in ("unavailable", "UNRESOLVED")
        ]

    def overlay_files(self):
        return sorted(path for path in OVERLAY.rglob("*") if path.is_file())

    def test_every_selected_package_is_classified_as_a_service_or_not(self):
        classified = set(SELECTED_SERVICES) | set(SELECTED_NON_SERVICES)
        selected = set(self.selected_packages())
        self.assertEqual(
            selected,
            classified,
            "a selected package is neither in SELECTED_SERVICES nor in "
            "SELECTED_NON_SERVICES, so the first boot defaults do not state "
            "what happens to it; missing: %s, unselected: %s"
            % (
                sorted(selected - classified),
                sorted(classified - selected),
            ),
        )
        self.assertEqual(
            [], sorted(set(SELECTED_SERVICES) & set(SELECTED_NON_SERVICES))
        )
        for name, entry in SELECTED_SERVICES.items():
            self.assertTrue(entry["init"], name)
        for name, reason in SELECTED_NON_SERVICES.items():
            self.assertTrue(reason, name)

    def test_first_boot_defaults_switch_every_selected_service_off(self):
        """PassWall, DDNS, Tailscale, ZeroTier, Docker, cloudflared and the rest.

        A service is off when its init script is disabled and, when the
        package gates itself through UCI, when every section of the gating
        type carries the off switch. The image enables all of them while it is
        assembled (include/rootfs.mk prepare_rootfs runs `rc.common enable`
        for every /etc/init.d script), so the symlink has to go.
        """
        for name, entry in SELECTED_SERVICES.items():
            for script in entry["init"]:
                self.assertRegex(
                    self.text,
                    r"(?m)^service_off %s$" % re.escape(script),
                    "%s: the init script %s is not disabled" % (name, script),
                )
            for package, section_type, option in entry["switches"]:
                self.assertRegex(
                    self.text,
                    r"(?m)^switch_off %s %s %s$"
                    % (re.escape(package), re.escape(section_type), re.escape(option)),
                    "%s: %s.%s is not switched off" % (name, package, option),
                )

    def test_first_boot_defaults_keep_the_essential_services_alone(self):
        for package in UNTOUCHABLE_UCI_PACKAGES:
            self.assertNotRegex(
                self.text,
                r"(?m)^(?:service_off|switch_off)\s+%s\b" % re.escape(package),
                "the first boot defaults must not switch off %s" % package,
            )
        for script in UNTOUCHABLE_SERVICES:
            self.assertNotRegex(
                self.text,
                r"(?m)^service_off %s$" % re.escape(script),
                "the first boot defaults must not disable /etc/init.d/%s" % script,
            )

    def test_first_boot_defaults_only_write_the_off_switch(self):
        """The defaults may write 0 to an enable option and nothing else.

        Any other value would be a deployment value: a node, an account, an
        interface, an address. `uci add`, `delete` and `rename` are refused as
        well, because a first boot script that rewrites a section also
        rewrites what an operator put there.
        """
        # Prose in a comment is not a command: `<uci package>` in the helper
        # documentation would otherwise read as the `uci package` subcommand.
        code = "\n".join(
            line for line in self.text.splitlines()
            if not line.lstrip().startswith("#")
        )
        subcommands = set()
        for match in re.finditer(r"\buci\s+(?:-\w+\s+)*(\w+)", code):
            subcommands.add(match.group(1))
        self.assertLessEqual(
            subcommands,
            {"show", "get", "set", "commit"},
            "the first boot defaults use a uci subcommand that changes more "
            "than an enable option",
        )
        for match in re.finditer(r"\buci\b[^\n]*\bset\b([^\n]*)", code):
            value = re.split(r"[;\n]", match.group(1))[0]
            value = re.sub(r"\bthen\b.*$", "", value).strip()
            self.assertTrue(
                value.endswith("=0") or value.endswith('=0"'),
                "the first boot defaults write %r instead of the off switch"
                % value,
            )

    def test_first_boot_defaults_guard_a_package_that_is_not_installed(self):
        """An absent package must not fail the script.

        Both helpers answer with the package's own paths: /etc/config/<name>
        for a UCI switch and /etc/init.d/<name> for a service. A package the
        probe dropped, or an optional tool that never built, leaves the file
        absent and the helper returns 0 instead of failing the first boot.
        """
        self.assertIn('[ ! -f "/etc/config/$package" ]', self.text)
        self.assertIn('[ ! -x "$script" ]', self.text)
        self.assertIn("#!/bin/sh", self.text.splitlines()[0])
        self.assertIn("set -eu", self.text)

    def test_first_boot_defaults_commit_only_the_packages_they_changed(self):
        """No blanket `uci commit`, and no write when the value already fits.

        A blanket commit would also commit the deltas of every other
        uci-defaults script of the image. Reading the current value first
        keeps a second run free of flash writes, which is what makes the file
        idempotent.
        """
        for match in re.finditer(r"\buci[^\n]*\bcommit\b([^\n]*)", self.text):
            self.assertTrue(
                match.group(1).strip().startswith('"$package"'),
                "the first boot defaults commit more than one package: %r"
                % match.group(0),
            )
        self.assertIn("mark_changed", self.text)
        self.assertRegex(self.text, r"(?m)^commit_changed$")

    def test_first_boot_defaults_are_removed_only_after_a_successful_run(self):
        """/etc/init.d/boot removes a uci-defaults script only when it returned 0.

        So this file must not delete itself and must not swallow a failure:
        the last statement is `exit 0`, every helper reports a failed write on
        stderr and returns nonzero, and `set -e` turns that into a nonzero
        exit of the sourced subshell, which keeps the file for the next boot.
        """
        self.assertEqual("exit 0", self.text.strip().splitlines()[-1].strip())
        self.assertNotIn("rm ", self.text)
        self.assertNotIn("$0", self.text)
        self.assertNotIn("|| true", self.text)
        self.assertRegex(self.text, r"(?m)^\s*echo \"nx30pro-defaults: ")
        # The documented zero byte libuci delta trap: a pending change is only
        # pending when the delta file has content, so `-e` is never enough.
        for match in re.finditer(r"\[\s*(-\w)\s+[^\n]*/tmp/\.uci", self.text):
            self.assertEqual(
                "-s",
                match.group(1),
                "a zero byte /tmp/.uci delta is not a pending change",
            )

    def test_first_boot_defaults_use_only_commands_of_the_target_image(self):
        """No applet the target busybox lacks.

        The documented Lite failure was a script that called `stat` and `od`
        on a device whose busybox has neither. The NX30 Pro command list is
        not verified yet because no image exists, so the allowlist holds only
        what the pinned base enables by default plus uci.
        """
        commands, functions = shell_commands(self.text)
        unknown = commands - IMAGE_COMMANDS - SHELL_BUILTINS - functions
        self.assertEqual(
            set(),
            unknown,
            "the first boot defaults call commands the image is not proven to "
            "provide; extend IMAGE_COMMANDS only with evidence from the "
            "pinned base or a verified image",
        )

    def test_first_boot_defaults_explain_the_deployment_placeholders(self):
        """cloudflared and DDNS are documented, not configured.

        The tunnel token and the DDNS provider, domain and password belong to
        one deployment. The defaults say where they go and that they never
        enter the image, and they write no value of them.
        """
        self.assertIn("cloudflared", self.text)
        self.assertIn("config.yml", self.text)
        self.assertIn("ddns", self.text)
        self.assertIn("deployment", self.text.lower())

    def test_overlay_carries_no_tunnel_token_domain_credential_or_address(self):
        for path in self.overlay_files():
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(OVERLAY).as_posix()
            self.assertEqual(
                [],
                IPV4_ADDRESS.findall(text),
                "%s carries an IP address" % relative,
            )
            self.assertEqual(
                [],
                IPV6_ADDRESS.findall(text),
                "%s carries an IPv6 address" % relative,
            )
            self.assertEqual(
                [],
                PRIVATE_KEY_BLOCK.findall(text),
                "%s carries private key material" % relative,
            )
            self.assertEqual(
                [],
                TOKEN_LITERAL.findall(text),
                "%s carries a token shaped literal" % relative,
            )
            found = MAC_ADDRESS.findall(text)
            if path != WAN_MAC_README:
                self.assertEqual(
                    [], found, "%s carries a MAC address" % relative
                )
            else:
                self.assertEqual(
                    [MAC_PLACEHOLDER] * len(found),
                    found,
                    "%s carries a MAC that is not the documented placeholder"
                    % relative,
                )
            for match in ASSIGNMENT.finditer(text):
                name = (
                    match.group("shell")
                    or match.group("uci")
                    or match.group("config")
                    or match.group("yaml")
                )
                value = match.group("value").strip().strip("'\"")
                if not value or value in ("0", '""', "''"):
                    continue
                self.assertEqual(
                    [],
                    DOMAIN_LITERAL.findall(value),
                    "%s assigns a domain to %s" % (relative, name),
                )
                self.assertNotIn(
                    name.lower(),
                    DEPLOYMENT_OPTIONS,
                    "%s assigns a value to the deployment option %s"
                    % (relative, name),
                )

    def test_overlay_ships_no_wireless_or_network_configuration(self):
        """No wholesale replacement of a baseline configuration file.

        The documented Lite failure replaced /etc/config/network and lost the
        `loopback` section, which took the device's own resolver, its clock
        and every TLS download with it. This overlay ships no /etc/config
        file at all: every selected service installs its own conffile, and a
        copy here would replace it during rootfs assembly and be ambiguous
        across a sysupgrade. If a template ever becomes necessary, a network
        template has to keep loopback.
        """
        if not OVERLAY_CONFIG_DIR.is_dir():
            return
        for path in sorted(OVERLAY_CONFIG_DIR.rglob("*")):
            if not path.is_file() or path.name != "network":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIn("config interface 'loopback'", text)
            for option in ("device 'lo'", "proto 'static'", "ipaddr '127.0.0.1'"):
                self.assertIn(option, text)


if __name__ == "__main__":
    unittest.main()
