"""Verification tests for the thermal reference, the FDM solver, the physics
residual, and NSGA-II.

The ordering is deliberate: each layer is checked against something more
trustworthy than itself.

    reference solver  <- analytic 1D slab conduction, global energy balance
    FDM solver        <- the reference solver (different method, same equations)
    heat residual     <- a converged field (residual must vanish)
    NSGA-II           <- ZDT1, whose Pareto front is known analytically
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "physics_accelerated", "src"))
sys.path.insert(0, os.path.join(ROOT, "serdes_architect", "src"))

from thermal_reference import (ThermalReference, Layer, Boundary,      # noqa: E402
                              analytic_slab_peak_c)
from heat_residual import HeatEquationResidual                          # noqa: E402
from thermal.solver import ThermalSolver                                # noqa: E402
from thermal.transient_solver import TransientThermalSolver             # noqa: E402
import pareto as P                                                      # noqa: E402

GOLDEN = os.path.join(ROOT, "physics_accelerated", "results", "golden_config.json")


class TestReferenceSolver(unittest.TestCase):
    """The reference is only a reference if it reproduces known answers."""

    def _slab(self, n_cells_z=8):
        self.L, self.k, self.h, self.P, self.W = 500e-6, 150.0, 5000.0, 100.0, 10e-3
        return ThermalReference(
            [Layer("slab", self.L, self.k, self.P, n_cells_z=n_cells_z)],
            self.W, self.W,
            Boundary(h_top_w_m2k=self.h, h_bottom_w_m2k=0.0,
                     h_side_w_m2k=0.0, t_ambient_c=25.0))

    def test_matches_analytic_slab(self):
        ref = self._slab()
        sol = ref.solve(nx=8, ny=8, refine_z=8)
        exact = analytic_slab_peak_c(self.P, self.W ** 2, self.L, self.k,
                                     self.h, 25.0)
        self.assertAlmostEqual(sol.t_peak_c, exact, places=5)

    def test_conserves_energy(self):
        sol = self._slab().solve(nx=8, ny=8, refine_z=4)
        self.assertLess(sol.energy_balance["relative_error"], 1e-9)

    def test_peak_scales_linearly_with_power(self):
        """Linear conduction: doubling the power doubles the rise."""
        base = self._slab()
        s1 = base.solve(nx=6, ny=6, refine_z=4)
        base.layers[0].power_w *= 2.0
        s2 = base.solve(nx=6, ny=6, refine_z=4)
        rise1, rise2 = s1.t_peak_c - 25.0, s2.t_peak_c - 25.0
        self.assertAlmostEqual(rise2 / rise1, 2.0, places=6)

    def test_better_cooling_lowers_peak(self):
        cold = self._slab()
        cold.bc.h_top_w_m2k = 50_000.0
        hot = self._slab()
        hot.bc.h_top_w_m2k = 500.0
        self.assertLess(cold.solve(nx=6, ny=6, refine_z=2).t_peak_c,
                        hot.solve(nx=6, ny=6, refine_z=2).t_peak_c)

    def test_exact_on_the_analytic_benchmark_at_every_mesh(self):
        """Stronger than an order-of-accuracy claim: on the 1D uniform-source
        benchmark this discretisation is exact, so the error sits at round-off
        regardless of mesh. Order of accuracy is therefore not measurable here --
        and claiming "second order" from this case would be wrong.
        """
        exact = analytic_slab_peak_c(100.0, 1e-4, 500e-6, 150.0, 5000.0, 25.0)
        for n in (2, 8, 32):
            ref = ThermalReference(
                [Layer("slab", 500e-6, 150.0, 100.0, n_cells_z=n)], 10e-3, 10e-3,
                Boundary(h_top_w_m2k=5000.0, h_bottom_w_m2k=0.0,
                         h_side_w_m2k=0.0, t_ambient_c=25.0))
            with self.subTest(n_cells_z=n):
                self.assertAlmostEqual(ref.solve(nx=4, ny=4).t_peak_c, exact,
                                       delta=1e-8)

    def test_mesh_convergence_reaches_a_grid_converged_answer(self):
        """On a realistic (discontinuous) hotspot source the formal order is
        outside the asymptotic range -- the discrete footprint of the hotspot
        changes as the mesh refines. What must hold is that the extrapolated
        value is reliable: a small grid-convergence index.
        """
        layers = [Layer("die", 50e-6, 140.0, 40.0, n_cells_z=1),
                  Layer("pkg", 500e-6, 100.0, 0.0, n_cells_z=1)]
        ref = ThermalReference(layers, 18e-3, 18e-3,
                              Boundary(h_top_w_m2k=8000.0, h_bottom_w_m2k=50.0,
                                       h_side_w_m2k=0.0, t_ambient_c=45.0))
        conv = ref.mesh_convergence(base_nx=10, levels=3,
                                    hotspots={0: (0.5, 0.5, 0.3)})
        self.assertEqual(len(conv["runs"]), 3)
        self.assertTrue(conv["converged"], conv)
        self.assertLess(conv["gci_finest_pct"], 1.0)
        # successive refinements must be settling, not diverging
        peaks = [r["t_peak_c"] for r in conv["runs"]]
        self.assertLess(abs(peaks[2] - peaks[1]), abs(peaks[1] - peaks[0]))
        for r in conv["runs"]:
            self.assertLess(r["energy_rel_err"], 1e-9)

    def test_rejects_stackup_without_declared_units(self):
        import json
        import tempfile
        from thermal_reference import from_stackup
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"units": {"length": "mm"}, "dies": []}, fh)
            path = fh.name
        with self.assertRaises(ValueError):
            from_stackup(path)
        os.unlink(path)


class TestFdmSolver(unittest.TestCase):
    """The production solver, checked against the reference."""

    @classmethod
    def setUpClass(cls):
        cls.solver = ThermalSolver(GOLDEN)
        cls.G = cls.solver.grid_size

    def _hotspot(self, watts=10.0):
        p = torch.zeros((1, self.solver.layers, self.G, self.G))
        c = self.G // 2
        p[0, 0, c - 1:c + 1, c - 1:c + 1] = watts / 4.0
        return p

    def test_uses_real_geometry_not_a_normalised_grid(self):
        """Regression guard: dx used to be hardcoded to 1.0 with a
        PHYSICAL_SCALE=500 fudge calibrated for a different die size."""
        self.assertAlmostEqual(self.solver.dx, self.solver.width_m / self.G)
        self.assertGreater(self.solver.dx, 1e-6)
        self.assertLess(self.solver.dx, 1e-2)
        # The fudge constant must not be *used*; the docstring may still
        # describe why it was removed.
        src = open(os.path.join(ROOT, "serdes_architect", "src", "thermal",
                                "solver.py")).read()
        code = [ln for ln in src.splitlines()
                if "PHYSICAL_SCALE" in ln and not ln.strip().startswith("#")
                and "hand-tuned" not in ln]
        self.assertEqual([], code, f"PHYSICAL_SCALE still in use: {code}")

    def test_conserves_energy(self):
        p = self._hotspot()
        t = self.solver.solve_steady_state(p)
        self.assertLess(self.solver.energy_balance(t, p)["relative_error"], 1e-2)

    def test_converges_to_a_tolerance(self):
        self.solver.solve_steady_state(self._hotspot(), tol=1e-5)
        self.assertLess(self.solver.final_delta, 1e-5)
        self.assertGreater(self.solver.iterations_used, 1)

    def test_agrees_with_the_reference_solver(self):
        """Different method, same discretisation -> must agree closely."""
        p = self._hotspot()
        t_fdm = float(self.solver.solve_steady_state(p).max())
        layers = [Layer(m, float(self.solver.dz[i]), float(self.solver.k[i]),
                        0.0, n_cells_z=1)
                  for i, m in enumerate(self.solver.layer_materials)]
        ref = ThermalReference(layers, self.solver.width_m, self.solver.depth_m,
                               Boundary(h_top_w_m2k=self.solver.h_top,
                                        h_bottom_w_m2k=self.solver.h_bottom,
                                        h_side_w_m2k=0.0,
                                        t_ambient_c=self.solver.t_ambient))
        q = p[0].numpy()

        def density(nx, ny, layer_of, hotspots):
            out = np.zeros((len(layer_of), ny, nx))
            for li in range(q.shape[0]):
                cells = np.where(layer_of == li)[0]
                for cz in cells:
                    out[cz] = q[li] / len(cells)
            return out

        ref._power_density = density
        t_ref = ref.solve(nx=self.G, ny=self.G, refine_z=1).t_field_c.max()
        self.assertLess(abs(t_fdm - t_ref), 0.05,
                        f"FDM {t_fdm:.4f} vs reference {t_ref:.4f}")

    def test_refuses_unknown_material_instead_of_defaulting(self):
        """A missing k used to fall through to 1.0 W/mK, modelling the Cu-Cu
        hybrid bond as an insulator and inflating peak Tj by ~6 C."""
        import copy
        import json
        import tempfile
        cfg = json.loads(open(GOLDEN).read())
        cfg["voxel_stack_params"]["k_map"].pop("Hybrid_Bond", None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(cfg, fh)
            path = fh.name
        with self.assertRaises(KeyError):
            ThermalSolver(path)
        os.unlink(path)

    def test_hotter_source_gives_hotter_peak(self):
        t_low = float(self.solver.solve_steady_state(self._hotspot(5.0)).max())
        t_high = float(self.solver.solve_steady_state(self._hotspot(20.0)).max())
        self.assertGreater(t_high, t_low)


class TestTransientSolver(unittest.TestCase):
    """The transient solver, checked against an exact solution and the
    steady-state solver it must agree with in the limit."""

    @classmethod
    def setUpClass(cls):
        cls.solver = TransientThermalSolver(GOLDEN)
        cls.G = cls.solver.grid_size

    def _hotspot(self, watts=10.0):
        p = torch.zeros((1, self.solver.layers, self.G, self.G),
                        dtype=torch.float64)
        c = self.G // 2
        p[0, 0, c - 1:c + 1, c - 1:c + 1] = watts / 4.0
        return p

    def test_no_magic_constants_remain(self):
        """Regression guard for the three the audit named: PHYSICAL_SCALE=500,
        a bare *2000.0 on the source, and `diffusivity` used as a relaxation
        factor. The module docstring may still explain why they went."""
        import ast
        src = open(os.path.join(ROOT, "serdes_architect", "src", "thermal",
                                "transient_solver.py")).read()
        doc = ast.get_docstring(ast.parse(src))
        code = src.replace(doc, "") if doc else src
        code = "\n".join(ln for ln in code.splitlines()
                         if not ln.strip().startswith("#"))
        for token in ("PHYSICAL_SCALE", "2000.0", "self.diffusivity"):
            self.assertNotIn(token, code, f"{token} still in use")

    def test_every_material_has_a_declared_heat_capacity(self):
        self.assertEqual(self.solver.layers, len(self.solver.capacitance))
        self.assertTrue(bool((self.solver.capacitance > 0).all()))

    def test_refuses_unknown_heat_capacity_instead_of_defaulting(self):
        """Same rule as the k_map, for the same reason: an unstated thermal
        mass silently changes every time constant in the result."""
        import transient_solver as TS
        saved = dict(TS.VOLUMETRIC_HEAT_CAPACITY_J_M3K)
        try:
            TS.VOLUMETRIC_HEAT_CAPACITY_J_M3K.pop("Hybrid_Bond")
            with self.assertRaises(KeyError):
                TS.TransientThermalSolver(GOLDEN)
        finally:
            TS.VOLUMETRIC_HEAT_CAPACITY_J_M3K.clear()
            TS.VOLUMETRIC_HEAT_CAPACITY_J_M3K.update(saved)

    def test_heat_capacity_can_be_overridden_without_editing_the_table(self):
        doubled = TransientThermalSolver(
            GOLDEN, rho_cp_map={m: 2.0 * v for m, v in
                                zip(self.solver.layer_materials,
                                    self.solver.rho_cp.tolist())})
        # Twice the thermal mass, same conductances -> twice the time constant.
        self.assertAlmostEqual(doubled.time_constant_s(),
                               2.0 * self.solver.time_constant_s(), places=9)

    def test_stability_limit_is_computed_from_the_discretisation(self):
        """dt_max = min_i C_i / sum_j g_ij -- the quantity `diffusivity = 0.01`
        was standing in for."""
        expected = float((self.solver.capacitance
                          / self.solver.face_conductance_sum()).min())
        self.assertAlmostEqual(self.solver.stability_limit_s(), expected, places=15)
        self.assertGreater(self.solver.stability_limit_s(), 0.0)

    def test_matches_the_exact_matrix_exponential(self):
        """With a laterally uniform field the stack reduces exactly to N
        coupled nodes, whose solution scipy computes independently."""
        r = self.solver.verify_against_matrix_exponential()
        self.assertLess(r["max_abs_error_c"], 1e-2,
                        f"transient vs expm: {r['max_abs_error_c']:.3e} C")

    def test_the_stack_has_more_than_one_time_constant(self):
        """Why a single lumped exponential is the wrong reference: the 5um
        hybrid bond and the 775um package are four orders of magnitude apart."""
        taus = self.solver.mode_time_constants_s()
        self.assertEqual(self.solver.layers, len(taus))
        self.assertGreater(taus[0] / taus[-1], 1e3)

    def test_shares_the_steady_state_solvers_fixed_point(self):
        """The check the old implementation could not have passed: its fixed
        point was not solver.py's fixed point, so the two solvers described
        different stacks. Checked as a residual rather than by integrating
        there, which would take ~2e6 explicit steps."""
        r = self.solver.verify_fixed_point(self._hotspot())
        self.assertLess(r["relative_to_load"], 1e-5,
                        f"{r['power_imbalance_w']:.3e} W unbalanced at the "
                        f"steady-state field")

    def test_closes_the_energy_budget(self):
        """integral(P dt) = dU + integral(Q_out dt)."""
        self.solver.solve_transient(self._hotspot(),
                                    duration_s=0.02, dt_s=0.002)
        self.assertLess(self.solver.energy_closure(), 1e-4)

    def test_starts_from_ambient_not_a_hardcoded_50c(self):
        p = self._hotspot(0.0)
        _, history = self.solver.solve_transient(p, duration_s=1e-4, dt_s=1e-4)
        self.assertAlmostEqual(history[0]["peak_c"], self.solver.t_ambient, places=6)

    def test_more_power_heats_faster(self):
        _, low = self.solver.solve_transient(self._hotspot(5.0), 0.005, dt_s=0.005)
        _, high = self.solver.solve_transient(self._hotspot(20.0), 0.005, dt_s=0.005)
        self.assertGreater(high[-1]["peak_c"], low[-1]["peak_c"])

    def test_transient_peak_never_exceeds_the_steady_state_peak(self):
        """Heating from ambient under constant power is monotone toward the
        steady state; overshoot would mean the integration is unstable."""
        r = self.solver.verify_relaxes_toward_steady_state(self._hotspot())
        self.assertTrue(r["monotone"], r["peaks_c"])
        self.assertLessEqual(r["overshoot_c"], 1e-6)
        self.assertGreater(r["fraction_of_steady_rise"], 0.1)


class TestHeatResidual(unittest.TestCase):
    """The residual must vanish exactly on a solution and not otherwise."""

    @classmethod
    def setUpClass(cls):
        cls.solver = ThermalSolver(GOLDEN)
        cls.res = HeatEquationResidual.from_solver(cls.solver)
        cls.G = cls.solver.grid_size
        cls.power = torch.zeros((1, cls.solver.layers, cls.G, cls.G))
        c = cls.G // 2
        cls.power[0, 0, c - 1:c + 1, c - 1:c + 1] = 10.0 / 4.0

    def test_vanishes_on_a_converged_field(self):
        t = self.solver.solve_steady_state(self.power, iterations=60000, tol=1e-7)
        self.assertLess(self.res.rms_k(t, self.power), 1e-4)

    def test_large_on_an_unconverged_field(self):
        """This is the check that would have caught labels generated with a
        fixed 200-iteration cap."""
        t_short = self.solver.solve_steady_state(self.power, iterations=200,
                                                 tol=1e-12)
        t_long = self.solver.solve_steady_state(self.power, iterations=60000,
                                                tol=1e-7)
        self.assertGreater(self.res.rms_k(t_short, self.power),
                           self.res.rms_k(t_long, self.power) * 10)

    def test_large_on_a_perturbed_field(self):
        t = self.solver.solve_steady_state(self.power, iterations=60000, tol=1e-7)
        perturbed = t + torch.randn_like(t) * 2.0
        self.assertGreater(self.res.rms_k(perturbed, self.power), 0.1)

    def test_is_differentiable(self):
        t = self.solver.solve_steady_state(self.power, iterations=500).clone()
        t.requires_grad_(True)
        (self.res(t, self.power) ** 2).mean().backward()
        self.assertIsNotNone(t.grad)
        self.assertGreater(float(t.grad.abs().sum()), 0.0)

    def test_matches_the_solver_discretisation(self):
        """Residual and solver must share geometry, materials and BCs."""
        self.assertEqual(self.res.layers, self.solver.layers)
        torch.testing.assert_close(self.res.gx.flatten(), self.solver.gx)


class TestNsga2(unittest.TestCase):
    def test_dominance(self):
        self.assertTrue(P.dominates(np.array([1., 1.]), np.array([2., 2.])))
        self.assertTrue(P.dominates(np.array([1., 2.]), np.array([1., 3.])))
        self.assertFalse(P.dominates(np.array([1., 2.]), np.array([2., 1.])))
        self.assertFalse(P.dominates(np.array([1., 1.]), np.array([1., 1.])))

    def test_front_partition(self):
        f = np.array([[1., 4.], [2., 2.], [3., 1.], [4., 4.], [2.5, 3.]])
        fronts = P.fast_non_dominated_sort(f)
        self.assertEqual(sorted(fronts[0].tolist()), [0, 1, 2])
        self.assertEqual(fronts[1].tolist(), [4])
        self.assertEqual(fronts[2].tolist(), [3])

    def test_front_members_are_mutually_nondominating(self):
        rng = np.random.default_rng(3)
        f = rng.random((60, 3))
        front = f[P.pareto_front(f)]
        for i in range(len(front)):
            for j in range(len(front)):
                if i != j:
                    self.assertFalse(P.dominates(front[i], front[j]))

    def test_crowding_endpoints_are_infinite(self):
        f = np.array([[0., 3.], [1., 2.], [2., 1.], [3., 0.]])
        d = P.crowding_distance(f)
        self.assertTrue(np.isinf(d[0]) and np.isinf(d[-1]))
        self.assertTrue(np.all(np.isfinite(d[1:-1])))

    def test_hypervolume_exact_in_2d(self):
        """A single point at the box centre dominates exactly one quarter."""
        f = np.array([[0.5, 0.5]])
        hv = P.hypervolume(f, reference=np.array([1., 1.]),
                           ideal=np.array([0., 0.]))
        self.assertAlmostEqual(hv, 0.25, places=9)

    def test_hypervolume_box_is_fixed_not_derived_from_the_front(self):
        """Regression guard: deriving the box from the front made an improving
        search score lower, so NSGA-II appeared to regress."""
        ref, ideal = np.array([1., 1.]), np.array([0., 0.])
        worse = np.array([[0.8, 0.8]])
        better = np.array([[0.2, 0.2]])
        self.assertGreater(P.hypervolume(better, ref, ideal),
                           P.hypervolume(worse, ref, ideal))

    def test_hypervolume_monotone_under_adding_a_dominating_point(self):
        ref, ideal = np.array([1., 1.]), np.array([0., 0.])
        base = np.array([[0.6, 0.6]])
        grown = np.vstack([base, [[0.3, 0.3]]])
        self.assertGreaterEqual(P.hypervolume(grown, ref, ideal),
                                P.hypervolume(base, ref, ideal))

    def test_converges_to_the_zdt1_analytic_front(self):
        def zdt1(x):
            f1 = x[:, 0]
            g = 1 + 9 * x[:, 1:].mean(axis=1)
            return np.stack([f1, g * (1 - np.sqrt(f1 / g))], axis=1)

        lo, hi = np.zeros(6), np.ones(6)
        r = P.nsga2(zdt1, lo, hi, pop_size=40, generations=150, seed=1)
        front = r.front
        err = np.abs(front[:, 1] - (1 - np.sqrt(np.clip(front[:, 0], 0, None))))
        self.assertLess(err.mean(), 0.05, "front is far from the analytic solution")
        self.assertGreater(len(front), 10)

    def test_beats_random_search_at_equal_budget(self):
        def zdt1(x):
            f1 = x[:, 0]
            g = 1 + 9 * x[:, 1:].mean(axis=1)
            return np.stack([f1, g * (1 - np.sqrt(f1 / g))], axis=1)

        lo, hi = np.zeros(6), np.ones(6)
        ref, ideal = np.array([1.1, 1.1]), np.array([0.0, 0.0])
        n = P.nsga2(zdt1, lo, hi, pop_size=40, generations=100, seed=2)
        rnd = P.random_search(zdt1, lo, hi, evaluations=n.evaluations, seed=2)
        self.assertGreater(P.hypervolume(n.objectives, ref, ideal),
                           P.hypervolume(rnd.objectives, ref, ideal),
                           "if random matches NSGA-II, no search is happening")

    def test_search_improves_hypervolume_over_generations(self):
        def zdt1(x):
            f1 = x[:, 0]
            g = 1 + 9 * x[:, 1:].mean(axis=1)
            return np.stack([f1, g * (1 - np.sqrt(f1 / g))], axis=1)

        ref, ideal = np.array([1.1, 1.1]), np.array([0.0, 0.0])
        r = P.nsga2(zdt1, np.zeros(6), np.ones(6), pop_size=40, generations=60,
                    seed=4, reference=ref, ideal=ideal)
        self.assertGreater(r.history[-1], r.history[0])


if __name__ == "__main__":
    unittest.main()
