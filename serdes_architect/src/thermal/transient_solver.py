"""Transient conduction on the voxel stack, in SI units.

Rewritten 2026-09-20, for the same reason solver.py was. The previous version
carried three constants that were not physics:

    PHYSICAL_SCALE = 500.0   # "Match steady state calibration" -- it did not
                             #  match the steady-state solver, and was unused
    power_map * 2000.0       # an unexplained source multiplier
    self.diffusivity = 0.01  # named a diffusivity (m^2/s); used as a
                             #  relaxation factor, and dimensionally it could
                             #  not have been one

and two boundary conditions written as exponential blends
(`T = T*0.99 + 25*0.01`) whose implied film coefficient depended on the time
step. Nothing in it was falsifiable.

This version integrates the same finite-volume energy equation the steady-state
solver discretises:

    C_i dT_i/dt = sum_j g_ij (T_j - T_i) + g_conv (T_inf - T_i) + P_i

with C_i = rho*c_p*V_i in J/K, the g's in W/K from ThermalSolver, and P_i in
watts. It therefore inherits the conductances that were verified against
analytic 1D conduction and a mesh-convergence study, and adds exactly one new
physical quantity: volumetric heat capacity.

Time integration is explicit Euler, automatically sub-stepped to stay inside
the stability limit dt <= min_i C_i / sum_j g_ij. The limit is computed, not
guessed, and `solve_transient` reports how many sub-steps it took.

Verified three ways (`--verify`):
  * against the exact solution of the system it integrates: with a laterally
    uniform field the stack reduces exactly to `layers` coupled nodes, whose
    answer is expm(A t) -- computed by scipy, which knows nothing about this
    discretisation;
  * against solver.py, by requiring its converged field to be a fixed point
    of the transient right-hand side (and relaxing monotonically toward it);
  * by closing the energy budget: integral(P dt) = dU + integral(Q_out dt).
"""
import argparse
import json
import math
import os
import sys

import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solver import ThermalSolver  # noqa: E402

# Volumetric heat capacity rho*c_p [J/(m^3 K)] near 350 K.
#
# Handbook values for the dominant constituent of each layer, not measured
# composites -- the same standing as the k_map they sit beside. A layer that is
# a mixture (C4/underfill, laminate package) is an effective-medium choice, and
# is marked as such. Anything not listed raises rather than defaulting, because
# a silently defaulted property is what modelled the Cu-Cu hybrid bond as an
# insulator in the k_map.
VOLUMETRIC_HEAT_CAPACITY_J_M3K = {
    "Die":         1.66e6,   # Si: 2330 kg/m3 * 712 J/kgK
    "Metal_Stack": 3.45e6,   # Cu-dominated BEOL: 8960 * 385
    "Hybrid_Bond": 3.45e6,   # Cu-Cu bond, treated as Cu
    "TSV_Array":   3.45e6,   # Cu-filled vias, treated as Cu
    "C4_BGA":      1.67e6,   # effective medium: SnAg solder 7310 * 228
    "Package":     2.28e6,   # effective medium: organic laminate 1900 * 1200
    "Interposer":  1.66e6,   # Si
    "TIM":         2.00e6,   # effective medium: filled grease 2500 * 800
    "Underfill":   1.62e6,   # effective medium: filled epoxy 1800 * 900
}

# Fraction of the explicit stability limit to actually use. Sitting exactly on
# the limit is neutrally stable; 0.9 leaves margin without costing much.
CFL_SAFETY = 0.9


class TransientThermalSolver(ThermalSolver):
    """Time-dependent conduction. Shares ThermalSolver's discretisation."""

    def __init__(self, config_path, rho_cp_map=None):
        super().__init__(config_path)
        self._build_capacitance(rho_cp_map)

    def _build_capacitance(self, rho_cp_map=None):
        table = dict(VOLUMETRIC_HEAT_CAPACITY_J_M3K)
        table.update(self.config.get('voxel_stack_params', {}).get('rho_cp_map', {}))
        if rho_cp_map:
            table.update(rho_cp_map)

        missing = sorted({m for m in self.layer_materials if m not in table})
        if missing:
            raise KeyError(
                f"no volumetric heat capacity for {missing} (known: "
                f"{sorted(table)}). Add them to voxel_stack_params.rho_cp_map "
                f"rather than letting them default -- an unstated thermal mass "
                f"silently changes every time constant in the result.")

        self.rho_cp = torch.tensor([table[m] for m in self.layer_materials],
                                   dtype=torch.float64)
        cell_volume = self.dx * self.dy * self.dz.to(torch.float64)
        self.capacitance = self.rho_cp * cell_volume          # [layers], J/K

    # --- the numbers that used to be magic constants ----------------------

    def stability_limit_s(self):
        """Largest explicit-Euler step that stays stable, in seconds.

        dt <= min_i C_i / (sum of conductances touching cell i). This is the
        quantity the old `diffusivity = 0.01` was standing in for.
        """
        return float((self.capacitance / self.face_conductance_sum()).min())

    def time_constant_s(self):
        """Lumped estimate of the slowest time constant, C_total / g_conv [s].

        An estimate, not the answer: the stack has one time constant per layer
        (see mode_time_constants_s). It happens to land within ~3% of the true
        slowest mode here, which is why it is a serviceable default for
        choosing how long to integrate.
        """
        cells = self.grid_size * self.grid_size
        c_total = float(self.capacitance.sum()) * cells
        g_total = float(self.g_top + self.g_bot) * cells
        return c_total / g_total

    # --- integration ------------------------------------------------------

    def _rate(self, t, power_map):
        """dT/dt [K/s] for the finite-volume energy equation."""
        pad = F.pad(t, (1, 1, 1, 1), mode='replicate')
        gx = self.gx.view(1, -1, 1, 1).to(t.dtype)
        gy = self.gy.view(1, -1, 1, 1).to(t.dtype)
        flux = gx * (pad[:, :, 1:-1, 2:] + pad[:, :, 1:-1, :-2] - 2.0 * t) \
            + gy * (pad[:, :, 2:, 1:-1] + pad[:, :, :-2, 1:-1] - 2.0 * t)

        for i in range(self.layers):
            if i > 0:
                flux[:, i] += self.gz[i - 1] * (t[:, i - 1] - t[:, i])
            if i < self.layers - 1:
                flux[:, i] += self.gz[i] * (t[:, i + 1] - t[:, i])

        flux[:, 0] += self.g_top * (self.t_ambient - t[:, 0])
        flux[:, -1] += self.g_bot * (self.t_ambient - t[:, -1])

        return (flux + power_map) / self.capacitance.view(1, -1, 1, 1)

    def heat_out_w(self, t):
        """Instantaneous heat leaving the two convective faces [W]."""
        return float((self.g_top * (t[:, 0] - self.t_ambient)).sum()
                     + (self.g_bot * (t[:, -1] - self.t_ambient)).sum())

    def stored_energy_j(self, t):
        """Internal energy relative to ambient [J]."""
        c = self.capacitance.view(1, -1, 1, 1)
        return float((c * (t.to(torch.float64) - self.t_ambient)).sum())

    def solve_transient(self, power_map, duration_s, dt_s=None,
                        t_initial=None, verbose=False):
        """Integrate for `duration_s` seconds.

        power_map : [B, layers, H, W] in watts per cell (constant over the run)
        dt_s      : sampling interval for the history. The integrator
                    sub-steps below this as the stability limit requires; it
                    is an output cadence, not the numerical time step.
        t_initial : [B, layers, H, W] in degrees C, or a scalar. Defaults to
                    ambient rather than the old hard-coded 50 C.

        Returns (T_final [B,layers,H,W] degrees C, history), where history is a
        list of samples carrying time, peak temperature, stored energy and the
        running energy-balance residual.
        """
        power_map = power_map.to(torch.float64)
        b = power_map.shape[0]

        if t_initial is None:
            t = torch.full((b, self.layers, self.grid_size, self.grid_size),
                           float(self.t_ambient), dtype=torch.float64)
        elif torch.is_tensor(t_initial):
            t = t_initial.to(torch.float64).expand_as(power_map).clone()
        else:
            t = torch.full_like(power_map, float(t_initial))

        dt_limit = self.stability_limit_s()
        dt_sample = float(dt_s) if dt_s else duration_s / 20.0
        dt_sample = min(dt_sample, duration_s)
        substeps = max(1, math.ceil(dt_sample / (CFL_SAFETY * dt_limit)))
        dt = dt_sample / substeps
        samples = max(1, int(round(duration_s / dt_sample)))

        self.dt_used_s = dt
        self.substeps_per_sample = substeps
        self.stability_limit_used_s = dt_limit

        if verbose:
            print(f"  [Transient] tau={self.time_constant_s()*1e3:.2f} ms, "
                  f"stability limit {dt_limit*1e6:.2f} us, "
                  f"dt={dt*1e6:.2f} us ({substeps} sub-steps per "
                  f"{dt_sample*1e3:.3f} ms sample)")

        p_in = float(power_map.sum()) / b
        energy_in = 0.0
        energy_out = 0.0
        u0 = self.stored_energy_j(t) / b
        history = [{"time_s": 0.0, "peak_c": float(t.max()),
                    "mean_c": float(t.mean()), "heat_out_w": self.heat_out_w(t) / b,
                    "stored_j": 0.0, "energy_residual": 0.0}]

        for s in range(samples):
            for _ in range(substeps):
                # Trapezoid on the outflow: the flux changes across the step,
                # and a left-rectangle rule leaves an O(dt) bias in the budget
                # that looks exactly like an energy-conservation bug.
                q0 = self.heat_out_w(t) / b
                t = t + dt * self._rate(t, power_map)
                q1 = self.heat_out_w(t) / b
                energy_out += 0.5 * (q0 + q1) * dt
                energy_in += p_in * dt
            stored = self.stored_energy_j(t) / b - u0
            history.append({
                "time_s": (s + 1) * dt * substeps,
                "peak_c": float(t.max()),
                "mean_c": float(t.mean()),
                "heat_out_w": self.heat_out_w(t) / b,
                "stored_j": stored,
                "energy_residual": energy_in - energy_out - stored,
            })

        self.energy_in_j = energy_in
        self.energy_out_j = energy_out
        self.energy_stored_j = history[-1]["stored_j"]
        return t.to(torch.float32), history

    def energy_closure(self):
        """Relative energy-budget error of the last run: (in - out - dU)/in."""
        residual = self.energy_in_j - self.energy_out_j - self.energy_stored_j
        return abs(residual) / max(abs(self.energy_in_j), 1e-12)

    # --- verification -----------------------------------------------------

    def vertical_system(self):
        """The stack as a linear ODE system dT/dt = A(T - T_inf), A in 1/s.

        With a laterally uniform field the in-plane fluxes cancel exactly
        (replicate padding at the walls, equal neighbours in the interior), so
        the layers reduce to `self.layers` nodes coupled by gz with convection
        at the two ends. That reduction is exact, not an approximation, which
        is what makes the next check a real analytic benchmark.
        """
        import numpy as np
        n = self.layers
        a = np.zeros((n, n))
        gz = self.gz.to(torch.float64).numpy()
        for i in range(n):
            if i > 0:
                a[i, i - 1] += gz[i - 1]
                a[i, i] -= gz[i - 1]
            if i < n - 1:
                a[i, i + 1] += gz[i]
                a[i, i] -= gz[i]
        a[0, 0] -= float(self.g_top)
        a[-1, -1] -= float(self.g_bot)
        return a / self.capacitance.numpy()[:, None]

    def mode_time_constants_s(self):
        """Time constants of the stack's eigenmodes, slowest first."""
        import numpy as np
        ev = np.linalg.eigvals(self.vertical_system()).real
        return sorted((-1.0 / ev).tolist(), reverse=True)

    def verify_against_matrix_exponential(self):
        """Against the exact solution of the system being integrated.

        A single lumped exponential is the wrong reference here: this stack has
        eigenmodes from ~1.5 us (the 5 um hybrid bond) to ~250 ms (the 775 um
        package), so T(t) is a sum of five decays, not one. The exact answer
        for a uniform start with no power applied is
        T(t) = T_inf + expm(A t) (T0 - T_inf), and expm is computed by scipy,
        which knows nothing about this discretisation.
        """
        from scipy.linalg import expm
        import numpy as np

        t0 = self.t_ambient + 50.0
        duration = 0.5 * self.time_constant_s()
        power = torch.zeros((1, self.layers, self.grid_size, self.grid_size),
                            dtype=torch.float64)
        t_final, _ = self.solve_transient(power, duration, dt_s=duration / 50.0,
                                          t_initial=t0)

        exact = self.t_ambient + expm(self.vertical_system() * duration) @ \
            np.full(self.layers, t0 - self.t_ambient)
        numeric = t_final.to(torch.float64).mean(dim=(0, 2, 3)).numpy()
        return {"exact_c": exact.tolist(), "numeric_c": numeric.tolist(),
                "max_abs_error_c": float(np.abs(numeric - exact).max()),
                "mode_tau_s": self.mode_time_constants_s()}

    def verify_fixed_point(self, power_map=None):
        """The steady-state field must be a fixed point of the transient.

        This is the check the old implementation could not have passed: with a
        source multiplier of 2000 and a relaxation factor called a diffusivity,
        its fixed point was not solver.py's fixed point, so the two solvers
        described different stacks.

        Checked as a residual rather than by integrating there, which would
        take ~2e6 explicit steps: feed solver.py's converged field to the
        transient right-hand side and require dT/dt to vanish. Reported as a
        power imbalance so it is comparable to the applied load.
        """
        if power_map is None:
            power_map = torch.zeros((1, self.layers, self.grid_size,
                                     self.grid_size), dtype=torch.float64)
            c = self.grid_size // 2
            power_map[0, 0, c - 1:c + 1, c - 1:c + 1] = 10.0 / 4.0

        # float64 out: the default float32 cast costs ~6e-6 K, which shows up
        # here as a ~5e-3 W phantom imbalance -- round-off, not disagreement.
        steady = self.solve_steady_state(power_map.to(torch.float32),
                                         return_dtype=torch.float64)
        rate = self._rate(steady, power_map)                  # K/s
        imbalance_w = (rate * self.capacitance.view(1, -1, 1, 1)).abs().sum()
        p_total = float(power_map.sum())
        return {"max_rate_k_per_s": float(rate.abs().max()),
                "power_imbalance_w": float(imbalance_w),
                "relative_to_load": float(imbalance_w) / max(p_total, 1e-12),
                "steady_peak_c": float(steady.max())}

    def verify_relaxes_toward_steady_state(self, power_map=None, duration_s=0.05):
        """Integrating from ambient must move monotonically toward, and never
        past, the steady-state peak."""
        if power_map is None:
            power_map = torch.zeros((1, self.layers, self.grid_size,
                                     self.grid_size), dtype=torch.float64)
            c = self.grid_size // 2
            power_map[0, 0, c - 1:c + 1, c - 1:c + 1] = 10.0 / 4.0

        steady_peak = float(self.solve_steady_state(power_map.to(torch.float32)).max())
        _, history = self.solve_transient(power_map, duration_s,
                                          dt_s=duration_s / 10.0)
        peaks = [h["peak_c"] for h in history]
        return {"steady_peak_c": steady_peak, "peaks_c": peaks,
                "monotone": peaks == sorted(peaks),
                "overshoot_c": max(peaks) - steady_peak,
                "fraction_of_steady_rise":
                    (peaks[-1] - self.t_ambient) / (steady_peak - self.t_ambient)}

    def verify(self):
        print("Running Transient Verification...")
        print(f"  Topology: {self.topology}")
        print(f"  Heat capacity: {dict(zip(self.layer_materials, [f'{v:.2e}' for v in self.rho_cp.tolist()]))}")
        print(f"  Stack time constant tau = {self.time_constant_s()*1e3:.3f} ms")
        print(f"  Explicit stability limit = {self.stability_limit_s()*1e6:.3f} us")

        ok = True

        mx = self.verify_against_matrix_exponential()
        taus = ", ".join(f"{v*1e3:.4g}" for v in mx["mode_tau_s"])
        print(f"  Mode time constants (ms): {taus}")
        print(f"  [1/3] Matrix exponential: max field error "
              f"{mx['max_abs_error_c']:.2e} C over {self.layers} layers")
        if mx["max_abs_error_c"] > 1e-2:
            print("  ❌ Transient integration disagrees with the exact solution.")
            ok = False
        else:
            print("  ✅ Matches the exact solution of the same ODE system.")

        fp = self.verify_fixed_point()
        print(f"  [2/3] Steady-state fixed point: solver.py's field leaves "
              f"{fp['power_imbalance_w']:.3e} W unbalanced against a 10 W load "
              f"({fp['relative_to_load']:.2e} relative, "
              f"max |dT/dt| {fp['max_rate_k_per_s']:.2e} K/s)")
        rel = self.verify_relaxes_toward_steady_state()
        print(f"        relaxation: {rel['fraction_of_steady_rise']*100:.1f}% of the "
              f"steady rise after 50 ms, monotone={rel['monotone']}, "
              f"overshoot {rel['overshoot_c']:+.2e} C")
        if fp["relative_to_load"] > 1e-5 or not rel["monotone"] or rel["overshoot_c"] > 1e-6:
            print("  ❌ Transient and steady-state solvers do not share a fixed point.")
            ok = False
        else:
            print("  ✅ Shares the verified steady-state solver's fixed point.")

        closure = self.energy_closure()
        print(f"  [3/3] Energy budget: in {self.energy_in_j:.4f} J, "
              f"out {self.energy_out_j:.4f} J, stored {self.energy_stored_j:.4f} J "
              f"(residual {closure:.2e} relative)")
        if closure > 1e-4:
            print(f"  ❌ Energy not conserved over the transient: {closure:.2e}")
            ok = False
        else:
            print("  ✅ Energy Conserved over the transient.")

        return ok


def _burst_report(solver, power_map, duration_s, cap_c):
    t_final, history = solver.solve_transient(power_map, duration_s,
                                              dt_s=duration_s / 20.0, verbose=True)
    peak = float(t_final.max())
    print("📈 Transient Analysis Results:")
    print(f"  - Start temperature : {history[0]['peak_c']:.2f} C (ambient)")
    print(f"  - Applied power     : {float(power_map.sum()) / power_map.shape[0]:.2f} W")
    print(f"  - Stack tau         : {solver.time_constant_s() * 1e3:.2f} ms")
    print(f"  - Peak burst temp   : {peak:.2f} C after {duration_s * 1e3:.1f} ms")
    print(f"  - Thermal headroom  : {cap_c - peak:.2f} C")
    print(f"  - Energy closure    : {solver.energy_closure():.2e} relative")
    return t_final, history, peak


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    parser.add_argument('--verify', action='store_true',
                        help="run the three verification checks and exit")
    parser.add_argument('--burst_ms', type=float, default=10.0)
    parser.add_argument('--burst_scale', type=float, default=1.5,
                        help="multiplier on the baseline power map")
    parser.add_argument('--cap_c', type=float, default=105.0)
    parser.add_argument('--write_config', action='store_true',
                        help="record the result back into the config")
    args = parser.parse_args()

    solver = TransientThermalSolver(args.config)

    if args.verify:
        raise SystemExit(0 if solver.verify() else 1)

    # Resolve against the repo root: run_full_cycle.sh runs this from
    # serdes_architect/, where the old relative path silently missed the file
    # and the script did nothing at all.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
    power_path = os.path.join(repo_root, 'serdes_architect/data/x_physics.pt')
    if not os.path.exists(power_path):
        raise SystemExit(f"no power map at {power_path}; run data_gen.py first")

    power_maps = torch.load(power_path)
    burst = power_maps[:1].to(torch.float64) * args.burst_scale
    duration_s = args.burst_ms * 1e-3

    t_final, history, peak = _burst_report(solver, burst, duration_s, args.cap_c)

    if peak > args.cap_c:
        print(f"  ❌ FAIL: burst exceeds the {args.cap_c:.0f} C cap.")
    else:
        print(f"  ✅ PASS: stack handles the {args.burst_ms:.0f} ms burst.")

    if args.write_config:
        with open(args.config) as f:
            config = json.load(f)
        config['transient_thermal_verification'] = {
            "peak_burst_temp_c": peak,
            "duration_ms": args.burst_ms,
            "applied_power_w": float(burst.sum()),
            "start_temp_c": float(solver.t_ambient),
            "tau_ms": solver.time_constant_s() * 1e3,
            "dt_s": solver.dt_used_s,
            "energy_closure_relative": solver.energy_closure(),
            "cap_c": args.cap_c,
            "status": "PASS" if peak <= args.cap_c else "FAIL",
            "method": "explicit Euler on the finite-volume energy equation, "
                      "sub-stepped to the computed stability limit; "
                      "conductances shared with solver.py",
        }
        with open(args.config, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"  wrote transient_thermal_verification to {args.config}")
