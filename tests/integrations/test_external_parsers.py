"""Validation against independently-written parsers.

The round-trip tests in test_interchange.py prove our writer and our reader
agree.  If both share a misreading of the format spec, they agree and are both
wrong.  These tests close that gap by handing the artifacts to implementations
nobody here wrote:

    gdstk      -- GDSII, independent C++ implementation
    scikit-rf  -- Touchstone + RF network theory
    klayout    -- LEF/DEF, the reader used by the open-source physical flows
    liberty-parser -- Liberty, an independent grammar (lark) rather than regexes
    ngspice    -- circuit simulation (see test_interchange.TestSpice)

Each test skips loudly when its tool is absent, so a missing dependency can
never be mistaken for a passing check.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np

from integrations.base import provenance, FIDELITY_SURROGATE
from integrations.canonical import load_design, Link
from integrations.interchange import (def_io, gds_io, lef_io, liberty_io,
                                      touchstone_io as ts)

HAS_GDSTK = importlib.util.find_spec("gdstk") is not None
HAS_SKRF = importlib.util.find_spec("skrf") is not None
HAS_KLAYOUT = importlib.util.find_spec("klayout") is not None
HAS_LIBERTY = importlib.util.find_spec("liberty") is not None


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()
        cls.prov = provenance("tests", FIDELITY_SURROGATE, cls.design.sha256(), "ext")
        cls._tmp = tempfile.TemporaryDirectory(prefix="3dicx-ext-")
        cls.out = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


@unittest.skipUnless(HAS_GDSTK, "gdstk not installed -- GDSII is unvalidated externally")
class TestGdstkReadsOurStream(Base):
    def setUp(self):
        import gdstk
        self.gdstk = gdstk
        self.die = self.design.dies[0]
        self.path = gds_io.write(self.design, self.die, self.out / "ext.gds", self.prov)
        self.lib = gdstk.read_gds(str(self.path))

    def test_units_are_interpreted_as_intended(self):
        self.assertAlmostEqual(self.lib.unit, 1e-6, delta=1e-18)
        self.assertAlmostEqual(self.lib.precision, 1e-9, delta=1e-18)

    def test_cell_hierarchy_matches(self):
        names = {c.name for c in self.lib.cells}
        self.assertIn(self.die.name.upper()[:31], names)
        for cell in {m.cell[:31] for m in self.design.macros_on(self.die.name)}:
            self.assertIn(cell, names)

    def test_geometry_lands_where_we_placed_it(self):
        top = next(c for c in self.lib.cells if c.name == self.die.name.upper()[:31])
        (x0, y0), (x1, y1) = top.bounding_box()
        self.assertAlmostEqual(x0, 0.0, places=3)
        self.assertAlmostEqual(y0, 0.0, places=3)
        self.assertAlmostEqual(x1, self.die.width_um, places=3)
        self.assertAlmostEqual(y1, self.die.height_um, places=3)

    def test_every_macro_is_a_real_reference(self):
        top = next(c for c in self.lib.cells if c.name == self.die.name.upper()[:31])
        self.assertEqual(len(top.references), len(self.design.macros_on(self.die.name)))
        placed = {(round(m.origin_um[0], 3), round(m.origin_um[1], 3))
                  for m in self.design.macros_on(self.die.name)}
        read_back = {(round(r.origin[0], 3), round(r.origin[1], 3)) for r in top.references}
        self.assertEqual(placed, read_back)

    def test_3d_interface_layers_survive(self):
        layers = {pg.layer for c in self.lib.cells for pg in c.polygons}
        self.assertIn(gds_io.LAYER_TSV, layers)
        self.assertIn(gds_io.LAYER_BOND, layers)
        self.assertIn(gds_io.LAYER_KEEPOUT, layers)


@unittest.skipUnless(HAS_SKRF, "scikit-rf not installed -- Touchstone is unvalidated externally")
class TestSkrfReadsOurChannel(Base):
    LINKS = [Link("EXT_TW", 224.0, "PAM4", "Twinax", 300.0),
             Link("EXT_MEG7", 224.0, "PAM4", "Megtron_7", 300.0),
             Link("EXT_FR4", 112.0, "PAM4", "FR4", 50.0),
             Link("EXT_HB", 224.0, "PAM4", "Twinax", 0.015),
             Link("EXT_NRZ", 32.0, "NRZ", "Megtron_7", 100.0)]

    def _net(self, link):
        import skrf
        freqs, s, info = ts.synth_channel(link)
        path = ts.write(link, self.out / f"{link.name}.s4p", self.prov, freqs, s, info)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return skrf.Network(str(path)), freqs, s

    def test_skrf_parses_identically(self):
        for link in self.LINKS:
            with self.subTest(link=link.name):
                net, freqs, s = self._net(link)
                self.assertEqual(net.nports, 4)
                self.assertEqual(len(net.f), len(freqs))
                self.assertAlmostEqual(complex(net.z0[0, 0]).real, link.z0_ohm, places=6)
                np.testing.assert_allclose(net.f, freqs, rtol=0, atol=1e-3)
                self.assertLess(float(np.max(np.abs(net.s - s))), 1e-9)

    def test_skrf_agrees_the_network_is_passive(self):
        """The check that caught a real defect: clamping reflection to exactly
        1-|t| gave a lossless, marginally passive network that skrf rejected."""
        for link in self.LINKS:
            with self.subTest(link=link.name):
                net, _, _ = self._net(link)
                self.assertTrue(net.is_passive(),
                                f"{link.name} is not strictly passive per scikit-rf")

    def test_skrf_agrees_the_network_is_reciprocal(self):
        for link in self.LINKS:
            with self.subTest(link=link.name):
                net, _, _ = self._net(link)
                self.assertTrue(net.is_reciprocal())

    def test_our_passivity_check_is_at_least_as_strict_as_skrf(self):
        """Ours must never accept what skrf rejects.

        The converse does not hold: skrf's is_passive squares the passivity
        matrix element-wise (M = square(S^H.S)) rather than testing the
        eigenvalues of I - S^H.S, so it accepts some marginal networks that our
        min-eigenvalue test rejects. We assert the direction that matters.
        """
        for link in self.LINKS:
            with self.subTest(link=link.name):
                net, _, s = self._net(link)
                ours, min_eig = ts.check_passivity(s)
                if ours:
                    self.assertTrue(net.is_passive(),
                                    f"{link.name}: we accept (min eig {min_eig:.3e}) "
                                    "but scikit-rf rejects")

    def test_marginal_passivity_is_rejected_by_our_checker(self):
        """Regression guard for the defect this suite found.

        Clamping reflection to exactly 1-|t| produced |rho|+|t| == 1: a lossless,
        marginally passive network whose dissipation matrix is singular. The old
        sigma_max <= 1+eps check accepted it. scikit-rf does NOT reliably catch
        this either (its element-wise test is weaker), so our own check has to.
        """
        link = self.LINKS[0]
        freqs, s, info = ts.synth_channel(link)
        sigma = max(np.linalg.svd(m, compute_uv=False)[0] for m in s)
        s_marginal = s / sigma          # largest singular value now exactly 1
        ours, min_eig = ts.check_passivity(s_marginal)
        self.assertFalse(ours, "a marginally passive network must be rejected")
        self.assertLessEqual(min_eig, 1e-12)
        errs = [f for f in ts.validate(freqs, s_marginal, link) if f.severity == "error"]
        self.assertTrue(any(e.check == "passivity" for e in errs), errs)

    def test_shipped_channels_have_real_passivity_margin(self):
        """Not just passive -- comfortably inside the boundary."""
        for link in self.LINKS:
            with self.subTest(link=link.name):
                _, _, s = self._net(link)
                _, min_eig = ts.check_passivity(s)
                self.assertGreater(min_eig, 1e-10,
                                   f"{link.name} sits on the passivity boundary")


# DEF orientation codes -> KLayout's fixpoint transformation codes.
# Written from the LEF/DEF spec, not from our writer, so a shared misreading
# of ORIENT would show up as a mismatch rather than agreement.
DEF_ORIENT_TO_KLAYOUT_ROT = {"N": 0, "W": 1, "S": 2, "E": 3,
                             "FS": 4, "FW": 5, "FN": 6, "FE": 7}


@unittest.skipUnless(HAS_KLAYOUT, "klayout not installed -- LEF/DEF is unvalidated externally")
class TestKlayoutReadsOurLefDef(Base):
    """LEF/DEF handed to KLayout's reader.

    DEF is the format where a misreading is most expensive and least visible:
    an ORIENT convention that our reader and writer share but the spec does not
    would place every rotated macro somewhere else in a vendor tool, and every
    round-trip test would still pass.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.die = cls.design.dies[0]
        cls.macros = cls.design.macros_on(cls.die.name)
        # Absolute paths: KLayout resolves lef_files relative to the DEF, not cwd.
        cls.lef_path = lef_io.write(cls.design, cls.out / "ext.lef", cls.prov).resolve()
        cls.def_path = def_io.write(cls.design, cls.die,
                                    cls.out / "ext.def", cls.prov).resolve()

    def _layout(self, *, with_lef: bool = True):
        import klayout.db as kdb
        ly = kdb.Layout()
        opt = kdb.LoadLayoutOptions()
        cfg = opt.lefdef_config
        if with_lef:
            cfg.lef_files = [str(self.lef_path)]
        cfg.produce_placement_blockages = True
        cfg.produce_cell_outlines = True
        cfg.produce_special_routing = True
        ly.read(str(self.def_path if with_lef else self.lef_path), opt)
        return ly

    # --- LEF ------------------------------------------------------------
    def test_klayout_sees_every_abstract_at_the_declared_size(self):
        ly = self._layout(with_lef=False)
        cells = {c.name: c.dbbox() for c in ly.each_cell()}
        for cell, (w, h) in lef_io._cells(self.design).items():
            self.assertIn(cell, cells, f"{cell} is invisible to KLayout's LEF reader")
            box = cells[cell]
            self.assertAlmostEqual(box.width(), w, places=3)
            self.assertAlmostEqual(box.height(), h, places=3)

    def test_placed_cells_resolve_against_the_lef(self):
        """The failure mode this catches: KLayout substitutes a dummy macro and
        warns rather than erroring, so an unresolvable cell reads as success."""
        placed = {m.cell for m in self.macros}
        lef_cells = {c.name for c in self._layout(with_lef=False).each_cell()}
        self.assertTrue(placed <= lef_cells,
                        f"placed but not in the LEF: {sorted(placed - lef_cells)}")

    # --- DEF ------------------------------------------------------------
    def test_units_are_interpreted_as_intended(self):
        self.assertAlmostEqual(self._layout().dbu, 1.0 / def_io.DBU_PER_UM, places=12)

    def test_design_name_and_die_area_survive(self):
        ly = self._layout()
        top = ly.top_cell()
        self.assertEqual(top.name, def_io._ident(self.die.name))
        box = top.dbbox()
        self.assertAlmostEqual(box.left, 0.0, places=3)
        self.assertAlmostEqual(box.bottom, 0.0, places=3)
        self.assertAlmostEqual(box.right, self.die.width_um, places=3)
        self.assertAlmostEqual(box.top, self.die.height_um, places=3)

    def test_every_component_lands_where_we_placed_it(self):
        """DEF's placement point is the lower-left of the bounding box *after*
        ORIENT is applied, not the untransformed origin.  KLayout applies that
        rule independently, so this is the test that would catch us emitting a
        pre-rotation origin -- our own round-trip cannot, since it would read
        the same number back out.
        """
        ly = self._layout()
        read_back = sorted(
            (inst.cell.name,
             round(inst.dbbox().left, 3), round(inst.dbbox().bottom, 3),
             inst.trans.rot)
            for inst in ly.top_cell().each_inst())
        placed = sorted(
            (m.cell, round(m.origin_um[0], 3), round(m.origin_um[1], 3),
             DEF_ORIENT_TO_KLAYOUT_ROT[m.orient])
            for m in self.macros)
        self.assertEqual(len(read_back), len(placed))
        self.assertEqual(placed, read_back)

    def test_rotated_macros_occupy_their_rotated_footprint(self):
        """A 900x600 PHY placed E must cover 600x900 of die area.  Emitting the
        unrotated extent is a silent way to overrun the edge keep-out."""
        ly = self._layout()
        by_cell_origin = {(m.cell, round(m.origin_um[0], 3), round(m.origin_um[1], 3)): m
                          for m in self.macros}
        for inst in ly.top_cell().each_inst():
            box = inst.dbbox()
            key = (inst.cell.name, round(box.left, 3), round(box.bottom, 3))
            m = by_cell_origin[key]
            w, h = m.size_um
            if m.orient in ("E", "W", "FE", "FW"):
                w, h = h, w
            self.assertAlmostEqual(box.width(), w, places=3, msg=f"{m.name} {m.orient}")
            self.assertAlmostEqual(box.height(), h, places=3, msg=f"{m.name} {m.orient}")

    def test_no_two_macros_overlap(self):
        """Placement legality, checked on the geometry a third-party reader
        builds rather than on the numbers we wrote."""
        ly = self._layout()
        boxes = [(i.cell.name, i.dbbox()) for i in ly.top_cell().each_inst()]
        clashes = []
        for idx, (name_a, a) in enumerate(boxes):
            for name_b, b in boxes[idx + 1:]:
                if a.overlaps(b):
                    clashes.append(f"{name_a}{a.to_s()} x {name_b}{b.to_s()}")
        self.assertEqual([], clashes, "overlapping placements")

    def test_no_macro_hangs_off_the_die(self):
        """An independent reader applying the spec's ORIENT semantics is the
        only way to check this: a rotated macro whose origin convention is wrong
        stays self-consistent in our own reader but leaves the die here."""
        import klayout.db as kdb
        ly = self._layout()
        die = kdb.DBox(0.0, 0.0, self.die.width_um, self.die.height_um)
        outside = [(i.cell.name, i.dbbox().to_s())
                   for i in ly.top_cell().each_inst()
                   if not die.contains(i.dbbox().p1) or not die.contains(i.dbbox().p2)]
        self.assertEqual([], outside, "macros extend past DIEAREA")

    def test_the_rot_shield_is_where_the_openroad_tcl_puts_the_rot(self):
        """Two guard-bands 7mm apart is how this started: the DEF writer used
        the die centre, gen_def.py used (w/2, 2000).  Both now read the origin
        from canonical, and KLayout reports where the blockage actually landed.
        """
        import klayout.db as kdb
        from integrations.canonical import ROT_KEEPOUT_UM, rot_origin_um
        ly = self._layout()
        idx = [i for i in ly.layer_indexes()
               if "PLACEMENT" in ly.get_info(i).name.upper()]
        self.assertEqual(1, len(idx), "expected exactly one placement-blockage layer")
        shapes = [s.dbbox() for s in ly.top_cell().each_shape(idx[0])]
        self.assertEqual(1, len(shapes), "expected exactly one RoT shield")
        cx, cy = rot_origin_um(self.die)
        want = kdb.DBox(cx - ROT_KEEPOUT_UM, cy - ROT_KEEPOUT_UM,
                        cx + ROT_KEEPOUT_UM, cy + ROT_KEEPOUT_UM)
        got = shapes[0]
        for attr in ("left", "bottom", "right", "top"):
            self.assertAlmostEqual(getattr(got, attr), getattr(want, attr), places=3,
                                   msg=f"shield {got.to_s()} != {want.to_s()}")
        intruding = [i.cell.name for i in ly.top_cell().each_inst()
                     if i.dbbox().overlaps(want)]
        self.assertEqual([], intruding, "macro inside the RoT EM shield")

    def test_power_stripes_and_keepout_reach_the_reader(self):
        ly = self._layout()
        layers = {ly.get_info(i).name for i in ly.layer_indexes()}
        for stripe in self.design.stripes:
            self.assertTrue(any(name.startswith(stripe.layer) for name in layers),
                            f"SPECIALNETS layer {stripe.layer} not read back: {sorted(layers)}")
        self.assertTrue(any("PLACEMENT" in name.upper() for name in layers),
                        f"RoT placement blockage not read back: {sorted(layers)}")


@unittest.skipUnless(HAS_LIBERTY, "liberty-parser not installed -- Liberty is unvalidated externally")
class TestLibertyParserReadsOurLib(Base):
    """Our .lib handed to a real Liberty grammar.

    liberty_io.read is a set of regexes.  Regexes are exactly the tool that
    cannot tell a `timing ()` group inside a cell from the word appearing in a
    comment, which matters here because "no fabricated timing arcs" is a claim
    the project makes rather than a formatting preference.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from liberty.parser import parse_liberty
        cls.path = liberty_io.write(cls.design, cls.out / "ext.lib", cls.prov)
        cls.lib = parse_liberty(cls.path.read_text())
        cls.cells = {c.args[0]: c for c in cls.lib.get_groups("cell")}

    def test_the_library_parses_under_a_real_liberty_grammar(self):
        self.assertEqual(["3dic_x_macros"], list(self.lib.args))
        self.assertEqual(sorted(lef_io._cells(self.design)), sorted(self.cells))

    def test_no_timing_arc_survives_an_independent_parser(self):
        """The rule the project states: uncharacterized macros must not ship
        cell_rise/cell_fall tables."""
        for name, cell in self.cells.items():
            with self.subTest(cell=name):
                self.assertEqual([], list(cell.get_groups("timing")))
                self.assertEqual([], list(cell.get_groups("internal_power")))

    def test_operating_point_matches_the_design_record(self):
        self.assertAlmostEqual(float(self.lib["nom_temperature"]),
                               self.design.op_temp_c, places=3)
        self.assertAlmostEqual(float(self.lib["nom_voltage"]),
                               self.design.vdd_v, places=6)

    def test_pin_directions_and_power_pins_are_what_we_declared(self):
        for cell_name, pins in lef_io.PIN_SETS.items():
            if cell_name not in self.cells:
                continue
            cell = self.cells[cell_name]
            with self.subTest(cell=cell_name):
                got_sig = {str(g.args[0]): str(g["direction"])
                           for g in cell.get_groups("pin")}
                got_pg = {str(g.args[0]) for g in cell.get_groups("pg_pin")}
                for pin, direction in pins:
                    if direction == "INOUT" and ("VDD" in pin or "VSS" in pin):
                        self.assertIn(pin, got_pg)
                    else:
                        self.assertEqual(direction.lower(), got_sig.get(pin),
                                         f"{cell_name}/{pin}")

    @unittest.skipUnless(HAS_KLAYOUT, "klayout not installed")
    def test_liberty_area_agrees_with_the_lef_abstract(self):
        """Cross-format, cross-parser: KLayout reads the macro extent from LEF,
        liberty-parser reads the area from .lib.  A downstream flow uses both,
        and nothing in this repo previously compared them.
        """
        import klayout.db as kdb
        ly = kdb.Layout()
        opt = kdb.LoadLayoutOptions()
        ly.read(str(lef_io.write(self.design, self.out / "area.lef", self.prov).resolve()),
                opt)
        for cell in ly.each_cell():
            if cell.name not in self.cells:
                continue
            box = cell.dbbox()
            with self.subTest(cell=cell.name):
                self.assertAlmostEqual(float(self.cells[cell.name]["area"]),
                                       box.width() * box.height(), places=3)


class TestExternalCoverageIsDeclared(unittest.TestCase):
    """Make the gap visible: which formats have no external validator here."""

    def test_report_external_validator_coverage(self):
        from integrations.interchange import spice_io
        coverage = {
            "GDSII": HAS_GDSTK,
            "Touchstone": HAS_SKRF,
            "SPICE": spice_io.ngspice_available(),
            "DEF": HAS_KLAYOUT,
            "LEF": HAS_KLAYOUT,
            "SPEF": False,       # needs OpenROAD / PrimeTime
            "Liberty": HAS_LIBERTY,
            "IBIS": False,       # needs ibischk7
        }
        externally_checked = [k for k, v in coverage.items() if v]
        self.assertTrue(externally_checked, "no external validators available at all")
        # Documented, not asserted away: these remain self-validated only.
        self.assertEqual(
            sorted(k for k, v in coverage.items() if not v),
            ["IBIS", "SPEF"],
            "external-validator coverage changed -- update spec section 10")


if __name__ == "__main__":
    unittest.main()
