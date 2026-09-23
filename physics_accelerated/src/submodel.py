"""Resolve a hotspot region without resolving the whole die.

The project's finest global mesh has **562 µm** cells on an 18 mm die. Real
hotspot structure is tens of microns. Refining globally is unaffordable and, more
importantly, would answer the wrong question: the grid-convergence study already
showed the *discretisation* is converged (0.18 °C between 32×32×10 and
64×64×20). What is not converged is the **input** — a power map already smeared
into 1.125 mm blocks. Converging the mesh under a smeared input is a converged
answer to a question nobody asked.

Submodeling separates the two. Solve globally coarse, cut out a region, and
re-solve it on a fine mesh that inherits its surroundings through a prescribed
boundary temperature. Cost scales with the region, not the die, so a 2 mm box at
35 µm resolution is affordable while the same resolution over 18 mm is not.

Two properties make it trustworthy rather than merely plausible:

  * **Exactness at matching resolution.** Run the submodel at the parent's own
    in-plane resolution and it must reproduce the parent's interior to solver
    tolerance. The boundary temperature is interpolated to the *face*, so the
    Dirichlet half-cell conductance (k·A / (span/2)) reproduces the parent's
    full-cell coupling (k·A / span) exactly. This is checked, not assumed.
  * **Region independence.** Enlarge the box and the peak must not move. The
    submodel inherits the parent's error at its boundary, so the boundary has to
    sit where that error no longer matters — which is a measurement, not a
    judgement call.

A previous `transient_roi_solver.py` was deleted from this repository for
reporting a fabricated peak alongside a "100,000×" speedup. The concept was
never the problem. The absence of those two checks was.

Run
---
    python submodel.py              # writes reports/submodel.json
    python submodel.py --verify     # assertions only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "serdes_architect", "src"))

from thermal_reference import ThermalReference                    # noqa: E402
from trust_guard import (ReferenceCascade, build_context,         # noqa: E402
                         expand_power_map)
from pareto_search import build_power_maps                        # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"

# Above this, a row is an illustration of the trend rather than a design.
# High-performance logic hotspots run a few hundred W/cm2; ~1 kW/cm2 is the
# top of what is normally discussed for a local hotspot.
PLAUSIBLE_W_CM2 = 1000.0


@dataclass(frozen=True)
class ROI:
    """A sub-rectangle of the die, in fractions of the footprint."""
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self):
        if not (0.0 < self.x0 < self.x1 < 1.0 and 0.0 < self.y0 < self.y1 < 1.0):
            raise ValueError(
                "the region must be strictly interior: a face that coincides "
                "with the die edge is a real boundary condition, not something "
                "to inherit from the parent solve")

    def cells(self, nx: int, ny: int) -> tuple[int, int, int, int]:
        """Parent cell index range covered, snapped outward to whole cells."""
        return (int(np.floor(self.x0 * nx)), int(np.floor(self.y0 * ny)),
                int(np.ceil(self.x1 * nx)), int(np.ceil(self.y1 * ny)))

    def snapped(self, nx: int, ny: int) -> "ROI":
        i0, j0, i1, j1 = self.cells(nx, ny)
        return ROI(i0 / nx, j0 / ny, i1 / nx, j1 / ny)


def _interp_layer(field2d: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                  qx: np.ndarray, qy: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of one layer at arbitrary points, clamped."""
    ny, nx = field2d.shape
    fx = np.clip(np.interp(qx, xs, np.arange(nx)), 0, nx - 1)
    fy = np.clip(np.interp(qy, ys, np.arange(ny)), 0, ny - 1)
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    x1, y1 = np.minimum(x0 + 1, nx - 1), np.minimum(y0 + 1, ny - 1)
    tx, ty = fx - x0, fy - y0
    return ((1 - tx) * (1 - ty) * field2d[y0, x0]
            + tx * (1 - ty) * field2d[y0, x1]
            + (1 - tx) * ty * field2d[y1, x0]
            + tx * ty * field2d[y1, x1])


def side_temperature(parent_field: np.ndarray, roi: ROI, nx_l: int, ny_l: int
                     ) -> np.ndarray:
    """Parent temperature interpolated onto each boundary *face*, per face.

    Two details, both of which the exactness check caught rather than confirmed:

    * **Face, not cell centre.** The local Dirichlet term is
      k·A/(span/2)·(T_face − T_cell) while the parent's coupling is
      k·A/span·(T_neighbour − T_cell). Those agree when T_face is the mean of
      the two cell centres, which a bilinear interpolation to the face returns.
    * **Per face, not per cell.** A corner cell has two open faces looking at
      two different neighbours. Sharing one value between them left a 3.0e-2 °C
      error at the parent's own resolution -- small, entirely at the corners,
      and exactly the kind of thing that passes an eyeball and fails a check.

    Returns [4, nz, ny_l, nx_l], ordered -x, +x, -y, +y to match the solver's
    own face ordering.
    """
    nz, ny_p, nx_p = parent_field.shape
    xs = (np.arange(nx_p) + 0.5) / nx_p
    ys = (np.arange(ny_p) + 0.5) / ny_p
    lx = roi.x0 + (np.arange(nx_l) + 0.5) / nx_l * (roi.x1 - roi.x0)
    ly = roi.y0 + (np.arange(ny_l) + 0.5) / ny_l * (roi.y1 - roi.y0)

    out = np.zeros((4, nz, ny_l, nx_l))
    for iz in range(nz):
        f = parent_field[iz]
        # -x and +x faces: vary along y, pinned in x at the region's edge
        out[0, iz][:, 0] = _interp_layer(f, xs, ys, np.full(ny_l, roi.x0), ly)
        out[1, iz][:, -1] = _interp_layer(f, xs, ys, np.full(ny_l, roi.x1), ly)
        # -y and +y faces: vary along x
        out[2, iz][0, :] = _interp_layer(f, xs, ys, lx, np.full(nx_l, roi.y0))
        out[3, iz][-1, :] = _interp_layer(f, xs, ys, lx, np.full(nx_l, roi.y1))
    return out


def local_model(parent: ThermalReference, roi: ROI) -> ThermalReference:
    """The same stack, over the region's footprint."""
    return ThermalReference(parent.layers,
                            parent.width_m * (roi.x1 - roi.x0),
                            parent.depth_m * (roi.y1 - roi.y0),
                            parent.bc,
                            k_lateral_scale=parent.k_lateral_scale)


def crop_power(parent_q: np.ndarray, roi: ROI, refine: int) -> np.ndarray:
    """The parent's load inside the region, upsampled, watts conserved."""
    nz, ny_p, nx_p = parent_q.shape
    i0, j0, i1, j1 = roi.cells(nx_p, ny_p)
    sub = parent_q[:, j0:j1, i0:i1]
    up = np.repeat(np.repeat(sub, refine, axis=1), refine, axis=2)
    return up / (refine * refine)


def concentrate(q_fine: np.ndarray, fraction_of_power: float,
                fraction_of_area: float) -> np.ndarray:
    """Move part of each layer's power into a central core of the heated area.

    This is the *input* resolution the global mesh cannot represent: the same
    watts, arranged with structure below a parent cell. `fraction_of_power` = 0
    returns the uniform map unchanged.
    """
    if not 0.0 <= fraction_of_power < 1.0:
        raise ValueError("fraction_of_power must be in [0, 1)")
    if not 0.0 < fraction_of_area <= 1.0:
        raise ValueError("fraction_of_area must be in (0, 1]")
    out = q_fine.copy()
    for iz in range(out.shape[0]):
        plane = out[iz]
        total = plane.sum()
        if total <= 0.0:
            continue
        hot = plane > 0.0
        idx = np.argwhere(hot)
        cy, cx = idx.mean(axis=0)
        side = max(1, int(round(np.sqrt(hot.sum() * fraction_of_area))))
        y0 = int(np.clip(round(cy - side / 2), 0, plane.shape[0] - side))
        x0 = int(np.clip(round(cx - side / 2), 0, plane.shape[1] - side))
        core = np.zeros_like(plane, dtype=bool)
        core[y0:y0 + side, x0:x0 + side] = True
        core &= hot
        if not core.any():
            continue
        moved = total * fraction_of_power
        plane[hot] *= (total - moved) / total
        plane[core] += moved / core.sum()
    return out


def solve_region(parent: ThermalReference, parent_field: np.ndarray,
                 parent_q: np.ndarray, roi: ROI, refine: int,
                 q_fine: np.ndarray | None = None,
                 refine_z: int | None = None):
    """Fine solve over the region, inheriting the parent through its boundary.

    The vertical structure follows the parent's: refining in-plane is the point
    (562 um cells against tens-of-micron features), and keeping z aligned is
    what lets the boundary temperatures be read straight off the parent field
    without a second interpolation.
    """
    nz, ny_p, nx_p = parent_field.shape
    if refine_z is None:
        base_nz = sum(max(1, l.n_cells_z) for l in parent.layers)
        if nz % base_nz:
            raise ValueError(f"parent has {nz} z-cells over {base_nz} layer "
                             f"cells: not an integer refinement")
        refine_z = nz // base_nz
    roi = roi.snapped(nx_p, ny_p)
    i0, j0, i1, j1 = roi.cells(nx_p, ny_p)
    nx_l, ny_l = (i1 - i0) * refine, (j1 - j0) * refine
    q = crop_power(parent_q, roi, refine) if q_fine is None else q_fine
    st = side_temperature(parent_field, roi, nx_l, ny_l)
    model = local_model(parent, roi)
    sol = model.solve(nx=nx_l, ny=ny_l, refine_z=refine_z, power_map=q,
                      side_temp=st)
    return sol, roi, q


# --- the two checks that make it trustworthy -------------------------------

def exactness(parent: ThermalReference, parent_sol, parent_q: np.ndarray,
              roi: ROI) -> dict:
    """At the parent's own resolution the submodel must reproduce its interior."""
    sol, roi_s, _ = solve_region(parent, parent_sol.t_field_c, parent_q, roi,
                                 refine=1)
    nz, ny_p, nx_p = parent_sol.t_field_c.shape
    i0, j0, i1, j1 = roi_s.cells(nx_p, ny_p)
    parent_block = parent_sol.t_field_c[:, j0:j1, i0:i1]
    err = np.abs(sol.t_field_c - parent_block)
    # The first ring is pinned by construction; the interior is the real test.
    interior = err[:, 1:-1, 1:-1] if min(err.shape[1:]) > 2 else err
    return {"max_abs_c": float(err.max()),
            "interior_max_abs_c": float(interior.max()),
            "cells": int(err.size)}


def region_independence(parent: ThermalReference, parent_sol, parent_q,
                        centre: tuple[float, float], half_sizes, refine: int,
                        nx: int, ny: int) -> list[dict]:
    """Grow the box; the peak must stop moving before the answer is usable."""
    out = []
    for h in half_sizes:
        roi = _box(centre, h, nx, ny)
        sol, roi_s, _ = solve_region(parent, parent_sol.t_field_c, parent_q,
                                     roi, refine=refine)
        out.append({"half_size_frac": h,
                    "box_mm": [(roi_s.x1 - roi_s.x0) * parent.width_m * 1e3,
                               (roi_s.y1 - roi_s.y0) * parent.depth_m * 1e3],
                    "cells": int(sol.t_field_c.size),
                    "peak_c": float(sol.t_field_c[0].max()),
                    "lateral_out_w": sol.energy_balance["lateral_out_w"],
                    "energy_rel_err": sol.energy_balance["relative_error"]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--front", default=str(REPO_ROOT / "reports/pareto_front_nsga2.json"))
    ap.add_argument("--design", type=int, default=0, help="front index")
    ap.add_argument("--parent-refine", type=int, default=2)
    ap.add_argument("--refine", type=int, default=8)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/submodel.json"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    layers = int(cfg["voxel_stack_params"]["layers"])
    _, cascade = build_context(Path(args.config))
    ref = cascade.ref

    front = json.loads(Path(args.front).read_text())
    keys = front["genome_keys"]
    genome = np.array([[front["front_genomes"][args.design][k] for k in keys]])
    coarse_map = build_power_maps(genome, total_w * 0.75, total_w * 0.25,
                                  layers).numpy()[0]

    lv = cascade.level(args.parent_refine)
    parent_q = expand_power_map(coarse_map, args.parent_refine,
                                lv.mesh["layer_of"])
    parent_sol = ref.solve(nx=lv.mesh["nx"], ny=lv.mesh["ny"],
                           refine_z=args.parent_refine, power_map=parent_q)
    peak_idx = np.unravel_index(int(np.argmax(parent_sol.t_field_c[0])),
                                parent_sol.t_field_c[0].shape)
    centre = ((peak_idx[1] + 0.5) / lv.mesh["nx"],
              (peak_idx[0] + 0.5) / lv.mesh["ny"])

    nx_p, ny_p = lv.mesh["nx"], lv.mesh["ny"]
    exact = exactness(ref, parent_sol, parent_q, _box(centre, 0.15, nx_p, ny_p))
    indep = region_independence(ref, parent_sol, parent_q, centre,
                                (0.10, 0.15, 0.20, 0.25), refine=2,
                                nx=nx_p, ny=ny_p)

    roi = _box(centre, 0.15, nx_p, ny_p)
    sweep = []
    for phi, area in ((0.0, 1.0), (0.25, 0.25), (0.5, 0.25), (0.5, 0.0625),
                      (0.75, 0.0625), (0.9, 0.0156)):
        sol, roi_s, q = solve_region(ref, parent_sol.t_field_c, parent_q, roi,
                                     refine=args.refine)
        if phi > 0.0:
            q = concentrate(q, phi, area)
            sol, roi_s, _ = solve_region(ref, parent_sol.t_field_c, parent_q,
                                         roi, refine=args.refine, q_fine=q)
        cell_um = (roi_s.x1 - roi_s.x0) * ref.width_m * 1e6 / q.shape[2]
        peak_density = float(q[0].max() / (cell_um * 1e-6) ** 2 / 1e4)  # W/cm2
        sweep.append({"power_fraction_in_core": phi, "core_area_fraction": area,
                      "cell_um": cell_um, "peak_w_per_cm2": peak_density,
                      "plausible": peak_density <= PLAUSIBLE_W_CM2,
                      "peak_c": float(sol.t_field_c[0].max()),
                      "energy_rel_err": sol.energy_balance["relative_error"]})

    base = sweep[0]["peak_c"]
    plausible = [r for r in sweep if r["plausible"]]
    doc = {
        "question": ("how much of the published temperature depends on power "
                     "being uniform inside a 1.125 mm cell?"),
        "design_index": args.design,
        "parent": {"mesh": lv.shape, "peak_c": float(parent_sol.t_field_c[0].max()),
                   "cell_um": ref.width_m * 1e6 / lv.mesh["nx"]},
        "region": {"centre_frac": list(centre),
                   "box_frac": [roi.x0, roi.y0, roi.x1, roi.y1],
                   "refine": args.refine},
        "exactness_at_parent_resolution": exact,
        "region_independence": indep,
        "input_resolution_sweep": sweep,
        "headline": {
            "uniform_peak_c": base,
            "worst_plausible_peak_c": plausible[-1]["peak_c"],
            "worst_plausible_w_per_cm2": plausible[-1]["peak_w_per_cm2"],
            "delta_c": plausible[-1]["peak_c"] - base,
            "most_concentrated_peak_c": sweep[-1]["peak_c"],
            "most_concentrated_delta_c": sweep[-1]["peak_c"] - base,
            "plausibility_threshold_w_per_cm2": PLAUSIBLE_W_CM2,
            "note": ("same watts, same mesh, redistributed inside the macro's "
                     "own footprint -- an error the global solve cannot see and "
                     "grid convergence cannot detect. The headline delta is "
                     "taken over rows below the plausibility threshold; the "
                     "rows above it show where the trend goes, and are not "
                     "predictions"),
        },
        "caveats": [
            "the concentration profile is a parameterised assumption, not a "
            "floorplan: this measures sensitivity to unresolved structure, it "
            "does not claim to know what the structure is",
            "the submodel inherits the parent's error at its boundary, which is "
            "what region_independence tests",
        ],
    }
    print_report(doc)
    ok = _assert_behaves(doc)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


def _box(centre: tuple[float, float], half: float, nx: int, ny: int) -> ROI:
    """A box of the requested size, *shifted* to stay interior rather than
    clipped.

    Clipping would silently shrink the region for a hotspot near the die edge,
    which is where the hotspots on this front actually sit -- and a smaller
    region is exactly the case region_independence is meant to reject. One
    parent cell of margin keeps the boundary off the die edge, where the
    condition is real and not inheritable.
    """
    def axis(c: float, n: int) -> tuple[float, float]:
        margin = 1.0 / n
        span = min(2.0 * half, 1.0 - 2.0 * margin)
        lo = min(max(c - span / 2.0, margin), 1.0 - margin - span)
        return lo, lo + span

    x0, x1 = axis(centre[0], nx)
    y0, y1 = axis(centre[1], ny)
    return ROI(x0, y0, x1, y1)


def print_report(doc: dict) -> None:
    p, r = doc["parent"], doc["region"]
    e = doc["exactness_at_parent_resolution"]
    print(f"🔬 Submodel: parent {p['mesh']} at {p['cell_um']:.0f} um/cell, peak "
          f"{p['peak_c']:.2f} C; region refined {r['refine']}x\n")
    print(f"  exactness at parent resolution : {e['interior_max_abs_c']:.2e} C "
          f"over {e['cells']} cells")
    print(f"  region independence (peak must stop moving as the box grows):")
    for row in doc["region_independence"]:
        print(f"    {row['box_mm'][0]:5.1f} x {row['box_mm'][1]:4.1f} mm  "
              f"{row['cells']:7d} cells  peak {row['peak_c']:7.3f} C  "
              f"lateral {row['lateral_out_w']:7.2f} W  "
              f"energy {row['energy_rel_err']:.1e}")
    print(f"\n  input resolution: same watts, redistributed inside the macro")
    print(f"    {'in core':>8} {'core area':>10} {'W/cm2':>9} {'peak':>9} "
          f"{'vs uniform':>11}")
    base = doc["headline"]["uniform_peak_c"]
    for row in doc["input_resolution_sweep"]:
        print(f"    {row['power_fraction_in_core']:7.0%} "
              f"{row['core_area_fraction']:10.2%} {row['peak_w_per_cm2']:9.1f} "
              f"{row['peak_c']:8.2f}C {row['peak_c'] - base:+10.2f}C"
              f"{'' if row['plausible'] else '   (beyond plausible density)'}")
    h = doc["headline"]
    print(f"\n  {h['delta_c']:+.2f} C between a uniform macro and the most "
          f"concentrated variant still under "
          f"{h['plausibility_threshold_w_per_cm2']:.0f} W/cm2, at identical "
          f"total power.")


def _assert_behaves(doc: dict) -> bool:
    ok = True
    e = doc["exactness_at_parent_resolution"]
    if e["interior_max_abs_c"] > 1e-6:
        print(f"\n  ❌ at the parent's own resolution the submodel differs from "
              f"the parent by {e['interior_max_abs_c']:.2e} C; the boundary "
              f"treatment is wrong.")
        ok = False
    peaks = [r["peak_c"] for r in doc["region_independence"]]
    if abs(peaks[-1] - peaks[-2]) > 0.05:
        print(f"\n  ❌ the peak is still moving at the largest box "
              f"({abs(peaks[-1] - peaks[-2]):.3f} C): the boundary is too close "
              f"to the hotspot for the result to be usable.")
        ok = False
    if any(r["energy_rel_err"] > 1e-9 for r in doc["region_independence"]):
        print("\n  ❌ a submodel does not close its own energy budget.")
        ok = False
    if ok:
        print("\n  ✅ the submodel reproduces its parent where it should, closes "
              "its energy budget including the lateral term, and its peak is "
              "independent of where the boundary sits.")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
