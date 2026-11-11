"""The exported surrogate must be the same model a consumer thinks it is.

`surrogate_export` exists so another project can run our trained surrogate
without importing this repository. That is only worth anything if the exported
graph computes what `train.FNO2d` computes, and if the contract shipped beside
it describes the graph it is shipped with. Both are asserted here rather than
asserted in prose.

The foreign reader is `onnxruntime`: it has none of our code, so if our export
is wrong it has no way to be wrong in the same direction. Same role gdstk plays
for GDSII in `tests/integrations/test_external_parsers.py`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "physics_accelerated/src"
sys.path.insert(0, str(SRC))

import surrogate_export as sx                                   # noqa: E402

HAS_ONNX = importlib.util.find_spec("onnx") is not None
HAS_ORT = importlib.util.find_spec("onnxruntime") is not None
HAS_SCRIPT = importlib.util.find_spec("onnxscript") is not None
HAS_MODEL = sx.DEFAULT_MODEL.exists() and sx.DEFAULT_STATS.exists()

# float32 round-off through four spectral layers. An architectural mismatch
# lands in whole kelvin; the decisions this feeds are tens of kelvin apart.
TOL_K = 1e-3


@unittest.skipUnless(HAS_MODEL, "no trained surrogate; weights are build artifacts")
class TestExportableMatchesTheRealModel(unittest.TestCase):
    """The export shim rewrites the spectral multiply in real arithmetic. If it
    does not reproduce the complex one, the artifact is a different model
    wearing the same name."""

    @classmethod
    def setUpClass(cls):
        cls.exportable = sx.load()
        cls.reference = sx.reference()
        stats = torch.load(sx.DEFAULT_STATS, map_location="cpu", weights_only=True)
        cls.std = float(stats["std"])
        cls.channels = cls.exportable.channels

    def _max_abs_k(self, x):
        with torch.no_grad():
            return float((self.reference(x) - self.exportable(x)).abs().max()) * self.std

    def test_random_input(self):
        torch.manual_seed(0)
        x = torch.randn(8, self.channels, 16, 16)
        self.assertLess(self._max_abs_k(x), TOL_K)

    def test_realistic_power_maps(self):
        """Non-negative, concentrated power -- what the search actually feeds."""
        torch.manual_seed(1)
        x = torch.zeros(6, self.channels, 16, 16)
        for i in range(6):
            for ch in range(2):
                r, c = torch.randint(0, 13, (2,))
                x[i, ch, r:r + 4, c:c + 4] = 3.0
        self.assertLess(self._max_abs_k(x), TOL_K)

    def test_off_training_resolution(self):
        """Mode truncation is where two implementations diverge: at 16x16 with
        8 modes the upper and lower blocks are exactly adjacent, and the shim
        pads-and-adds where FNO2d assigns."""
        torch.manual_seed(2)
        for grid in (16, 32, 64):
            with self.subTest(grid=grid):
                x = torch.randn(2, self.channels, grid, grid)
                self.assertLess(self._max_abs_k(x), TOL_K)

    def test_parameter_counts_agree_as_reals(self):
        ours = sum(p.numel() for p in self.reference.parameters())
        cplx = sum(p.numel() for p in self.reference.parameters() if p.is_complex())
        self.assertEqual(sum(p.numel() for p in self.exportable.parameters()),
                         ours + cplx)


@unittest.skipUnless(HAS_MODEL, "no trained surrogate; weights are build artifacts")
class TestContract(unittest.TestCase):
    """The contract is the only thing standing between a consumer and a silent
    unit error, so it has to agree with the weights it ships with."""

    @classmethod
    def setUpClass(cls):
        cls.doc = sx.contract()
        cls.model = sx.load()

    def test_declared_shape_matches_the_weights(self):
        self.assertEqual(self.doc["input"]["shape"][1], self.model.channels)
        self.assertEqual(self.doc["output"]["shape"][1], self.model.channels)

    def test_denormalisation_matches_the_stats_file(self):
        stats = torch.load(sx.DEFAULT_STATS, map_location="cpu", weights_only=True)
        self.assertAlmostEqual(self.doc["output"]["mean"], float(stats["mean"]), 6)
        self.assertAlmostEqual(self.doc["output"]["std"], float(stats["std"]), 6)

    def test_channel_layout_covers_every_channel(self):
        """A z-refined model has two channels per physical layer. A consumer
        that assumes one gets the wrong die."""
        layers = len(self.doc["input"]["layer_names"])
        self.assertEqual(self.model.channels % layers, 0)
        per_layer = self.model.channels // layers
        self.assertEqual(self.doc["input"]["logic_die_channels"],
                         list(range(per_layer)))
        self.assertEqual(self.doc["input"]["memory_die_channels"],
                         list(range(per_layer, 2 * per_layer)))

    def test_tier_is_not_overstated(self):
        """No licensed vendor tool has ever opened an artifact from this repo."""
        self.assertEqual(self.doc["validation"]["tier"], "T0")

    def test_known_defects_are_declared(self):
        """The edge wrap is a measured defect a consumer must be told about."""
        self.assertTrue(self.doc["known_defects"])
        wrap = [d for d in self.doc["known_defects"] if "circular" in d["what"]]
        self.assertTrue(wrap, "the boundary wrap must be declared")
        self.assertGreater(wrap[0]["magnitude_k"], 10.0)

    def test_claim_limit_present(self):
        self.assertIn("exploration only", self.doc["claim_limit"].lower())


@unittest.skipUnless(HAS_MODEL, "no trained surrogate; weights are build artifacts")
@unittest.skipUnless(HAS_ONNX and HAS_SCRIPT,
                     "onnx/onnxscript missing -- the handoff artifact is "
                     "unvalidated; pip install onnx onnxscript")
class TestOnnxArtifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="3dicx-sx-")
        cls.out = Path(cls._tmp.name)
        cls.doc = sx.export(cls.out)
        cls.path = cls.out / "surrogate.onnx"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_bundle_is_complete(self):
        self.assertTrue(self.path.exists())
        self.assertTrue((self.out / "surrogate_contract.json").exists())
        json.loads((self.out / "surrogate_contract.json").read_text())

    def test_independent_checker_accepts_the_graph(self):
        import onnx
        onnx.checker.check_model(onnx.load(str(self.path)), full_check=True)

    def test_declared_io_names_are_the_graph_io_names(self):
        """A contract naming inputs the graph does not have is worse than none."""
        import onnx
        g = onnx.load(str(self.path)).graph
        self.assertIn(self.doc["input"]["name"], [i.name for i in g.input])
        self.assertIn(self.doc["output"]["name"], [o.name for o in g.output])

    @unittest.skipUnless(HAS_ORT, "onnxruntime missing -- the graph is parsed "
                                  "but never executed; pip install onnxruntime")
    def test_onnxruntime_reproduces_the_field(self):
        """Parsing proves well-formedness; only running it proves a consumer
        gets our model. Batch is dynamic, so this runs at a size the export
        never traced."""
        import onnxruntime as ort
        sess = ort.InferenceSession(str(self.path),
                                    providers=["CPUExecutionProvider"])
        torch.manual_seed(3)
        x = torch.rand(16, sx.load().channels, 16, 16) * 4.0
        got = torch.from_numpy(
            sess.run(None, {self.doc["input"]["name"]: x.numpy()})[0])
        with torch.no_grad():
            want = sx.reference()(x)
        self.assertLess(float((got - want).abs().max()) * self.doc["output"]["std"],
                        TOL_K)

    @unittest.skipUnless(HAS_ORT, "onnxruntime missing")
    def test_contract_recipe_gives_celsius(self):
        """Follow the contract literally and the numbers must be plausible
        temperatures -- this is the consumer's first five minutes."""
        import onnxruntime as ort
        sess = ort.InferenceSession(str(self.path),
                                    providers=["CPUExecutionProvider"])
        ch = self.doc["input"]["shape"][1]
        power = torch.zeros(1, ch, 16, 16)
        for c in self.doc["input"]["logic_die_channels"]:
            power[0, c, 6:10, 6:10] = 45.0 / 16 / len(
                self.doc["input"]["logic_die_channels"])
        y = sess.run(None, {self.doc["input"]["name"]: power.numpy()})[0]
        t_c = y * self.doc["output"]["std"] + self.doc["output"]["mean"]
        logic = t_c[0, self.doc["input"]["logic_die_channels"]]
        peak = float(logic.max())
        self.assertGreater(peak, 25.0, "a powered die must be above ambient")
        self.assertLess(peak, 400.0, "de-normalisation looks wrong")


if __name__ == "__main__":
    unittest.main(verbosity=2)
