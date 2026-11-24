"""Run the Full AP defaults through the Lite test harness (token-renamed).

The drift guard (test_tr3000_full_drift) proves the Full wifi trio is a pure
token rename of the Lite trio, so the Lite AP behavior suite is re-executed
here against the Full script paths and Full expected tokens. The Lite-only
ManagementGateTests (plant HTTPS gate) is deliberately not carried over:
Full has no plant controller.
"""
import unittest

from tests.scripts.test_scripts import ROOT
from tests.scripts.test_tr3000_full_drift import rename

_source = (ROOT / "tests/scripts/test_tr3000_lite_wifi.py").read_text(encoding="utf-8")
_source = rename(_source)
# The plant-test helper import must keep pointing at the real Lite module.
_source = _source.replace(
    "from tests.scripts import test_tr3000_full_plant as plant_tests",
    "from tests.scripts import test_tr3000_lite_plant as plant_tests",
)
module_globals = {
    "__name__": "tests.scripts._full_wifi_transformed",
    "__file__": str(ROOT / "tests/scripts/test_tr3000_lite_wifi.py"),
}
exec(compile(_source, module_globals["__file__"], "exec"), module_globals)


class FullManagementAPTests(module_globals["ManagementAPTests"]):
    """Every Lite AP behavior case, exercised on the Full script."""

    def test_ap_creation_does_not_mutate_plant_policy(self):
        # Full ships no plant policy file; the invariant that survives is
        # "AP creation leaves the shipped firewall untouched".
        firewall = ROOT / "overlays/devices/tr3000-full/files/etc/config/firewall"
        (self.root / "etc/config" / firewall.name).write_bytes(firewall.read_bytes())
        self.run_ap()
        self.assertEqual(firewall.read_bytes(),
                         (self.root / "etc/config" / firewall.name).read_bytes())


class FullTransformSentinel(unittest.TestCase):
    def test_transformed_module_targets_the_full_script(self):
        self.assertIn("tr3000-full", str(module_globals["SCRIPT"]))
        self.assertNotIn("tr3000-lite", str(module_globals["SCRIPT"]))
