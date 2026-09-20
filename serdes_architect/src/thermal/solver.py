import argparse
import json
import os
import torch
import torch.nn.functional as F

# Default vertical stack thicknesses (um) when the config does not supply them.
DEFAULT_THICKNESS_UM = [50.0, 5.0, 50.0, 40.0, 775.0]


class ThermalSolver:
    """Steady-state conduction on a voxel stack, in SI units.

    Rewritten 2026-09-20. The previous implementation used a normalized grid
    (dx = dy = dz = 1.0) and a hand-tuned PHYSICAL_SCALE = 500.0 documented as
    "Calibrated for 100W on 10mm die -> ~85C", so its output was a relative
    field rather than a temperature -- and the config it was being run on is an
    18 mm die, not the 10 mm the constant was tuned for.

    This version discretises the same finite-volume equations as
    physics_accelerated/src/thermal_reference.py (harmonic-mean face
    conductances, Robin boundaries with h in W/m^2K) but solves them by Jacobi
    relaxation to a residual tolerance instead of a fixed iteration count. The
    reference solver is verified against analytic 1D slab conduction and a mesh
    convergence study; this solver is then measured against the reference.

    Batch support is retained because data_gen.py generates training sets.
    """

    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.layers = self.config['voxel_stack_params']['layers']
        self.grid_size = self.config['voxel_stack_params']['grid_size']
        self.base_k_map = self.config['voxel_stack_params']['k_map']

        self.pkg_config = self.config.get('packaging', {})
        self.topology = self.pkg_config.get('topology', 'Face_to_Face')
        if 'material_properties' in self.pkg_config:
            self.base_k_map.update(self.pkg_config['material_properties'])

        self.layer_materials = self._build_stack_materials()
        print(f"  [Solver] Built {self.topology} Stack: {self.layer_materials}")

        # --- real geometry, in metres -------------------------------------
        die0 = self.config.get('die_hierarchy', {}).get('die_0', {})
        size_mm = die0.get('size_mm', [10.0, 10.0])
        self.width_m = float(size_mm[0]) * 1e-3
        self.depth_m = float(size_mm[1]) * 1e-3
        self.dx = self.width_m / self.grid_size
        self.dy = self.depth_m / self.grid_size

        thickness_um = self.config.get('voxel_stack_params', {}).get(
            'layer_thickness_um', DEFAULT_THICKNESS_UM)
        if len(thickness_um) < self.layers:
            thickness_um = list(thickness_um) + \
                [DEFAULT_THICKNESS_UM[-1]] * (self.layers - len(thickness_um))
        self.dz = torch.tensor([t * 1e-6 for t in thickness_um[:self.layers]],
                               dtype=torch.float32)

        # A missing material used to fall through to k = 1.0 W/mK silently, which
        # modelled the 5 um Cu-Cu hybrid bond as a near-insulator and corrupted
        # the vertical path -- the most important path in a 3D stack.
        self.missing_materials = sorted({m for m in self.layer_materials
                                         if m not in self.base_k_map})
        if self.missing_materials:
            raise KeyError(
                f"no thermal conductivity for {self.missing_materials} in k_map "
                f"(known: {sorted(self.base_k_map)}). Add them to "
                f"voxel_stack_params.k_map rather than letting them default.")
        k_values = [self.base_k_map[mat] for mat in self.layer_materials]
        self.k = torch.tensor(k_values, dtype=torch.float32)
        self.k_tensor = self.k.view(1, self.layers, 1, 1)   # kept for compatibility

        # --- boundary conditions, real units -------------------------------
        cooling = str(self.pkg_config.get('cooling', 'Passive'))
        if 'Liquid' in cooling:
            self.h_top = 8000.0          # cold plate on a liquid loop
        elif 'BSPDN' in cooling:
            self.h_top = 4000.0
        else:
            self.h_top = 1500.0          # air-cooled heatsink
        self.h_bottom = 50.0             # board side, mostly insulating
        self.t_ambient = float(
            self.config.get('thermal_boundary_conditions', {})
            .get('heatsink_case_temp_c', 25.0))

        self._build_conductances()

    def _build_stack_materials(self):
        """Constructs the vertical material stack based on topology."""
        if self.topology == "Face_to_Face" or "3D" in self.topology:
            base = ["Die", "Hybrid_Bond", "Die", "C4_BGA", "Package"]
        else:
            base = ["Die", "Metal_Stack", "C4_BGA", "Package", "Package"]
        if len(base) < self.layers:
            base = base + ["Package"] * (self.layers - len(base))
        return base[:self.layers]

    def _build_conductances(self):
        """Face conductances [W/K] for one cell, per layer."""
        area_z = self.dx * self.dy
        # In-plane: k * (cross-section) / spacing.
        self.gx = self.k * (self.dy * self.dz) / self.dx
        self.gy = self.k * (self.dx * self.dz) / self.dy
        # Vertical interfaces: series resistance of the two half-cells.
        gz = []
        for i in range(self.layers - 1):
            r = (self.dz[i] / 2.0) / self.k[i] + (self.dz[i + 1] / 2.0) / self.k[i + 1]
            gz.append(area_z / r)
        self.gz = torch.tensor(gz, dtype=torch.float32) if gz else torch.zeros(0)
        # Convective faces: half-cell conduction in series with the film.
        self.g_top = area_z / ((self.dz[0] / 2.0) / self.k[0] + 1.0 / self.h_top)
        self.g_bot = area_z / ((self.dz[-1] / 2.0) / self.k[-1] + 1.0 / self.h_bottom)

    def solve_steady_state(self, power_map, iterations=60000, tol=1e-8,
                           verbose=False):
        """Jacobi relaxation on the finite-volume equations.

        power_map: [B, layers, H, W] in watts per cell.
        Returns temperature in degrees C. Iterates until the largest update
        falls below `tol` kelvin rather than stopping at a fixed count.

        The default tol of 1e-8 K yields a global energy imbalance below 1e-5
        relative; 1e-5 K leaves ~1e-3, which is not good enough for the solver
        to be used as a check on anything.
        """
        # Solve in float64. In float32 the Jacobi update stalls at ~eps*T
        # (~3e-6 K at 57 C), which leaves a ~1e-3 relative energy imbalance that
        # looks like a solver bug but is round-off. The grids here are small, so
        # double precision is essentially free.
        b = power_map.shape[0]
        dtype = torch.float64
        power_map = power_map.to(dtype)
        t = torch.full((b, self.layers, self.grid_size, self.grid_size),
                       self.t_ambient, dtype=dtype)

        gx = self.gx.view(1, -1, 1, 1).to(dtype)
        gy = self.gy.view(1, -1, 1, 1).to(dtype)

        # Denominator: all face conductances touching each cell. Adiabatic side
        # walls are handled by replicate padding, which makes the ghost cell
        # equal to the cell, so its flux is zero while the conductance still
        # appears consistently on both sides of the update.
        denom = 2.0 * gx + 2.0 * gy
        vert = torch.zeros(self.layers, dtype=dtype)
        for i in range(self.layers):
            if i > 0:
                vert[i] += self.gz[i - 1]
            if i < self.layers - 1:
                vert[i] += self.gz[i]
        vert[0] += self.g_top
        vert[-1] += self.g_bot
        denom = denom + vert.view(1, -1, 1, 1)

        bc_source = torch.zeros(self.layers, dtype=dtype)
        bc_source[0] += self.g_top * self.t_ambient
        bc_source[-1] += self.g_bot * self.t_ambient
        bc_source = bc_source.view(1, -1, 1, 1)

        last_delta = float('inf')
        for it in range(iterations):
            pad = F.pad(t, (1, 1, 1, 1), mode='replicate')
            inplane = gx * (pad[:, :, 1:-1, 2:] + pad[:, :, 1:-1, :-2]) \
                + gy * (pad[:, :, 2:, 1:-1] + pad[:, :, :-2, 1:-1])

            vertical = torch.zeros_like(t)
            for i in range(self.layers):
                if i > 0:
                    vertical[:, i] += self.gz[i - 1] * t[:, i - 1]
                if i < self.layers - 1:
                    vertical[:, i] += self.gz[i] * t[:, i + 1]

            t_new = (inplane + vertical + bc_source + power_map) / denom
            last_delta = float((t_new - t).abs().max())
            t = t_new
            if last_delta < tol:
                break

        self.iterations_used = it + 1
        self.final_delta = last_delta
        if verbose:
            print(f"  [Solver] converged in {self.iterations_used} iterations "
                  f"(max update {last_delta:.2e} K)")
        if last_delta >= tol:
            print(f"  ⚠️  [Solver] did not converge: max update {last_delta:.2e} K "
                  f"after {iterations} iterations")
        return t.to(torch.float32)

    def energy_balance(self, t, power_map):
        """Heat leaving the convective faces must equal the power injected."""
        t = t.to(torch.float64)
        power_map = power_map.to(torch.float64)
        out = (self.g_top * (t[:, 0] - self.t_ambient)).sum(dim=(-1, -2)) \
            + (self.g_bot * (t[:, -1] - self.t_ambient)).sum(dim=(-1, -2))
        p_in = power_map.sum(dim=(-1, -2, -3))
        return {"power_in_w": float(p_in[0]), "power_out_w": float(out[0]),
                "relative_error": float(((p_in - out).abs() / p_in.clamp(min=1e-12))[0])}

    def verify(self):
        """Self-check: gradient direction, energy balance, and convergence."""
        print("Running Nodal Laplacian Check...")
        print(f"  Topology: {self.topology}")
        print(f"  Geometry: {self.width_m*1e3:.1f} x {self.depth_m*1e3:.1f} mm, "
              f"dx={self.dx*1e6:.1f} um, dz={[f'{z*1e6:.0f}' for z in self.dz]} um")
        print(f"  Boundary: h_top={self.h_top:.0f} W/m2K, h_bot={self.h_bottom:.0f}, "
              f"T_inf={self.t_ambient:.1f} C")

        power = torch.zeros((1, self.layers, self.grid_size, self.grid_size))
        c = self.grid_size // 2
        power[0, 0, c - 1:c + 1, c - 1:c + 1] = 10.0 / 4.0      # 10 W hotspot

        t = self.solve_steady_state(power, verbose=True)
        eb = self.energy_balance(t, power)
        print(f"  Test Hotspot (10W): Max T = {t.max():.2f}C, Min T = {t.min():.2f}C")
        print(f"  Gradient Check: Layer 0 ({t[0,0].max():.2f}C) vs "
              f"Layer 1 ({t[0,1].max():.2f}C)")
        print(f"  Energy Balance: in {eb['power_in_w']:.4f} W, out "
              f"{eb['power_out_w']:.4f} W, rel err {eb['relative_error']:.2e}")

        ok = True
        if t[0, 0].max() <= t[0, min(1, self.layers - 1)].max():
            print("  ❌ Gradient wrong: heat is not flowing from source to sink.")
            ok = False
        else:
            print("  ✅ Gradient Correct: Heat flowing from Source to Sink.")
        if eb['relative_error'] > 1e-5:
            print(f"  ❌ Energy not conserved: {eb['relative_error']:.2e}")
            ok = False
        else:
            print("  ✅ Energy Conserved.")
        return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--mode', type=str, default='3d_6neighbor')
    parser.add_argument('--config', type=str,
                        default='../physics_accelerated/results/golden_config.json')
    args = parser.parse_args()

    path = args.config
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(__file__), '..', '..', '..',
                            'physics_accelerated/results/golden_config.json')
    solver = ThermalSolver(path)
    if args.verify:
        ok = solver.verify()
        raise SystemExit(0 if ok else 1)
