"""Grid-converged steady-state thermal reference solver, in SI units.

This exists because nothing in the repository could act as a reference. The
Jacobi solver in serdes_architect/src/thermal/solver.py used a normalized grid
spacing (dx = dy = dz = 1.0) with a hand-tuned PHYSICAL_SCALE = 500.0 chosen to
make one 10 mm / 100 W case land near 85 C, so its output was a relative field,
not a temperature.

This module is deliberately a different method from that one, so agreement
between them is evidence rather than tautology:

    discretisation : finite volume, harmonic-mean face conductance
    boundaries     : Robin (convective), h in W/m^2K
    solution       : direct sparse solve (scipy), not relaxation
    units          : SI throughout (m, W, K)

Verification, in order of strength:
    1. analytic 1D slab conduction          -> exact to solver tolerance
    2. global energy balance                -> heat out == power in
    3. mesh convergence + Richardson        -> observed order and GCI

Solving the conduction equation:   div(k grad T) + q = 0
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


@dataclass
class Layer:
    """One material layer in the vertical stack."""
    name: str
    thickness_m: float
    k_w_mk: float
    power_w: float = 0.0          # total power dissipated in this layer
    n_cells_z: int = 2            # vertical cells (refined by the convergence study)


@dataclass
class Boundary:
    """Convective boundary condition: q = h (T - T_inf)."""
    h_top_w_m2k: float = 5000.0       # cold plate / liquid loop on the top face
    h_bottom_w_m2k: float = 50.0      # board-side, mostly insulating
    h_side_w_m2k: float = 0.0         # adiabatic sides (die in an array)
    t_ambient_c: float = 45.0


@dataclass
class Solution:
    t_field_c: np.ndarray             # [nz, ny, nx]
    t_peak_c: float
    t_mean_c: float
    hotspot_index: tuple[int, int, int]
    nx: int
    ny: int
    nz: int
    n_unknowns: int
    energy_balance: dict
    layer_peaks_c: dict


class ThermalReference:
    def __init__(self, layers: list[Layer], width_m: float, depth_m: float,
                 boundary: Boundary | None = None):
        if not layers:
            raise ValueError("at least one layer is required")
        self.layers = layers
        self.width_m = float(width_m)
        self.depth_m = float(depth_m)
        self.bc = boundary or Boundary()

    # -- mesh ----------------------------------------------------------------
    def _mesh(self, nx: int, ny: int, refine_z: int = 1):
        """Cell-centred mesh. Returns (dz per cell, k per cell, layer id per cell)."""
        dz, kz, layer_of = [], [], []
        for idx, layer in enumerate(self.layers):
            n = max(1, layer.n_cells_z * refine_z)
            h = layer.thickness_m / n
            for _ in range(n):
                dz.append(h)
                kz.append(layer.k_w_mk)
                layer_of.append(idx)
        return (np.asarray(dz), np.asarray(kz), np.asarray(layer_of),
                self.width_m / nx, self.depth_m / ny)

    def _power_density(self, nx: int, ny: int, layer_of: np.ndarray,
                       hotspots: dict[int, tuple[float, float, float]] | None):
        """Per-cell power [W]. hotspots maps layer index -> (cx, cy, radius_frac)."""
        nz = len(layer_of)
        q = np.zeros((nz, ny, nx))
        xs = (np.arange(nx) + 0.5) / nx
        ys = (np.arange(ny) + 0.5) / ny
        gx, gy = np.meshgrid(xs, ys, indexing="xy")
        for li, layer in enumerate(self.layers):
            if layer.power_w == 0.0:
                continue
            cells = np.where(layer_of == li)[0]
            if hotspots and li in hotspots:
                cx, cy, r = hotspots[li]
                mask = ((gx - cx) ** 2 + (gy - cy) ** 2) <= r * r
                if not mask.any():
                    mask = np.ones_like(gx, dtype=bool)
                weight = mask.astype(float)
            else:
                weight = np.ones_like(gx)
            weight = weight / weight.sum()
            per_cell_layer = layer.power_w / len(cells)
            for cz in cells:
                q[cz] = weight * per_cell_layer
        return q

    # -- assembly ------------------------------------------------------------
    def solve(self, nx: int = 32, ny: int = 32, refine_z: int = 1,
              hotspots: dict[int, tuple[float, float, float]] | None = None) -> Solution:
        dz, kz, layer_of, dx, dy = self._mesh(nx, ny, refine_z)
        nz = len(dz)
        n = nx * ny * nz
        q = self._power_density(nx, ny, layer_of, hotspots)

        def idx(iz, iy, ix):
            return (iz * ny + iy) * nx + ix

        rows, cols, vals = [], [], []
        rhs = np.zeros(n)
        t_inf = self.bc.t_ambient_c

        for iz in range(nz):
            area_z = dx * dy                       # horizontal face area
            for iy in range(ny):
                for ix in range(nx):
                    p = idx(iz, iy, ix)
                    diag = 0.0
                    rhs[p] += q[iz, iy, ix]

                    # in-plane neighbours: same layer, so k is uniform across the face
                    for dix, diy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        jx, jy = ix + dix, iy + diy
                        if 0 <= jx < nx and 0 <= jy < ny:
                            span = dx if dix else dy
                            area = dy * dz[iz] if dix else dx * dz[iz]
                            g = kz[iz] * area / span
                            diag += g
                            rows.append(p); cols.append(idx(iz, jy, jx)); vals.append(-g)
                        elif self.bc.h_side_w_m2k > 0.0:
                            area = dy * dz[iz] if dix else dx * dz[iz]
                            g = self.bc.h_side_w_m2k * area
                            diag += g
                            rhs[p] += g * t_inf

                    # vertical neighbours: harmonic mean across a material change
                    for diz in (-1, 1):
                        jz = iz + diz
                        if 0 <= jz < nz:
                            # series resistance of the two half-cells
                            r = (dz[iz] / 2.0) / kz[iz] + (dz[jz] / 2.0) / kz[jz]
                            g = area_z / r
                            diag += g
                            rows.append(p); cols.append(idx(jz, iy, ix)); vals.append(-g)
                        else:
                            h = (self.bc.h_top_w_m2k if diz < 0
                                 else self.bc.h_bottom_w_m2k)
                            if h <= 0.0:
                                continue
                            # convective film in series with the half-cell
                            r = (dz[iz] / 2.0) / kz[iz] + 1.0 / h
                            g = area_z / r
                            diag += g
                            rhs[p] += g * t_inf

                    rows.append(p); cols.append(p); vals.append(diag)

        a = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
        t = spla.spsolve(a, rhs)
        field = t.reshape(nz, ny, nx)

        peak_flat = int(np.argmax(field))
        hotspot = np.unravel_index(peak_flat, field.shape)
        return Solution(
            t_field_c=field,
            t_peak_c=float(field.max()),
            t_mean_c=float(field.mean()),
            hotspot_index=(int(hotspot[0]), int(hotspot[1]), int(hotspot[2])),
            nx=nx, ny=ny, nz=nz, n_unknowns=n,
            energy_balance=self._energy_balance(field, dz, kz, dx, dy, q),
            layer_peaks_c={self.layers[li].name: float(field[layer_of == li].max())
                           for li in range(len(self.layers))},
        )

    def _energy_balance(self, field, dz, kz, dx, dy, q) -> dict:
        """Heat leaving through the convective faces must equal power in."""
        area_z = dx * dy
        t_inf = self.bc.t_ambient_c
        out = 0.0
        for face, h, iz in (("top", self.bc.h_top_w_m2k, 0),
                            ("bottom", self.bc.h_bottom_w_m2k, len(dz) - 1)):
            if h <= 0.0:
                continue
            r = (dz[iz] / 2.0) / kz[iz] + 1.0 / h
            out += float(((field[iz] - t_inf) * area_z / r).sum())
        if self.bc.h_side_w_m2k > 0.0:
            for iz in range(len(dz)):
                perim = 2 * (field[iz, 0, :].sum() + field[iz, -1, :].sum()) * 0 \
                        + 0.0            # sides handled in assembly; not summed here
                out += perim
        power_in = float(q.sum())
        return {"power_in_w": power_in, "power_out_w": out,
                "residual_w": power_in - out,
                "relative_error": abs(power_in - out) / power_in if power_in else 0.0}

    # -- verification --------------------------------------------------------
    def mesh_convergence(self, base_nx: int = 16, levels: int = 3,
                         hotspots=None) -> dict:
        """Successive refinement + Richardson extrapolation (ASME V&V 20 style).

        Returns observed order of accuracy, the extrapolated peak temperature,
        and the grid-convergence index of the finest mesh.

        Caveat on `observed_order_p`: with a discontinuous source term (a hotspot
        mask) the discrete footprint changes as the mesh refines, so the grids are
        not in the asymptotic range and p is not a meaningful order of accuracy --
        values of 4-6 are routine here. The GCI and the extrapolated value remain
        useful; p should not be quoted as the scheme's order. On the smooth
        analytic benchmark this discretisation is exact, so its order cannot be
        measured that way either.
        """
        runs = []
        for level in range(levels):
            f = 2 ** level
            sol = self.solve(nx=base_nx * f, ny=base_nx * f, refine_z=f,
                             hotspots=hotspots)
            runs.append({"nx": sol.nx, "nz": sol.nz, "unknowns": sol.n_unknowns,
                         "t_peak_c": sol.t_peak_c,
                         "energy_rel_err": sol.energy_balance["relative_error"]})
        out = {"runs": runs}
        if levels >= 3:
            t1, t2, t3 = (r["t_peak_c"] for r in runs[-3:])
            e21, e32 = t2 - t1, t3 - t2
            if abs(e32) > 1e-12 and abs(e21) > 1e-12 and (e21 / e32) > 0:
                p = math.log(abs(e21 / e32)) / math.log(2.0)
                t_exact = t3 + e32 / (2.0 ** p - 1.0)
                gci = 1.25 * abs(e32 / t3) / (2.0 ** p - 1.0) * 100.0
                out.update({"observed_order_p": p,
                            "richardson_t_peak_c": t_exact,
                            "gci_finest_pct": gci,
                            "converged": gci < 1.0})
            else:
                out.update({"observed_order_p": None,
                            "richardson_t_peak_c": t3,
                            "gci_finest_pct": None,
                            "converged": abs(e32) < 0.05,
                            "note": "differences below extrapolation resolution"})
        return out


# --- analytic benchmark ------------------------------------------------------
def analytic_slab_peak_c(power_w: float, area_m2: float, thickness_m: float,
                         k_w_mk: float, h_w_m2k: float, t_inf_c: float) -> float:
    """Peak temperature of a slab with uniform volumetric heating, insulated on
    one face, convective on the other.

    q'' = P/A through the convective face; inside the slab with uniform
    generation the profile is parabolic, giving
        T_max = T_inf + q''/h + q''*L/(2k)
    """
    flux = power_w / area_m2
    return t_inf_c + flux / h_w_m2k + flux * thickness_m / (2.0 * k_w_mk)


def from_stackup(path: str | Path, total_power_w: float | None = None,
                 boundary: Boundary | None = None) -> ThermalReference:
    """Build a reference model from the interchange layer's stackup JSON."""
    doc = json.loads(Path(path).read_text())
    if doc.get("units", {}).get("length") != "um":
        raise ValueError("stackup must declare length units in um")
    dies = doc["dies"]
    layers = [Layer(name=d["name"], thickness_m=d["thickness_um"] * 1e-6,
                    k_w_mk=d["k_w_mk"], power_w=d.get("power_w", 0.0))
              for d in dies]
    if total_power_w is not None:
        scale = total_power_w / max(sum(l.power_w for l in layers), 1e-12)
        for l in layers:
            l.power_w *= scale
    w = max(d["size_um"][0] for d in dies) * 1e-6
    d_ = max(d["size_um"][1] for d in dies) * 1e-6
    bnd = boundary or Boundary(t_ambient_c=doc.get("boundary", {})
                               .get("case_temp_c", 45.0))
    return ThermalReference(layers, w, d_, bnd)
