"""The surrogate, checked against an implementation nobody here wrote.

`tests/integrations/test_external_parsers.py` states the rule for the file
formats: our writer and our reader agreeing proves only that they agree, so
every emitted format is handed to a foreign implementation. The surrogate never
had that check. Its FNO is hand-written in `train.py`, trained by our loop and
scored by our scripts; a misreading of Li et al. 2020 in the spectral
convolution would be invisible from inside.

NVIDIA PhysicsNeMo (formerly Modulus) ships a production FNO. These tests map
our weights onto it and require the two to agree -- the same role gdstk plays
for GDSII, applied to the operator rather than to a file.

They also check the two ways the surrogate can leave this repository:

    .mdlus  PhysicsNeMo's own checkpoint, which rebuilds the architecture from
            the file. Self-describing only to a receiver who has PhysicsNeMo
            and `physicsnemo_bridge`.
    ONNX    self-describing to anyone. Needs the real-arithmetic spectral
            layers; the complex einsum has no ONNX decomposition, which is why
            PhysicsNeMo's own FNO metadata declares onnx_cpu=False.

Every test skips loudly when its dependency is absent, so a missing package can
never be mistaken for a passing check.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "physics_accelerated/src"
sys.path.insert(0, str(SRC))

from train import FNO2d                                     # noqa: E402

HAS_PHYSICSNEMO = importlib.util.find_spec("physicsnemo") is not None
HAS_ONNX = importlib.util.find_spec("onnx") is not None
HAS_ORT = importlib.util.find_spec("onnxruntime") is not None

CKPT = REPO / "physics_accelerated/results/fno_model_mixedz2_lam0p1.pt"
STATS = REPO / "physics_accelerated/results/norm_stats_mixedz2_lam0p1.pt"
X_TEST = REPO / "physics_accelerated/data/x_mixed_z2_test.pt"
Y_TEST = REPO / "physics_accelerated/data/y_mixed_z2_test.pt"
FRONT = REPO / "reports/pareto_front_nsga2.json"

# Trained weights and datasets are build artifacts, so a fresh clone has none.
HAS_MODEL = CKPT.exists() and STATS.exists()
HAS_DATA = X_TEST.exists() and Y_TEST.exists()

# float32 round-off through four spectral layers, two FFTs each. Not a fitted
# tolerance: a real architectural mismatch lands in whole kelvin, and the
# decisions this surrogate informs are tens of kelvin apart.
TOL_K = 1e-3


@unittest.skipUnless(HAS_PHYSICSNEMO,
                     "physicsnemo not installed -- the surrogate is "
                     "unvalidated against any foreign implementation")
@unittest.skipUnless(HAS_MODEL, f"no surrogate at {CKPT.name}; train it first")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import physicsnemo_bridge as bridge
        cls.bridge = bridge
        state = torch.load(CKPT, map_location="cpu", weights_only=True)
        cls.channels = state["fc2.bias"].numel()
        stats = torch.load(STATS, map_location="cpu", weights_only=True)
        cls.mean, cls.std = float(stats["mean"]), float(stats["std"])
        cls.ours = FNO2d(modes1=bridge.MODES, modes2=bridge.MODES,
                         width=bridge.WIDTH, layers=cls.channels)
        cls.ours.load_state_dict(state)
        cls.ours.eval()
        cls.theirs = bridge.load(CKPT)

    def max_abs_k(self, x: torch.Tensor, a=None, b=None) -> float:
        """Largest disagreement over `x`, in kelvin."""
        with torch.no_grad():
            a = self.ours(x) if a is None else a
            b = self.theirs(x) if b is None else b
        return float((a - b).abs().max()) * self.std


class TestWeightTranslation(Base):
    def test_translation_is_total(self):
        """Every parameter of the PhysicsNeMo model comes from our checkpoint.

        `load` already loads strictly, so this asserts the converse: that the
        translation invents nothing and leaves nothing at its initial value.
        """
        state = torch.load(CKPT, map_location="cpu", weights_only=True)
        translated = self.bridge.translate(state)
        self.assertEqual(set(translated), set(self.theirs.state_dict()))

    def test_parameter_count_matches_once_complex_is_counted_as_two_reals(self):
        """Ours stores spectral weights as cfloat, theirs as real pairs, so the
        raw counts differ by exactly the number of complex weights."""
        ours = sum(p.numel() for p in self.ours.parameters())
        theirs = sum(p.numel() for p in self.theirs.parameters())
        complex_weights = sum(p.numel() for p in self.ours.parameters()
                              if p.is_complex())
        self.assertEqual(theirs, ours + complex_weights)

    def test_no_domain_padding(self):
        """PhysicsNeMo pads the domain by 8 cells before the FFT by default.
        We never trained that way, and the default would make the two disagree
        for a reason unrelated to either being wrong."""
        self.assertEqual(self.theirs.padding, 0)


class TestFieldEquivalence(Base):
    def test_random_input(self):
        torch.manual_seed(0)
        x = torch.randn(8, self.channels, 16, 16)
        self.assertLess(self.max_abs_k(x), TOL_K)

    @unittest.skipUnless(HAS_DATA, "no z-refined test set; run dataset.py")
    def test_held_out_power_maps(self):
        x = torch.load(X_TEST, map_location="cpu", weights_only=True)
        self.assertLess(self.max_abs_k(x), TOL_K)

    def test_off_training_resolution(self):
        """An FNO is meant to be discretisation-invariant, and mode truncation
        is where two implementations most plausibly diverge: at 16x16 with 8
        modes the upper and lower mode blocks are exactly adjacent, and ours
        assigns into them while PhysicsNeMo accumulates."""
        torch.manual_seed(1)
        for grid in (16, 32, 64):
            with self.subTest(grid=grid):
                x = torch.randn(2, self.channels, grid, grid)
                self.assertLess(self.max_abs_k(x), TOL_K)

    @unittest.skipUnless(HAS_DATA, "no z-refined test set; run dataset.py")
    def test_accuracy_against_labels_is_the_same_number(self):
        x = torch.load(X_TEST, map_location="cpu", weights_only=True)
        y = torch.load(Y_TEST, map_location="cpu", weights_only=True)
        rmse = {}
        for name, model in (("ours", self.ours), ("physicsnemo", self.theirs)):
            with torch.no_grad():
                pred = model(x) * self.std + self.mean
            rmse[name] = float(torch.sqrt(((pred - y) ** 2).mean()))
        self.assertAlmostEqual(rmse["ours"], rmse["physicsnemo"], places=4,
                               msg=f"held-out field RMSE differs: {rmse}")


@unittest.skipUnless(FRONT.exists(), "no published front; run pareto_search.py")
class TestDecisionsUnchanged(Base):
    """The question this project judges a surrogate by is not RMSE but whether
    the design the search selects, and the order it ranks the front in, holds."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from pareto_search import build_power_maps, adapt_maps, N_SUB
        from pareto import pareto_front
        cls.pareto_front = staticmethod(pareto_front)
        cfg = json.loads((SRC.parent / "results/golden_config.json").read_text())
        total_w = float(cfg["max_power_budget_w"])
        layers = int(cfg["voxel_stack_params"]["layers"])
        doc = json.loads(FRONT.read_text())
        keys = doc.get("genome_keys") or list(doc["front_genomes"][0])
        cls.genomes = np.array([[g[k] for k in keys]
                                for g in doc["front_genomes"]], dtype=float)
        maps = build_power_maps(cls.genomes, total_w * 0.75, total_w * 0.25, layers)
        cls.x = adapt_maps(maps, cls.ours)
        cls.per_layer = max(1, cls.channels // layers)
        cls.n_sub = N_SUB

    def objectives(self, model) -> np.ndarray:
        """(logic peak Tj, memory peak Tj, interconnect span) -- the three the
        search minimises. Span is geometry and identical for both; including it
        makes the dominance comparison the real one rather than a 2D proxy."""
        with torch.no_grad():
            field = model(self.x) * self.std + self.mean
        logic = field[:, :self.per_layer].amax(dim=(1, 2, 3)).numpy()
        memory = field[:, self.per_layer:2 * self.per_layer].amax(dim=(1, 2, 3)).numpy()
        span = []
        for g in self.genomes:
            pts = [(g[2 * s], g[2 * s + 1]) for s in range(self.n_sub)]
            cx = sum(p[0] for p in pts) / self.n_sub
            cy = sum(p[1] for p in pts) / self.n_sub
            internal = sum(abs(p[0] - cx) + abs(p[1] - cy) for p in pts)
            span.append(internal + abs(cx - g[2 * self.n_sub])
                        + abs(cy - g[2 * self.n_sub + 1]))
        return np.column_stack([logic, memory, np.array(span)])

    def test_non_dominated_set_is_identical(self):
        a, b = self.objectives(self.ours), self.objectives(self.theirs)
        self.assertEqual(set(self.pareto_front(a)), set(self.pareto_front(b)))

    def test_rank_order_and_pick_are_identical(self):
        a, b = self.objectives(self.ours), self.objectives(self.theirs)
        np.testing.assert_array_equal(np.argsort(a[:, 0]), np.argsort(b[:, 0]))

    def test_peak_tj_agrees_far_inside_the_decision_margin(self):
        a, b = self.objectives(self.ours), self.objectives(self.theirs)
        self.assertLess(float(np.abs(a[:, :2] - b[:, :2]).max()), TOL_K)


class TestHandoffArtifacts(Base):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="3dicx-pn-")
        self.out = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_mdlus_rebuilds_the_architecture_from_the_file(self):
        """`Module.from_checkpoint` reconstructs from the stored constructor
        arguments, not from our source. It fails on a stock FNO whose lift was
        swapped after construction, which is why the bridge is a subclass."""
        import physicsnemo
        path = self.out / "surrogate.mdlus"
        self.theirs.save(str(path))
        reloaded = physicsnemo.Module.from_checkpoint(str(path))
        reloaded.eval()
        self.assertEqual(type(reloaded).__name__, "ThermalFNO")
        torch.manual_seed(2)
        x = torch.randn(4, self.channels, 16, 16)
        with torch.no_grad():
            self.assertEqual(float((self.theirs(x) - reloaded(x)).abs().max()), 0.0)

    def test_export_shim_matches_the_complex_layer(self):
        """The real-arithmetic spectral layer exists only to be exportable. If
        it does not reproduce the complex one, the ONNX artifact is a different
        model wearing the same name."""
        torch.manual_seed(3)
        x = torch.randn(4, self.channels, 16, 16)
        shim = self.bridge.load(CKPT, exportable=True)
        with torch.no_grad():
            d = float((self.theirs(x) - shim(x)).abs().max()) * self.std
        self.assertLess(d, TOL_K)

    @unittest.skipUnless(HAS_ONNX, "onnx not installed -- the self-describing "
                                   "handoff artifact is unvalidated")
    def test_onnx_passes_an_independent_checker(self):
        import onnx
        path = self.bridge.export_onnx(CKPT, self.out / "surrogate.onnx")
        onnx.checker.check_model(onnx.load(str(path)), full_check=True)

    @unittest.skipUnless(HAS_ORT, "onnxruntime not installed -- the exported "
                                  "graph is parsed but never executed")
    def test_onnxruntime_reproduces_the_field(self):
        """Parsing proves the file is well formed; only running it proves the
        receiver gets our model. Batch is dynamic, so this must run at a batch
        size the export never saw."""
        import onnxruntime as ort
        path = self.bridge.export_onnx(CKPT, self.out / "surrogate.onnx")
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        torch.manual_seed(4)
        x = torch.rand(32, self.channels, 16, 16) * 5.0
        got = torch.from_numpy(sess.run(None, {"power_w_per_cell": x.numpy()})[0])
        with torch.no_grad():
            want = self.bridge.load(CKPT, exportable=True)(x)
        self.assertLess(float((got - want).abs().max()) * self.std, TOL_K)


if __name__ == "__main__":
    unittest.main(verbosity=2)
