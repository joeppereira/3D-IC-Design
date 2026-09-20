"""Tests for the cross-consistency gate.

Each check is exercised both ways: it must fire on a crafted defect and stay
quiet on a consistent record.  The gate is only useful if it does both.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from integrations import verify as V
from integrations.base import SEV_ERROR, SEV_WARN
from integrations.canonical import (DesignRecord, Die, Interface, Link, Net,
                                    Predictions, load_design)
from integrations.interchange import touchstone_io as ts


def clean_record(tmp: Path) -> DesignRecord:
    """A record whose numbers agree with each other."""
    link = Link("LINK_0", 224.0, "PAM4", "Twinax", 300.0)
    freqs, s, _ = ts.synth_channel(link)
    il = ts.il_at(freqs, s, link.nyquist_ghz)
    golden = tmp / "golden_config.json"
    golden.write_text(json.dumps({"project_name": "3DIC_X_Module",
                                  "max_power_budget_w": 60.0}))
    deck = tmp / "deck.json"
    deck.write_text(json.dumps({"design_id": "3DIC_X_v1"}))
    return DesignRecord(
        project="3DIC_X_Module",
        dies=[Die("DRAM_Stack", "dram", 15000.0, 15000.0, 30.0, power_w=15.0),
              Die("SRAM_Search_Die", "sram", 15000.0, 15000.0, 50.0, power_w=15.0),
              Die("CXL_Switch_Logic", "logic", 18000.0, 18000.0, 50.0, power_w=25.0),
              Die("Power_Delivery_Die", "vrm", 18000.0, 18000.0, 775.0, power_w=5.0)],
        interfaces=[Interface(("CXL_Switch_Logic", "SRAM_Search_Die"), "hybrid_bond", 5.0)],
        links=[link],
        nets=[Net("LINK_0_TX_P", "serdes_diff", r_ohm=150.0, c_pf=12.0,
                  length_um=300000.0)],
        predictions=Predictions(tj_peak_c=98.5, droop_mv=4.0, eye_margin_ui=0.62,
                                insertion_loss_db=il),
        sources={"golden_config": str(golden), "vector_deck": str(deck)},
    )


class TestChecks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.design = clean_record(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def errors(self, findings):
        return [f for f in findings if f.severity == SEV_ERROR]

    def warns(self, findings):
        return [f for f in findings if f.severity == SEV_WARN]

    # --- freshness ----------------------------------------------------------
    def test_fresh_golden_passes(self):
        self.assertEqual([], self.errors(V.check_input_freshness(self.design)))

    def test_stale_golden_fires(self):
        golden = Path(self.design.sources["golden_config"])
        old = time.time() - 200 * V.DAY
        os.utime(golden, (old, old))
        errs = self.errors(V.check_input_freshness(self.design))
        self.assertTrue(any(e.check == "stale_golden_config" for e in errs), errs)

    def test_missing_golden_fires(self):
        Path(self.design.sources["golden_config"]).unlink()
        errs = self.errors(V.check_input_freshness(self.design))
        self.assertTrue(any(e.check == "golden_missing" for e in errs), errs)

    # --- identity -----------------------------------------------------------
    def test_matching_identity_passes(self):
        self.assertEqual([], self.errors(V.check_project_identity(self.design)))

    def test_identity_mismatch_fires(self):
        Path(self.design.sources["vector_deck"]).write_text(
            json.dumps({"design_id": "SomethingElse_v9"}))
        errs = self.errors(V.check_project_identity(self.design))
        self.assertTrue(any(e.check == "project_identity" for e in errs), errs)

    # --- the flow's own verdict --------------------------------------------
    def test_open_eye_passes(self):
        self.assertEqual([], self.errors(V.check_surrogate_verdict(self.design)))

    def test_closed_eye_fires(self):
        self.design.predictions.eye_margin_ui = 0.0
        errs = self.errors(V.check_surrogate_verdict(self.design))
        self.assertTrue(any(e.check == "surrogate_verdict" for e in errs), errs)

    def test_overtemperature_fires(self):
        self.design.predictions.tj_peak_c = 140.0
        errs = self.errors(V.check_surrogate_verdict(self.design))
        self.assertTrue(any(e.check == "thermal_verdict" for e in errs), errs)

    # --- channel agreement: the 62 dB class of bug -------------------------
    def test_agreeing_channel_passes(self):
        self.assertEqual([], self.errors(V.check_channel_agreement(self.design)))

    def test_disagreeing_channel_fires(self):
        self.design.predictions.insertion_loss_db = 67.03
        errs = self.errors(V.check_channel_agreement(self.design))
        self.assertTrue(any(e.check == "il_model_disagreement" for e in errs), errs)
        self.assertIn("dB", errs[0].message)

    def test_small_disagreement_tolerated(self):
        self.design.predictions.insertion_loss_db += V.IL_DISAGREEMENT_DB * 0.5
        self.assertEqual([], self.errors(V.check_channel_agreement(self.design)))

    def test_no_prediction_is_not_an_error(self):
        self.design.predictions.insertion_loss_db = None
        self.assertEqual([], V.check_channel_agreement(self.design))

    # --- parasitic plausibility --------------------------------------------
    def test_plausible_rc_passes(self):
        self.assertEqual([], self.errors(V.check_rc_plausibility(self.design)))

    def test_ondie_resistance_on_a_channel_fires(self):
        self.design.nets[0].r_ohm = 14062.5
        errs = self.errors(V.check_rc_plausibility(self.design))
        self.assertTrue(any(e.check == "rc_implausible" for e in errs), errs)
        self.assertIn("ohm/mm", errs[0].message)

    # --- material keys ------------------------------------------------------
    def test_material_drift_is_reported(self):
        self.design.links[0].material = "Flyover"
        warns = self.warns(V.check_material_keys(self.design))
        self.assertTrue(any(w.check == "material_key_drift" for w in warns), warns)

    def test_shared_material_is_quiet(self):
        self.design.links[0].material = "FR4"
        drift = [w for w in self.warns(V.check_material_keys(self.design))
                 if w.check == "material_key_drift"]
        self.assertEqual([], drift)

    # --- stack coverage -----------------------------------------------------
    def test_full_stack_passes(self):
        self.assertEqual([], self.errors(V.check_stack_coverage(self.design)))

    def test_missing_layer_fires(self):
        self.design.dies = [d for d in self.design.dies if d.name != "DRAM_Stack"]
        errs = self.errors(V.check_stack_coverage(self.design))
        self.assertTrue(any(e.check == "stack_coverage" for e in errs), errs)
        self.assertIn("dram_stack", errs[0].message)

    def test_thickness_mismatch_fires(self):
        self.design.die("DRAM_Stack").thickness_um = 55.0
        errs = self.errors(V.check_stack_coverage(self.design))
        self.assertTrue(any(e.check == "stack_thickness" for e in errs), errs)

    def test_naming_drift_is_a_warning_not_an_error(self):
        findings = V.check_stack_coverage(self.design)
        self.assertEqual([], self.errors(findings))
        self.assertTrue(any(f.check == "stack_naming" for f in findings))

    # --- power budget -------------------------------------------------------
    def test_power_budget_matches(self):
        self.assertEqual([], self.errors(V.check_power_budget(self.design)))

    def test_power_budget_overrun_fires(self):
        self.design.dies[0].power_w += 5.0
        errs = self.errors(V.check_power_budget(self.design))
        self.assertTrue(any(e.check == "power_budget" for e in errs), errs)


class TestDeckChecks(unittest.TestCase):
    """Checks that read the emitted handoff tree."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.design = clean_record(self.tmp)
        self.handoff = self.tmp / "handoff"
        self.handoff.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_temperature_consistency(self):
        (self.handoff / "a.sp").write_text(f".options temp={self.design.op_temp_c}\n")
        findings = V.check_temperature_consistency(self.design, self.handoff)
        self.assertEqual([], [f for f in findings if f.severity == SEV_ERROR])

    def test_temperature_drift_fires(self):
        (self.handoff / "a.sp").write_text(".options temp=25.0\n")
        errs = [f for f in V.check_temperature_consistency(self.design, self.handoff)
                if f.severity == SEV_ERROR]
        self.assertTrue(any(e.check == "temperature_drift" for e in errs), errs)

    def test_def_area_mismatch_fires(self):
        from integrations.base import provenance
        from integrations.interchange import def_io
        die = self.design.die("CXL_Switch_Logic")
        prov = provenance("t", "SURROGATE", self.design.sha256(), "rid")
        def_io.write(self.design, die, self.handoff / "x.def", prov)
        die.width_um = 20000.0          # golden changed after the DEF was written
        errs = [f for f in V.check_def_area(self.design, self.handoff)
                if f.severity == SEV_ERROR]
        self.assertTrue(any(e.check == "def_area_mismatch" for e in errs), errs)

    def test_unknown_die_in_def_fires(self):
        from integrations.base import provenance
        from integrations.interchange import def_io
        die = self.design.die("CXL_Switch_Logic")
        prov = provenance("t", "SURROGATE", self.design.sha256(), "rid")
        def_io.write(self.design, die, self.handoff / "y.def", prov)
        self.design.dies = [d for d in self.design.dies if d.name != "CXL_Switch_Logic"]
        errs = [f for f in V.check_def_area(self.design, self.handoff)
                if f.severity == SEV_ERROR]
        self.assertTrue(any(e.check == "def_unknown_die" for e in errs), errs)


class TestGate(unittest.TestCase):
    def test_summary_and_gate_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = clean_record(Path(tmp))
            findings = V.verify(design, None)
            s = V.summary(findings)
            self.assertEqual(s["ok"], s["errors"] == 0)

    def test_gate_runs_against_the_real_repo(self):
        """Must produce a verdict on the live design record without crashing."""
        findings = V.verify(load_design(), None)
        self.assertTrue(findings)
        self.assertIn("ok", V.summary(findings))


if __name__ == "__main__":
    unittest.main()
