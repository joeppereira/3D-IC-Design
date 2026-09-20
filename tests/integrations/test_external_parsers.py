"""Validation against independently-written parsers.

The round-trip tests in test_interchange.py prove our writer and our reader
agree.  If both share a misreading of the format spec, they agree and are both
wrong.  These tests close that gap by handing the artifacts to implementations
nobody here wrote:

    gdstk      -- GDSII, independent C++ implementation
    scikit-rf  -- Touchstone + RF network theory
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
from integrations.interchange import gds_io, touchstone_io as ts

HAS_GDSTK = importlib.util.find_spec("gdstk") is not None
HAS_SKRF = importlib.util.find_spec("skrf") is not None


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


class TestExternalCoverageIsDeclared(unittest.TestCase):
    """Make the gap visible: which formats have no external validator here."""

    def test_report_external_validator_coverage(self):
        from integrations.interchange import spice_io
        coverage = {
            "GDSII": HAS_GDSTK,
            "Touchstone": HAS_SKRF,
            "SPICE": spice_io.ngspice_available(),
            "DEF": False,        # needs OpenROAD / a vendor reader
            "LEF": False,
            "SPEF": False,       # needs OpenROAD / PrimeTime
            "Liberty": False,
            "IBIS": False,       # needs ibischk7
        }
        externally_checked = [k for k, v in coverage.items() if v]
        self.assertTrue(externally_checked, "no external validators available at all")
        # Documented, not asserted away: these remain self-validated only.
        self.assertEqual(
            sorted(k for k, v in coverage.items() if not v),
            ["DEF", "IBIS", "LEF", "Liberty", "SPEF"],
            "external-validator coverage changed -- update spec section 10")


if __name__ == "__main__":
    unittest.main()
