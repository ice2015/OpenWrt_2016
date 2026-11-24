"""Full copies of the Lite wifi trio must stay token-identical (spec D2)."""
import unittest
from tests.scripts.test_scripts import ROOT

PAIRS = [
    ("scripts/tr3000-lite-wifi.sh", "scripts/tr3000-full-wifi.sh"),
    ("overlays/devices/tr3000-lite/files/etc/uci-defaults/91-tr3000-lite-management-ap",
     "overlays/devices/tr3000-full/files/etc/uci-defaults/91-tr3000-full-management-ap"),
    ("overlays/devices/tr3000-lite/files/etc/init.d/tr3000-lite-wifi",
     "overlays/devices/tr3000-full/files/etc/init.d/tr3000-full-wifi"),
]


def rename(text: str) -> str:
    for old, new in (("tr3000-lite", "tr3000-full"),
                     ("tr3000_lite", "tr3000_full"),
                     ("TR3000-Lite", "TR3000-Full")):
        text = text.replace(old, new)
    return text


class FullWifiDriftTests(unittest.TestCase):
    def test_full_wifi_copies_match_lite_after_token_rename(self) -> None:
        for lite, full in PAIRS:
            with self.subTest(pair=full):
                expected = rename((ROOT / lite).read_text(encoding="utf-8"))
                self.assertEqual(expected, (ROOT / full).read_text(encoding="utf-8"))
