"""T0 tests: every format round-trips, and each validator actually catches damage.

No vendor licenses and no vendor binaries required -- that is the point of the
vendor-neutral layer.  ngspice is used when present as the one external checker
available on this machine.
"""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from integrations.base import provenance, FIDELITY_SURROGATE
from integrations.canonical import load_design, Link, MATERIAL_LOSS_DB_PER_INCH
from integrations.interchange import (stackup, def_io, lef_io, gds_io, spef_io,
                                      liberty_io, ibis_io, spice_io)
from integrations.interchange import touchstone_io as ts


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()
        cls.prov = provenance("tests", FIDELITY_SURROGATE, cls.design.sha256(), "test-run")
        cls._tmp = tempfile.TemporaryDirectory(prefix="3dicx-test-")
        cls.out = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def errors(self, findings):
        return [f for f in findings if f.severity == "error"]


class TestStackup(Base):
    def test_roundtrip_and_units(self):
        p = stackup.write(self.design, self.out / "s.json", self.prov)
        doc = stackup.read(p)
        self.assertEqual(doc["units"], dict(stackup.REQUIRED_UNITS))
        self.assertEqual(len(doc["dies"]), len(self.design.dies))
        self.assertEqual([], self.errors(stackup.validate(doc)))

    def test_detects_mm_um_confusion(self):
        """The spec calls a silent mm/um slip the most expensive bug class here."""
        doc = stackup.read(stackup.write(self.design, self.out / "s2.json", self.prov))
        doc["dies"][0]["thickness_um"] = 0.05        # 50 um written as mm
        errs = self.errors(stackup.validate(doc))
        self.assertTrue(any(e.check == "unit_sanity" for e in errs), errs)

    def test_requires_declared_units(self):
        doc = stackup.read(stackup.write(self.design, self.out / "s3.json", self.prov))
        doc["units"]["length"] = "mm"
        self.assertTrue(any(e.check == "units" for e in self.errors(stackup.validate(doc))))


class TestDef(Base):
    def setUp(self):
        self.die = self.design.dies[0]
        self.macros = self.design.macros_on(self.die.name)
        self.path = def_io.write(self.design, self.die, self.out / "d.def", self.prov)

    def test_placements_roundtrip_exactly(self):
        doc = def_io.read(self.path)
        self.assertEqual(doc["diearea_um"], (self.die.width_um, self.die.height_um))
        self.assertEqual(len(doc["components"]), len(self.macros))
        self.assertEqual([], self.errors(def_io.validate(doc, self.die, self.macros)))
        by_name = {c["name"]: c for c in doc["components"]}
        for m in self.macros:
            self.assertEqual(by_name[m.name]["origin_um"], tuple(m.origin_um))
            self.assertEqual(by_name[m.name]["orient"], m.orient)

    def test_matches_gen_def_geometry(self):
        """DEF must carry the same numbers gen_def.py writes into OpenROAD Tcl."""
        doc = def_io.read(self.path)
        first = {c["name"]: c for c in doc["components"]}["SERDES_N_0"]
        self.assertEqual(first["origin_um"], (1000.0, self.die.height_um - 1500.0))
        self.assertTrue(all(o % 10 == 0 for c in doc["components"]
                            for o in c["origin_um"]), "10um snap grid violated")

    def test_detects_moved_macro(self):
        text = self.path.read_text().replace("( 1000000 16500000 )", "( 1000000 16400000 )")
        p2 = self.out / "d_moved.def"
        p2.write_text(text)
        errs = self.errors(def_io.validate(def_io.read(p2), self.die, self.macros))
        self.assertTrue(any(e.check == "def_placement" for e in errs), errs)

    def test_detects_dbu_change(self):
        text = self.path.read_text().replace("UNITS DISTANCE MICRONS 1000",
                                             "UNITS DISTANCE MICRONS 2000")
        p2 = self.out / "d_dbu.def"
        p2.write_text(text)
        errs = self.errors(def_io.validate(def_io.read(p2), self.die, self.macros))
        self.assertTrue(any(e.check == "def_units" for e in errs), errs)

    def test_one_def_per_die(self):
        """A 3D stack is N DEFs plus a stack description, never a flat view."""
        written = {d.name for d in self.design.dies if self.design.macros_on(d.name)}
        for name in written:
            die = self.design.die(name)
            p = def_io.write(self.design, die, self.out / f"{name}.def", self.prov)
            self.assertEqual(def_io.read(p)["design"], name)


class TestLef(Base):
    def test_covers_every_placed_cell(self):
        doc = lef_io.read(lef_io.write(self.design, self.out / "l.lef", self.prov))
        self.assertEqual([], self.errors(lef_io.validate(doc, self.design)))
        for cell in {m.cell for m in self.design.macros}:
            self.assertIn(cell, doc["macros"])

    def test_includes_3d_interface_cells(self):
        """Without TSV/bond abstracts the 3D interface is invisible downstream."""
        doc = lef_io.read(lef_io.write(self.design, self.out / "l2.lef", self.prov))
        self.assertIn("TSV_CU_2UM", doc["macros"])
        self.assertIn("HYBRID_BOND_PAD", doc["macros"])
        self.assertEqual(doc["macros"]["TSV_CU_2UM"]["size_um"], (2.0, 2.0))

    def test_site_matches_floorplan_call(self):
        doc = lef_io.read(lef_io.write(self.design, self.out / "l3.lef", self.prov))
        self.assertIn(lef_io.SITE, doc["sites"])

    def test_detects_missing_macro(self):
        p = lef_io.write(self.design, self.out / "l4.lef", self.prov)
        text = p.read_text()
        start = text.index("MACRO SERDES_224G_PHY")
        end = text.index("END SERDES_224G_PHY") + len("END SERDES_224G_PHY")
        p2 = self.out / "l5.lef"
        p2.write_text(text[:start] + text[end:])
        errs = self.errors(lef_io.validate(lef_io.read(p2), self.design))
        self.assertTrue(any(e.check in ("lef_macro", "lef_coverage") for e in errs), errs)


class TestGds(Base):
    def test_real8_codec(self):
        for v in (1e-3, 1e-9, 1.0, 0.5, 1234.5678, -42.0, 0.0):
            self.assertAlmostEqual(gds_io._parse_real8(gds_io._real8(v)), v,
                                   delta=abs(v) * 1e-12 + 1e-18)

    def test_stream_roundtrip(self):
        die = self.design.dies[0]
        p = gds_io.write(self.design, die, self.out / "g.gds", self.prov)
        doc = gds_io.read(p)
        self.assertAlmostEqual(doc["units"][1], 1e-9, delta=1e-18)
        top = doc["structures"][die.name.upper()[:31]]
        self.assertEqual(len(top["srefs"]), len(self.design.macros_on(die.name)))
        bb = top["bbox"]
        self.assertAlmostEqual(bb[2], die.width_um, places=3)
        self.assertAlmostEqual(bb[3], die.height_um, places=3)
        self.assertEqual([], self.errors(gds_io.validate(doc, self.design, die)))

    def test_sidecar_provenance_written(self):
        die = self.design.dies[0]
        p = gds_io.write(self.design, die, self.out / "g2.gds", self.prov)
        self.assertTrue(Path(str(p) + ".provenance.json").exists(),
                        "binary formats need a provenance sidecar")

    def test_record_structure_is_wellformed(self):
        """Every record must declare a length that walks cleanly to ENDLIB."""
        die = self.design.dies[0]
        raw = gds_io.write(self.design, die, self.out / "g3.gds", self.prov).read_bytes()
        pos, saw_endlib = 0, False
        while pos < len(raw):
            length, rtype = struct.unpack(">HH", raw[pos:pos + 4])
            self.assertGreaterEqual(length, 4)
            self.assertEqual(length % 2, 0, "GDSII records must be even-length")
            if rtype == gds_io.ENDLIB:
                saw_endlib = True
            pos += length
        self.assertEqual(pos, len(raw), "record walk overran the file")
        self.assertTrue(saw_endlib)


class TestSpef(Base):
    def test_conservation_and_roundtrip(self):
        p = spef_io.write(self.design, self.out / "p.spef", self.prov)
        doc = spef_io.read(p)
        self.assertEqual([], self.errors(spef_io.validate(doc, self.design)))
        for net in self.design.nets:
            got = doc["nets"][net.name]
            self.assertAlmostEqual(got["sum_r_ohm"], net.r_ohm, places=6)
            self.assertAlmostEqual(got["sum_c_ff"], net.c_pf * 1000.0, places=3)

    def test_declares_analytic_flow(self):
        """Nothing downstream may mistake these for a real extraction."""
        doc = spef_io.read(spef_io.write(self.design, self.out / "p2.spef", self.prov))
        self.assertIn("ANALYTIC_SURROGATE", doc["header"]["DESIGN_FLOW"])

    def test_detects_broken_conservation(self):
        p = spef_io.write(self.design, self.out / "p3.spef", self.prov)
        lines = p.read_text().splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("1 LINK_0_TX_P:1 LINK_0_TX_P:2"):
                lines[i] = "1 LINK_0_TX_P:1 LINK_0_TX_P:2 999.000000"
                break
        p2 = self.out / "p4.spef"
        p2.write_text("\n".join(lines) + "\n")
        errs = self.errors(spef_io.validate(spef_io.read(p2), self.design))
        self.assertTrue(any(e.check == "spef_res" for e in errs), errs)

    def test_is_scoped_to_modeled_nets(self):
        doc = spef_io.read(spef_io.write(self.design, self.out / "p5.spef", self.prov))
        self.assertEqual(set(doc["nets"]), {n.name for n in self.design.nets})
        self.assertLess(len(doc["nets"]), 1000, "SPEF must stay scoped, not full-chip")


class TestLiberty(Base):
    def test_roundtrip(self):
        doc = liberty_io.read(liberty_io.write(self.design, self.out / "m.lib", self.prov))
        self.assertEqual([], self.errors(liberty_io.validate(doc, self.design)))
        self.assertEqual(doc["nom_temperature"], self.design.op_temp_c)

    def test_no_timing_arcs_emitted(self):
        """Uncharacterized cell_rise tables would be fabricated data."""
        doc = liberty_io.read(liberty_io.write(self.design, self.out / "m2.lib", self.prov))
        self.assertEqual(doc["total_timing_groups"], 0)

    def test_rejects_injected_timing(self):
        p = liberty_io.write(self.design, self.out / "m3.lib", self.prov)
        text = p.read_text().replace(
            "    is_macro_cell : true;",
            "    is_macro_cell : true;\n    timing () { cell_rise (t) { values(\"1.0\"); } }", 1)
        p2 = self.out / "m4.lib"
        p2.write_text(text)
        errs = self.errors(liberty_io.validate(liberty_io.read(p2), self.design))
        self.assertTrue(any(e.check == "lib_no_fabricated_timing" for e in errs), errs)

    def test_power_pins_are_pg_pins(self):
        doc = liberty_io.read(liberty_io.write(self.design, self.out / "m5.lib", self.prov))
        phy = doc["cells"]["SERDES_224G_PHY"]
        self.assertIn("VDDQ_SERDES", phy["pg_pins"])
        self.assertNotIn("VDDQ_SERDES", phy["pins"])


class TestTouchstone(Base):
    LINKS = [Link("TW_300", 224.0, "PAM4", "Twinax", 300.0),
             Link("MEG7_300", 224.0, "PAM4", "Megtron_7", 300.0),
             Link("FR4_50", 112.0, "PAM4", "FR4", 50.0),
             Link("HB_15UM", 224.0, "PAM4", "Twinax", 0.015),
             Link("NRZ_32", 32.0, "NRZ", "Megtron_7", 100.0)]

    def test_electrical_properties(self):
        for link in self.LINKS:
            with self.subTest(link=link.name):
                freqs, s, info = ts.synth_channel(link)
                passive, worst = ts.check_passivity(s)
                self.assertTrue(passive, f"max singular value {worst}")
                recip, err = ts.check_reciprocity(s)
                self.assertTrue(recip, f"|S-S^T| = {err}")
                ok_dc, dc = ts.check_dc(s)
                self.assertTrue(ok_dc, f"DC point {dc}")
                frac, _ = ts.check_causality(freqs, s, ts._group_delay_s(link, link.dk_df[0]))
                self.assertLess(frac, 0.01, f"pre-cursor energy {frac:.4%}")

    def test_il_matches_si_analyzer_budget(self):
        """The artifact must agree with the number the surrogate reports."""
        for link in self.LINKS:
            with self.subTest(link=link.name):
                freqs, s, _ = ts.synth_channel(link)
                target = MATERIAL_LOSS_DB_PER_INCH[link.material] * link.reach_mm / 25.4
                self.assertAlmostEqual(ts.il_at(freqs, s, link.nyquist_ghz), target,
                                       delta=max(0.5, 0.05 * target))

    def test_bandwidth_covers_twice_nyquist(self):
        for link in self.LINKS:
            freqs, _, _ = ts.synth_channel(link)
            self.assertGreaterEqual(freqs[-1] / 1e9, 2 * link.nyquist_ghz - 1e-6)

    def test_file_roundtrip(self):
        link = self.LINKS[0]
        freqs, s, info = ts.synth_channel(link)
        p = ts.write(link, self.out / f"{link.name}.s4p", self.prov, freqs, s, info)
        f2, s2, meta = ts.read(p)
        self.assertEqual(meta["n_ports"], 4)
        self.assertEqual(meta["z0"], link.z0_ohm)
        np.testing.assert_allclose(freqs, f2, rtol=0, atol=1e-6)
        self.assertLess(float(np.max(np.abs(s - s2))), 1e-9)
        self.assertEqual([], self.errors(ts.validate(f2, s2, link)))

    def test_port_order_is_documented(self):
        link = self.LINKS[0]
        p = ts.write(link, self.out / "ports.s4p", self.prov)
        self.assertIn("1,2 = TX P/N", p.read_text())

    def test_declares_synthetic_provenance(self):
        link = self.LINKS[0]
        text = ts.write(link, self.out / "syn.s4p", self.prov).read_text()
        self.assertIn("SYNTHETIC", text)
        self.assertIn("Not measured, not field-solved", text)

    def test_catches_nonpassive_file(self):
        link = self.LINKS[0]
        freqs, s, info = ts.synth_channel(link)
        s[10] *= 3.0                       # inject gain
        errs = self.errors(ts.validate(freqs, s, link))
        self.assertTrue(any(e.check == "passivity" for e in errs), errs)

    def test_differential_extraction_is_consistent(self):
        """Sdd21 built from the single-ended matrix must match the model's |t|."""
        link = self.LINKS[1]
        freqs, s, _ = ts.synth_channel(link)
        il = ts.insertion_loss_db(s)
        self.assertTrue(np.all(np.diff(il[1:]) >= -1e-6), "IL must rise with frequency")
        self.assertGreater(il[-1], il[1])


class TestIbis(Base):
    def test_structure(self):
        link = self.design.links[0]
        doc = ibis_io.read_ibs(ibis_io.write_ibs(self.design, link,
                                                self.out / "b.ibs", self.prov))
        self.assertEqual([], self.errors(ibis_io.validate(doc)))
        self.assertEqual(doc["ibis_ver"], "7.0")
        self.assertTrue(doc["ends"])
        self.assertGreaterEqual(len(doc["pulldown"]), 2)

    def test_detects_nonmonotonic_iv(self):
        link = self.design.links[0]
        p = ibis_io.write_ibs(self.design, link, self.out / "b2.ibs", self.prov)
        lines = p.read_text().splitlines()
        idx = lines.index("[Pulldown]") + 3
        lines[idx], lines[idx + 1] = lines[idx + 1], lines[idx]
        p2 = self.out / "b3.ibs"
        p2.write_text("\n".join(lines) + "\n")
        errs = self.errors(ibis_io.validate(ibis_io.read_ibs(p2)))
        self.assertTrue(any("pulldown" in e.check for e in errs), errs)

    def test_ami_declares_no_getwave(self):
        """No DLL ships, so GetWave must be False or simulators will break."""
        link = self.design.links[0]
        text = ibis_io.write_ami(self.design, link, self.out / "b.ami", self.prov).read_text()
        self.assertIn("(GetWave_Exists (Usage Info) (Type Boolean) (Value False))", text)
        self.assertIn("Init_Returns_Impulse", text)


class TestSpice(Base):
    def test_deck_is_built_from_the_design_record(self):
        """P0-C: no hardcoded topology, no nonexistent PDK include."""
        link = self.design.links[0]
        text = spice_io.write_ngspice(self.design, link, self.out / "n.sp",
                                      self.prov).read_text()
        self.assertIn(f"temp={self.design.op_temp_c}", text)
        self.assertNotIn("/pdk/3nm_GAA/models.sp", text)
        self.assertIn(f"chan_{link.name}", text)

    @unittest.skipUnless(spice_io.ngspice_available(), "ngspice not installed")
    def test_deck_actually_simulates(self):
        for link in (self.design.links[0],
                     Link("MEG7_300", 224.0, "PAM4", "Megtron_7", 300.0)):
            with self.subTest(link=link.name):
                p = spice_io.write_ngspice(self.design, link,
                                           self.out / f"{link.name}.sp", self.prov)
                res = spice_io.run_ngspice(p)
                self.assertTrue(res["ok"], f"ngspice failed: {res.get('errors')}")
                self.assertIn("vrx_pp", res["measures"])
                self.assertGreater(res["measures"]["vrx_pp"], 0.0)
                self.assertLessEqual(res["measures"]["vrx_pp"],
                                     res["measures"]["vtx_pp"] * 1.05,
                                     "a passive channel cannot amplify")
                self.assertEqual([], self.errors(
                    spice_io.validate(res, link, self.design)))

    @unittest.skipUnless(spice_io.ngspice_available(), "ngspice not installed")
    def test_lossier_material_loses_more(self):
        """Sanity that the deck carries real physics, not just valid syntax."""
        swings = {}
        for material in ("Twinax", "Megtron_7", "FR4"):
            link = Link(f"X_{material}", 224.0, "PAM4", material, 200.0)
            res = spice_io.run_ngspice(spice_io.write_ngspice(
                self.design, link, self.out / f"x_{material}.sp", self.prov))
            self.assertTrue(res["ok"])
            swings[material] = res["measures"]["vrx_pp"]
        self.assertGreater(swings["Twinax"], swings["Megtron_7"])
        self.assertGreater(swings["Megtron_7"], swings["FR4"])

    def test_primesim_deck_references_touchstone(self):
        link = self.design.links[0]
        text = spice_io.write_primesim(self.design, link, self.out / "ps.sp",
                                       self.prov, f"{link.name}.s4p").read_text()
        self.assertIn(f"tstonefile='{link.name}.s4p'", text)
        self.assertIn(f".temp {self.design.op_temp_c}", text)


if __name__ == "__main__":
    unittest.main()
