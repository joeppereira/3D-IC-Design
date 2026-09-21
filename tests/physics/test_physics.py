"""Verification tests for the thermal reference, the FDM solver, the physics
residual, and NSGA-II.

The ordering is deliberate: each layer is checked against something more
trustworthy than itself.

    reference solver  <- analytic 1D slab conduction, global energy balance
    FDM solver        <- the reference solver (different method, same equations)
    heat residual     <- a converged field (residual must vanish)
    NSGA-II           <- ZDT1, whose Pareto front is known analytically
    trust guard       <- an independent solve of the design it re-solved, and
                         its own training set, which it must not flag
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
import thermal_rom as rom_mod                                           # noqa: E402
import trust_guard as tg                                                # noqa: E402
from pareto_search import build_power_maps, GRID, SUB, N_SUB      # noqa: E402

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


class TestThermalROM(unittest.TestCase):
    """The POD-Galerkin ROM -- the last unimplemented item from the original
    claims, which used to be described with a 1.9M x speedup against a tool
    nobody had run."""

    @classmethod
    def setUpClass(cls):
        cls.ref = rom_mod.build_reference()
        cls.rom = rom_mod.ThermalROM(cls.ref, nx=16, ny=16, refine_z=1)
        cls.train = rom_mod.sample_params(48, seed=1)
        cls.test = rom_mod.sample_params(8, seed=2)
        cls.basis = cls.rom.fit(cls.train, rank=48)

    def _rel(self, p, rank=None):
        if rank is not None:
            self.rom.set_rank(rank)
        t_full = self.rom.solve_full(p)
        t_rom = self.rom.solve_reduced(p)
        return (float(np.linalg.norm(t_rom - t_full) / np.linalg.norm(t_full)),
                float(abs(t_rom.max() - t_full.max())))

    def test_assemble_and_solve_agree(self):
        """The ROM projects the operator solve() uses, so the split-out
        assembly must reproduce solve() exactly."""
        import scipy.sparse.linalg as spla
        a, b, mesh = self.ref.assemble(nx=12, ny=12, refine_z=1)
        field = spla.spsolve(a, b).reshape(mesh["nz"], mesh["ny"], mesh["nx"])
        direct = self.ref.solve(nx=12, ny=12, refine_z=1)
        np.testing.assert_allclose(field, direct.t_field_c, rtol=0, atol=1e-9)

    def test_basis_is_orthonormal(self):
        m = self.basis.modes
        np.testing.assert_allclose(m.T @ m, np.eye(m.shape[1]), atol=1e-10)

    def test_full_rank_basis_spans_the_training_snapshots(self):
        """The defining property of POD: at rank M the span contains every
        snapshot, so the projection error on training data is round-off."""
        self.rom.set_rank(self.basis.max_rank)
        for p in self.train[:4]:
            t_full = self.rom.solve_full(p)
            err = np.linalg.norm(self.rom.project(t_full) - t_full) \
                / np.linalg.norm(t_full)
            self.assertLess(err, 1e-10)

    def test_reduced_operator_is_a_galerkin_projection(self):
        """U^T A U, not a regression fitted to the outputs."""
        self.rom.set_rank(12)
        m = self.rom.basis.modes
        np.testing.assert_allclose(self.rom._a_reduced,
                                   m.T @ (self.rom.a @ m), atol=1e-12)
        # A is symmetric, so its projection must be too.
        np.testing.assert_allclose(self.rom._a_reduced, self.rom._a_reduced.T,
                                   rtol=1e-9, atol=1e-12)

    def test_error_falls_as_modes_are_retained(self):
        errs = [max(self._rel(p, rank=r)[0] for p in self.test)
                for r in (4, 12, 24, 48)]
        self.assertEqual(errs, sorted(errs, reverse=True), errs)

    def test_set_rank_can_grow_as_well_as_shrink(self):
        """Regression guard: set_rank used to discard the tail of the basis, so
        every rank after the first was capped at the smallest one requested and
        the rank sweep reported a flat line."""
        self.rom.set_rank(4)
        self.assertEqual(4, self.rom.basis.rank)
        self.rom.set_rank(40)
        self.assertEqual(40, self.rom.basis.rank)
        self.assertEqual(40, self.rom.basis.modes.shape[1])

    def test_retained_energy_overstates_accuracy(self):
        """The finding worth carrying forward: 99.98% 'retained energy' is not
        99.98% accuracy. Quoting the energy fraction is how a ROM gets
        advertised at an accuracy it does not have."""
        self.rom.set_rank(24)
        self.assertGreater(self.rom.basis.retained_energy, 0.999)
        worst_l2, worst_peak = max((self._rel(p) for p in self.test),
                                   key=lambda e: e[0])
        self.assertGreater(worst_l2, 1e-2)
        self.assertGreater(worst_peak, 1.0)

    def test_reduced_solve_beats_the_neural_surrogate_on_peak_error(self):
        """Context for the number: the FNO surrogate is +8 to +40 K at
        optimiser-selected designs (reports/thermal_validation.json)."""
        self.rom.set_rank(self.basis.max_rank)
        worst = max(self._rel(p)[1] for p in self.test)
        self.assertLess(worst, 8.0)

    def test_held_out_parameters_are_not_training_parameters(self):
        self.assertEqual(set(), set(self.train) & set(self.test))


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


class TestTrustGuard(unittest.TestCase):
    """The guard exists so no surrogate prediction reaches a report unchecked.
    These tests check the two things it asserts: that what it publishes is a
    reference solve, and that its out-of-distribution flag means something."""

    @classmethod
    def setUpClass(cls):
        solver = ThermalSolver(GOLDEN)
        cls.solver = solver
        cls.ref = tg.reference_from_solver(solver)
        cls.cascade = tg.ReferenceCascade(cls.ref)
        cls.layers = solver.layers
        cls.logic_w, cls.mem_w = 45.0, 15.0
        cls.maps = build_power_maps(
            np.random.default_rng(7).uniform(0, GRID - SUB, (6, 2 * N_SUB + 2)),
            cls.logic_w, cls.mem_w, cls.layers).numpy()
        cls.train_maps = tg.load_training_maps()
        cls.guard = tg.DistributionGuard.fit(cls.train_maps)

    # -- the cascade publishes solver output, not an approximation of it ----
    def test_expansion_conserves_power(self):
        lv = self.cascade.level(2)
        q = tg.expand_power_map(self.maps[0], 2, lv.mesh["layer_of"])
        self.assertAlmostEqual(q.sum(), float(self.maps[0].sum()), places=9)
        self.assertEqual(q.shape, (lv.mesh["nz"], lv.mesh["ny"], lv.mesh["nx"]))

    def test_rhs_shortcut_matches_a_fresh_assembly(self):
        """The cascade subtracts the assembly's own load once and adds each
        design's instead. If that shortcut were wrong, every temperature it
        reports would be wrong by a constant nobody would notice."""
        lv = self.cascade.level(1)
        q = tg.expand_power_map(self.maps[0], 1, lv.mesh["layer_of"])
        _, b_fresh, _ = self.ref.assemble(GRID, GRID, 1, power_map=q)
        np.testing.assert_allclose(self.cascade.rhs(self.maps[0], 1), b_fresh,
                                   rtol=0, atol=1e-12)

    def test_peak_matches_an_independent_solve(self):
        lv = self.cascade.level(2)
        q = tg.expand_power_map(self.maps[1], 2, lv.mesh["layer_of"])
        direct = self.ref.solve(nx=GRID * 2, ny=GRID * 2, refine_z=2, power_map=q)
        self.assertAlmostEqual(self.cascade.peak(self.maps[1], 2),
                               float(direct.t_field_c[0].max()), places=9)

    def test_finer_mesh_is_a_smaller_correction_than_the_error_it_checks(self):
        """refine=2 is the working mesh because refine=4 barely moves it."""
        m = self.maps[0]
        self.assertLess(abs(self.cascade.peak(m, 2) - self.cascade.peak(m, 4)),
                        abs(self.cascade.peak(m, 1) - self.cascade.peak(m, 2)))

    # -- the distribution flag ----------------------------------------------
    def test_does_not_flag_its_own_training_set(self):
        d = self.guard.distance(self.train_maps)
        flagged = float((d > self.guard.threshold).mean())
        self.assertLessEqual(flagged, 0.02,
                             "a detector that flags the training data flags "
                             "everything and means nothing")

    def test_flags_every_design_the_optimiser_can_express(self):
        """The search places 2x2 blocks and a solid 4x4 memory macro;
        data_gen.py trained on r=3 discs and single hot cells. This is the
        measured reason the surrogate is tens of kelvin out at the optimum."""
        d = self.guard.distance(self.maps)
        self.assertTrue((d > self.guard.threshold).all())
        self.assertGreater(d.min(), 4 * self.guard.threshold)

    def test_names_the_feature_responsible(self):
        name, z = self.guard.dominant_feature(self.maps[0])
        self.assertIn(name, tg.FEATURE_NAMES)
        self.assertGreater(abs(z), 3.0)

    def test_features_separate_a_block_from_a_spread_source(self):
        block = np.zeros((self.layers, GRID, GRID))
        block[0, 4:8, 4:8] = 1.0
        block[1, 6:10, 6:10] = 1.0
        spread = np.zeros((self.layers, GRID, GRID))
        spread[0] = 1.0
        spread[1] = 1.0
        f_block = tg.power_map_features(block)
        f_spread = tg.power_map_features(spread)
        i_active = tg.FEATURE_NAMES.index("logic_active_fraction")
        i_ptm = tg.FEATURE_NAMES.index("logic_peak_to_mean")
        self.assertLess(f_block[i_active], f_spread[i_active])
        self.assertGreater(f_block[i_ptm], f_spread[i_ptm])

    def test_refuses_a_power_map_with_no_power(self):
        with self.assertRaises(ValueError):
            tg.power_map_features(np.zeros((self.layers, GRID, GRID)))

    # -- the audit -----------------------------------------------------------
    def _audit(self, surrogate_peaks, **kw):
        g = tg.SurrogateTrustGuard(self.cascade, self.guard)
        return g.audit(self.maps, surrogate_peaks, **kw)

    def test_reports_the_reference_not_the_prediction(self):
        truth = self.cascade.peaks(self.maps, 2)
        r = self._audit(truth + 20.0)
        for d in r["designs"]:
            self.assertAlmostEqual(d["reference_peak_c"],
                                   float(truth[d["index"]]), places=9)
            self.assertAlmostEqual(d["surrogate_error_k"], 20.0, places=6)

    def test_error_budget_closes_on_the_total(self):
        maps_t = torch.from_numpy(self.maps).float()
        fdm = self.solver.solve_steady_state(maps_t)[:, 0].amax(dim=(1, 2)).numpy()
        surro = fdm + 5.0
        r = self._audit(surro, fdm_peaks=fdm)
        self.assertLess(r["error_budget_k"]["closes_to_k"], 1e-9)
        self.assertLess(
            r["error_budget_k"]["solver_agreement_same_mesh"]["max_abs_k"], 1e-3,
            "the split assumes the FDM solver and the reference agree on the "
            "training mesh; if they do not, the attribution is meaningless")

    def test_regret_and_tau_catch_a_misranking_surrogate(self):
        truth = self.cascade.peaks(self.maps, 2)
        good = self._audit(truth)
        bad = self._audit(-truth)            # perfectly reversed ordering
        self.assertAlmostEqual(good["ranking"]["kendall_tau"], 1.0, places=9)
        self.assertAlmostEqual(good["ranking"]["selection_regret_c"], 0.0, places=9)
        self.assertAlmostEqual(bad["ranking"]["kendall_tau"], -1.0, places=9)
        self.assertGreater(bad["ranking"]["selection_regret_c"], 0.0)

    def test_top_k_resolves_the_coolest_designs_only(self):
        truth = self.cascade.peaks(self.maps, 2)
        r = self._audit(truth, top_k=2)
        self.assertEqual(r["n_resolved"], 2)
        self.assertEqual([d["index"] for d in r["designs"]],
                         list(np.argsort(truth)[:2]))

    def test_refuses_a_prediction_per_design_mismatch(self):
        with self.assertRaises(ValueError):
            self._audit(np.zeros(len(self.maps) - 1))

    # -- the published artifact ---------------------------------------------
    def test_published_front_temperatures_are_reference_solves(self):
        """Re-derive one published number from its own genome. This is what
        stops the front from drifting back to surrogate predictions."""
        path = os.path.join(ROOT, "reports", "pareto_front_nsga2.json")
        if not os.path.exists(path):
            self.skipTest("front not generated")
        import json
        with open(path) as fh:
            doc = json.load(fh)
        keys = doc["genome_keys"]
        entry, genome = doc["front"][0], doc["front_genomes"][0]
        self.assertIn("reference_peak_tj_c", entry,
                      "the published front must carry a solved temperature")
        pmap = build_power_maps(np.array([[genome[k] for k in keys]]),
                                self.logic_w, self.mem_w, self.layers).numpy()
        self.assertAlmostEqual(self.cascade.peak(pmap[0], 2),
                               entry["reference_peak_tj_c"], places=6)
        self.assertGreater(entry["logic_peak_tj_c"], entry["reference_peak_tj_c"],
                           "the surrogate over-predicts at these designs")


class TestRomAcceptsArbitraryLoads(unittest.TestCase):
    """fit_rhs/from_operator exist so the trust guard can build a POD basis
    over the layouts the optimiser searches, using the operator it already
    factorised, without a second copy of the POD code."""

    def test_fit_rhs_matches_fit_on_the_same_snapshots(self):
        ref = rom_mod.build_reference()
        a = rom_mod.ThermalROM(ref, nx=12, ny=12, refine_z=1)
        b = rom_mod.ThermalROM(ref, nx=12, ny=12, refine_z=1)
        params = rom_mod.sample_params(8, seed=3)
        a.fit(params, rank=8)
        b.fit_rhs([b.rhs(p) for p in params], rank=8)
        test = rom_mod.sample_params(1, seed=9)[0]
        np.testing.assert_allclose(a.solve_reduced(test), b.solve_reduced(test),
                                   rtol=1e-10, atol=1e-8)

    def test_from_operator_reuses_the_factorisation(self):
        ref = rom_mod.build_reference()
        cascade = tg.ReferenceCascade(ref, grid=GRID)
        lv = cascade.level(1)
        rom = rom_mod.ThermalROM.from_operator(ref, lv.a, lv.mesh, lv.lu, 1)
        self.assertIs(rom.a, lv.a)
        self.assertEqual(rom.n, lv.n)
        loads = [cascade.rhs(m, 1) for m in
                 build_power_maps(np.random.default_rng(2)
                                  .uniform(0, GRID - SUB, (6, 2 * N_SUB + 2)),
                                  45.0, 15.0, len(ref.layers)).numpy()]
        rom.fit_rhs(loads[:4], rank=4)
        approx = rom.solve_reduced_rhs(loads[0])
        np.testing.assert_allclose(approx, lv.lu.solve(loads[0]),
                                   rtol=0, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
