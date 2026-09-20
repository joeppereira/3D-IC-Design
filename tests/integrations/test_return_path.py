"""EDA -> physics-AI: readers, correlation math, and the calibration feedback.

Fixtures under fixtures/ emulate the FORMAT of vendor exports.  They are not
vendor data, and every one of them carries the fixture marker so the tier guard
reports T0 -- correlating against our own output and calling it T2 would be
self-validation.
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from integrations import correlate as corr
from integrations.base import provenance, TIER_EMITTED, TIER_CORRELATED
from integrations.canonical import load_design
from integrations.importers import vendor_results as vr
from integrations.interchange import touchstone_io as ts, spef_io

FIX = Path(__file__).parent / "fixtures"


class TestReaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()

    def test_thermal_field(self):
        res = vr.read_thermal_field(FIX / "celsius_temperature.csv")
        self.assertEqual(res["kind"], "thermal_field")
        self.assertEqual(res["n_points"], 256)
        self.assertGreater(res["tj_peak_c"], res["tj_mean_c"])
        self.assertEqual(len(res["hotspot_um"]), 3)
        self.assertEqual(res["coords_um"].shape, (256, 3))

    def test_ir_drop_with_explicit_column(self):
        res = vr.read_ir_drop(FIX / "voltus_ir_drop.csv")
        self.assertAlmostEqual(res["worst_droop_mv"], 5.1, places=3)
        self.assertEqual(res["worst_net"], "VDD_CORE")
        self.assertAlmostEqual(res["nominal_v"], self.design.vddq_v, places=6)

    def test_ir_drop_from_voltage_only(self):
        """A voltage-only report still works, but only with a declared nominal."""
        res = vr.read_ir_drop(FIX / "ir_voltage_only.csv")
        self.assertAlmostEqual(res["worst_droop_mv"], 5.1, places=3)

    def test_voltage_only_without_nominal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.csv"
            p.write_text("net,voltage\nVDD_CORE,0.8449\n")
            with self.assertRaises(ValueError):
                vr.read_ir_drop(p)

    def test_headerless_table_is_rejected(self):
        """Never guess column meaning -- that is how units get silently wrong."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "raw.csv"
            p.write_text("0,0,50,98.5\n1,1,50,99.1\n")
            with self.assertRaises(ValueError):
                vr.read_thermal_field(p)

    def test_missing_temperature_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nt.csv"
            p.write_text("x_um,y_um,pressure\n0,0,1.0\n")
            with self.assertRaises(ValueError):
                vr.read_thermal_field(p)

    def test_golden_spef(self):
        res = vr.read_starrc_spef(FIX / "starrc_golden.spef")
        self.assertEqual(res["kind"], "parasitics")
        self.assertIn("GOLDEN", res["flow"])
        self.assertEqual(len(res["nets"]), len(self.design.nets))

    def test_sparameters(self):
        res = vr.read_sparameters(FIX / "hyperlynx_field_solved.s4p")
        self.assertEqual(res["meta"]["n_ports"], 4)
        self.assertGreater(res["il_db"][-1], res["il_db"][1])

    def test_read_any_dispatch(self):
        for name, kind in (("celsius_temperature.csv", "thermal_field"),
                           ("voltus_ir_drop.csv", "ir_drop"),
                           ("starrc_golden.spef", "parasitics"),
                           ("hyperlynx_field_solved.s4p", "sparameters")):
            with self.subTest(name=name):
                self.assertEqual(vr.read_any(FIX / name)["kind"], kind)

    def test_def_readback_reenters_the_loop(self):
        """A DEF written back by P&R must reload as placements."""
        from integrations.interchange import def_io
        with tempfile.TemporaryDirectory() as tmp:
            die = self.design.dies[0]
            prov = provenance("t", "SURROGATE", self.design.sha256(), "rid")
            p = def_io.write(self.design, die, Path(tmp) / "x.def", prov)
            res = vr.read_def_placement(p)
            self.assertEqual(res["design"], die.name)
            self.assertEqual(len(res["components"]),
                             len(self.design.macros_on(die.name)))


class TestCorrelation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()

    def test_thermal_delta(self):
        c = corr.thermal(self.design, vr.read_thermal_field(FIX / "celsius_temperature.csv"))
        self.assertEqual(c.quantity, "tj_peak")
        self.assertAlmostEqual(c.delta, c.surrogate - c.vendor, places=9)
        self.assertEqual(c.verdict, "PASS")
        self.assertEqual(c.band, corr.BAND_TJ_C)
        self.assertIn("thermal_bias_c", c.calibration)

    def test_thermal_out_of_band_is_flagged(self):
        vendor = vr.read_thermal_field(FIX / "celsius_temperature.csv")
        vendor["tj_peak_c"] += 30.0
        c = corr.thermal(self.design, vendor)
        self.assertEqual(c.verdict, "REVIEW")
        self.assertEqual(c.finding().severity, "warning")

    def test_thermal_field_rms_when_shapes_match(self):
        vendor = vr.read_thermal_field(FIX / "celsius_temperature.csv")
        surrogate = vendor["field"] - 1.5
        c = corr.thermal(self.design, vendor, surrogate_field=surrogate)
        self.assertAlmostEqual(c.detail["field_rms_c"], 1.5, places=6)
        self.assertAlmostEqual(c.detail["field_max_abs_c"], 1.5, places=6)

    def test_ir_delta_and_calibration(self):
        c = corr.ir_drop(self.design, vr.read_ir_drop(FIX / "voltus_ir_drop.csv"))
        self.assertEqual(c.verdict, "PASS")
        self.assertAlmostEqual(c.vendor, 5.1, places=3)
        self.assertAlmostEqual(c.calibration["droop_scale"], 5.1 / c.surrogate, places=5)
        self.assertTrue(c.detail["vendor_within_target"])

    def test_parasitic_error_distribution(self):
        """Fixture R/C are 1.15x ours, so our error is -13.04% everywhere."""
        c = corr.parasitics(self.design, vr.read_starrc_spef(FIX / "starrc_golden.spef"))
        self.assertEqual(c.detail["matched_entries"], 2 * len(self.design.nets))
        self.assertAlmostEqual(c.detail["mean_err_pct"], -13.0434782, places=5)
        self.assertAlmostEqual(c.detail["max_abs_err_pct"], 13.0434782, places=5)
        self.assertEqual(c.verdict, "PASS")
        for scale in c.calibration["rc_scale_by_class"].values():
            self.assertAlmostEqual(scale, 1.15, places=6)

    def test_parasitic_large_error_is_flagged(self):
        vendor = vr.read_starrc_spef(FIX / "starrc_golden.spef")
        for net in vendor["nets"].values():
            net["r_ohm"] *= 4.0
        c = corr.parasitics(self.design, vendor)
        self.assertEqual(c.verdict, "REVIEW")
        self.assertGreater(abs(c.detail["max_abs_err_pct"]), corr.BAND_RC_PCT)

    def test_channel_delta_matches_injected_offset(self):
        """The fixture adds 1.4 dB at Nyquist; correlation must recover exactly that."""
        link = self.design.links[0]
        c = corr.channel(self.design, link,
                         vr.read_sparameters(FIX / "hyperlynx_field_solved.s4p"))
        self.assertAlmostEqual(c.delta, -1.4, places=3)
        self.assertEqual(c.verdict, "PASS")
        self.assertGreater(c.detail["rms_in_band_db"], 0.0)
        self.assertAlmostEqual(c.detail["nyquist_ghz"], link.nyquist_ghz, places=6)

    def test_no_prediction_is_reported_not_faked(self):
        design = load_design()
        design.predictions.tj_peak_c = None
        c = corr.thermal(design, vr.read_thermal_field(FIX / "celsius_temperature.csv"))
        self.assertEqual(c.verdict, "NO_PREDICTION")
        self.assertEqual(c.calibration, {})
        self.assertEqual(c.finding().severity, "warning")


class TestTierGuard(unittest.TestCase):
    """The self-validation guard: our own output can never earn T2."""

    @classmethod
    def setUpClass(cls):
        cls.design = load_design()

    def test_fixtures_are_marked_untrusted(self):
        for name in ("celsius_temperature.csv", "voltus_ir_drop.csv",
                     "starrc_golden.spef", "hyperlynx_field_solved.s4p"):
            with self.subTest(name=name):
                self.assertTrue(corr.is_self_generated(FIX / name))

    def test_our_own_emitted_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = provenance("t", "SURROGATE", self.design.sha256(), "rid")
            p = spef_io.write(self.design, Path(tmp) / "own.spef", prov)
            self.assertTrue(corr.is_self_generated(p))
            c = corr.parasitics(self.design, vr.read_starrc_spef(p))
            self.assertEqual(c.tier, TIER_EMITTED)

    def test_gds_sidecar_also_counts_as_self_generated(self):
        from integrations.interchange import gds_io
        with tempfile.TemporaryDirectory() as tmp:
            prov = provenance("t", "SURROGATE", self.design.sha256(), "rid")
            p = gds_io.write(self.design, self.design.dies[0], Path(tmp) / "x.gds", prov)
            self.assertTrue(corr.is_self_generated(p))

    def test_unmarked_third_party_file_earns_t2(self):
        """A genuine vendor file (no marker) is the only path to T2."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "vendor.csv"
            p.write_text("# Celsius 2026.1 export, nominal 0.85 V\n"
                         "x_um,y_um,temperature_c\n0,0,101.0\n100,100,99.0\n")
            self.assertFalse(corr.is_self_generated(p))
            c = corr.thermal(self.design, vr.read_thermal_field(p))
            self.assertEqual(c.tier, TIER_CORRELATED)


class TestFeedback(unittest.TestCase):
    """Calibration must flow back into the physics-AI env -- but only if earned."""

    @classmethod
    def setUpClass(cls):
        cls.design = load_design()

    def _fixture_correlations(self):
        return [
            corr.thermal(self.design, vr.read_thermal_field(FIX / "celsius_temperature.csv")),
            corr.ir_drop(self.design, vr.read_ir_drop(FIX / "voltus_ir_drop.csv")),
            corr.parasitics(self.design, vr.read_starrc_spef(FIX / "starrc_golden.spef")),
            corr.channel(self.design, self.design.links[0],
                         vr.read_sparameters(FIX / "hyperlynx_field_solved.s4p")),
        ]

    def test_report_records_the_t0_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = corr.write_report(self._fixture_correlations(), Path(tmp))
            doc = json.loads(p.read_text())
            self.assertEqual(doc["claim_tier"], TIER_EMITTED)
            self.assertEqual(len(doc["correlations"]), 4)
            self.assertEqual(doc["bands"]["tj_c"], corr.BAND_TJ_C)
            self.assertIn("plumbing", doc["note"])

    def test_untrusted_calibration_is_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = corr.write_calibration(self._fixture_correlations(), Path(tmp) / "cal.json")
            doc = json.loads(p.read_text())
            self.assertFalse(doc["trustworthy"])
            self.assertEqual(corr.load_calibration(p), {},
                             "untrusted calibration must not reach the surrogate")
            applied = corr.apply_calibration(self.design, corr.load_calibration(p))
            self.assertEqual(applied["tj_peak_c"], self.design.predictions.tj_peak_c)
            self.assertEqual(applied["applied"], [])

    def test_trusted_calibration_shifts_the_prediction(self):
        """With real vendor data the loop closes: predictions move."""
        with tempfile.TemporaryDirectory() as tmp:
            vend = Path(tmp) / "vendor_temp.csv"
            vend.write_text("# Celsius 2026.1 steady-state export\n"
                            "x_um,y_um,temperature_c\n0,0,104.0\n100,100,88.0\n")
            c = corr.thermal(self.design, vr.read_thermal_field(vend))
            self.assertEqual(c.tier, TIER_CORRELATED)
            p = corr.write_calibration([c], Path(tmp) / "cal.json")
            self.assertTrue(json.loads(p.read_text())["trustworthy"])
            cal = corr.load_calibration(p)
            self.assertIn("thermal_bias_c", cal)
            applied = corr.apply_calibration(self.design, cal)
            self.assertAlmostEqual(applied["tj_peak_c"], 104.0, places=4)
            self.assertIn("thermal_bias_c", applied["applied"])

    def test_calibration_records_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = corr.write_calibration(self._fixture_correlations(), Path(tmp) / "c.json")
            doc = json.loads(p.read_text())
            self.assertIn("git_sha", doc)
            self.assertIn("run_id", doc)
            self.assertEqual(len(doc["derived_from"]), 4)
            for entry in doc["derived_from"]:
                self.assertIn(entry["tier"], (TIER_EMITTED, TIER_CORRELATED))


class TestFullLoop(unittest.TestCase):
    def test_emit_then_read_back_every_format(self):
        """One pass of the whole loop: emit -> read -> correlate, no licenses."""
        from integrations.base import HOOK_REGISTRY
        from integrations import vendors  # noqa: F401
        design = load_design()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hook = HOOK_REGISTRY["neutral:touchstone"]()
            result = hook.run(design, root / "ts", rid="loop")
            self.assertTrue(result.ok)
            emitted = root / "ts" / f"{design.links[0].name}.s4p"
            back = vr.read_sparameters(emitted)
            c = corr.channel(design, design.links[0], back)
            self.assertAlmostEqual(c.delta, 0.0, places=6,
                                   msg="reading back our own channel must show zero delta")
            self.assertEqual(c.tier, TIER_EMITTED)

            spef_hook = HOOK_REGISTRY["neutral:spef"]()
            spef_hook.run(design, root / "spef", rid="loop")
            back_spef = vr.read_starrc_spef(root / "spef" / "3dic_x.spef")
            cp = corr.parasitics(design, back_spef)
            self.assertAlmostEqual(cp.detail["max_abs_err_pct"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
