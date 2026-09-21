"""Proper-orthogonal-decomposition reduced-order model for the thermal stack.

This was the last unimplemented item from the project's original claims. The
documents used to describe a ROM with a "1.9M x speedup" against Ansys Icepak;
no POD, SVD or modal decomposition existed anywhere in the repository, and no
Icepak dataset existed either. What follows is the real thing, measured.

Method
------
The reference solver assembles A T = b, where A depends only on geometry and
boundary conditions and b carries the load. Varying *where* the heat is applied
therefore moves b around a parameter space while A stays fixed, which is the
textbook setting for a parameterised POD-Galerkin ROM:

    1. snapshots   solve A T_i = b(mu_i) for M sampled parameters
    2. POD         X = [T_1 ... T_M] = U S V^T; keep the leading r columns U_r
    3. projection  solve (U_r^T A U_r) a = U_r^T b, then T ~= U_r a

Step 3 is a Galerkin projection of the same operator, not a regression fitted
to the outputs: the reduced system is r x r and still carries the physics.

What is reported
----------------
Truncation error, not a speedup ratio, because a speedup ratio here would be an
internal number about this mesh on this hardware and says nothing about
agreement with any commercial tool. Specifically:

  * the POD spectrum and retained energy;
  * the *projection* error on held-out snapshots -- the floor no r-mode ROM can
    beat, since it is the distance from the held-out field to the span of U_r;
  * the *ROM* error on held-out snapshots, which is what you actually get;
  * peak-temperature error in degrees C, which is the number a designer quotes.

Held-out means held out: the test parameters are drawn from a separate stream
and never enter the snapshot matrix.

Run
---
    python thermal_rom.py                 # builds the ROM and writes the report
    python thermal_rom.py --verify        # the assertions, no report file
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import scipy.sparse.linalg as spla

from thermal_reference import Boundary, Layer, ThermalReference

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- the parameter space -------------------------------------------------

@dataclass(frozen=True)
class HotspotParams:
    """Where the logic hotspot sits, how tight it is, and the power split.

    The first three are genuinely nonlinear in the field: moving a hotspot is
    not a scaling of any other hotspot's solution, which is what makes the POD
    basis worth building. The power split is linear and is included because the
    optimiser varies it.
    """
    cx: float
    cy: float
    radius_frac: float
    logic_fraction: float

    def as_dict(self) -> dict:
        return {"cx": self.cx, "cy": self.cy,
                "radius_frac": self.radius_frac,
                "logic_fraction": self.logic_fraction}


def sample_params(n: int, seed: int) -> list[HotspotParams]:
    rng = np.random.default_rng(seed)
    return [HotspotParams(cx=float(rng.uniform(0.2, 0.8)),
                          cy=float(rng.uniform(0.2, 0.8)),
                          radius_frac=float(rng.uniform(0.08, 0.28)),
                          logic_fraction=float(rng.uniform(0.45, 0.85)))
            for _ in range(n)]


# --- the model -----------------------------------------------------------

@dataclass
class PODBasis:
    """The full left-singular basis plus the rank currently in use.

    Holding all the modes and truncating through a property, rather than
    storing a truncated array, is deliberate: the first version discarded the
    tail on set_rank, so every rank after the first was silently capped at the
    smallest one ever requested and the rank sweep reported a flat line.
    """
    all_modes: np.ndarray              # [n, M]
    singular_values: np.ndarray        # [min(n, M)]
    rank: int

    @property
    def modes(self) -> np.ndarray:
        return self.all_modes[:, :self.rank]

    @property
    def max_rank(self) -> int:
        return self.all_modes.shape[1]

    @property
    def retained_energy(self) -> float:
        s2 = self.singular_values ** 2
        return float(s2[:self.rank].sum() / s2.sum())


class ThermalROM:
    """POD-Galerkin ROM over hotspot position and power split."""

    def __init__(self, ref: ThermalReference, nx: int = 32, ny: int = 32,
                 refine_z: int = 1):
        self.ref = ref
        self.nx, self.ny, self.refine_z = nx, ny, refine_z
        # A is parameter-independent, so it is assembled and factorised once.
        # Every snapshot after the first is a back-substitution.
        a, _, mesh = ref.assemble(nx, ny, refine_z)
        self.a = a
        self.mesh = mesh
        self.n = nx * ny * mesh["nz"]
        self.lu = spla.splu(a.tocsc())
        self.basis: PODBasis | None = None
        self._a_reduced: np.ndarray | None = None

    @classmethod
    def from_operator(cls, ref: ThermalReference, a, mesh: dict, lu,
                      refine_z: int) -> "ThermalROM":
        """Reuse an operator that has already been assembled and factorised.

        The trust guard builds A once for its solver cascade; re-assembling and
        re-factorising the same matrix here would be the bulk of the ROM's
        offline cost and would make the ROM-vs-exact comparison meaningless.
        """
        rom = cls.__new__(cls)
        rom.ref, rom.refine_z = ref, refine_z
        rom.nx, rom.ny = mesh["nx"], mesh["ny"]
        rom.a, rom.mesh, rom.lu = a, mesh, lu
        rom.n = mesh["nx"] * mesh["ny"] * mesh["nz"]
        rom.basis, rom._a_reduced = None, None
        return rom

    # -- loads ------------------------------------------------------------
    def rhs(self, p: HotspotParams) -> np.ndarray:
        """b(mu): the load vector for one parameter point."""
        total = sum(l.power_w for l in self.ref.layers)
        logic_i = int(np.argmax([l.power_w for l in self.ref.layers]))
        others = [i for i in range(len(self.ref.layers)) if i != logic_i]

        scaled = []
        for i, l in enumerate(self.ref.layers):
            if i == logic_i:
                w = total * p.logic_fraction
            elif others:
                rest = total * (1.0 - p.logic_fraction)
                share = l.power_w / max(sum(self.ref.layers[j].power_w
                                            for j in others), 1e-12)
                w = rest * share
            else:
                w = l.power_w
            scaled.append(Layer(l.name, l.thickness_m, l.k_w_mk, w, l.n_cells_z))

        shifted = ThermalReference(scaled, self.ref.width_m, self.ref.depth_m,
                                   self.ref.bc)
        _, b, _ = shifted.assemble(self.nx, self.ny, self.refine_z,
                                   hotspots={logic_i: (p.cx, p.cy,
                                                       p.radius_frac)})
        return b

    def solve_full(self, p: HotspotParams) -> np.ndarray:
        return self.lu.solve(self.rhs(p))

    # -- fit --------------------------------------------------------------
    def fit(self, params: list[HotspotParams], rank: int | None = None,
            energy: float = 1.0 - 1e-10) -> PODBasis:
        """Snapshots -> SVD -> leading modes -> project the operator."""
        return self.fit_rhs([self.rhs(p) for p in params], rank, energy)

    def fit_rhs(self, loads: list[np.ndarray], rank: int | None = None,
                energy: float = 1.0 - 1e-10) -> PODBasis:
        """The same fit from right-hand sides directly.

        Any load the solver accepts can parameterise the basis, not only the
        hotspot family: the trust guard builds its snapshots from the block
        layouts the optimiser searches, which is the distribution its ROM has
        to be accurate on.
        """
        x = np.column_stack([self.lu.solve(b) for b in loads])
        u, s, _ = np.linalg.svd(x, full_matrices=False)

        if rank is None:
            cumulative = np.cumsum(s ** 2) / np.sum(s ** 2)
            rank = int(np.searchsorted(cumulative, energy) + 1)
        rank = max(1, min(rank, u.shape[1]))

        self.basis = PODBasis(all_modes=u, singular_values=s, rank=rank)
        self._project_operator()
        self.snapshot_matrix_shape = x.shape
        return self.basis

    def _project_operator(self) -> None:
        m = self.basis.modes
        self._a_reduced = m.T @ (self.a @ m)

    def set_rank(self, rank: int) -> None:
        """Re-truncate without redoing the SVD. Can grow as well as shrink."""
        if self.basis is None:
            raise RuntimeError("fit() first")
        self.basis.rank = max(1, min(rank, self.basis.max_rank))
        self._project_operator()

    # -- reduced solve ----------------------------------------------------
    def solve_reduced(self, p: HotspotParams) -> np.ndarray:
        return self.solve_reduced_rhs(self.rhs(p))

    def solve_reduced_rhs(self, b: np.ndarray) -> np.ndarray:
        if self.basis is None:
            raise RuntimeError("fit() first")
        coeffs = np.linalg.solve(self._a_reduced, self.basis.modes.T @ b)
        return self.basis.modes @ coeffs

    def project(self, t_full: np.ndarray) -> np.ndarray:
        """U_r U_r^T T -- the best an r-mode basis can do for this field."""
        return self.basis.modes @ (self.basis.modes.T @ t_full)

    def as_field(self, flat: np.ndarray) -> np.ndarray:
        return flat.reshape(self.mesh["nz"], self.mesh["ny"], self.mesh["nx"])


# --- measurement ---------------------------------------------------------

def _errors(t_full: np.ndarray, t_approx: np.ndarray) -> dict:
    return {
        "relative_l2": float(np.linalg.norm(t_approx - t_full)
                             / np.linalg.norm(t_full)),
        "max_abs_c": float(np.max(np.abs(t_approx - t_full))),
        "peak_error_c": float(t_approx.max() - t_full.max()),
    }


def evaluate(rom: ThermalROM, test_params: list[HotspotParams]) -> dict:
    """Held-out accuracy: projection floor, ROM actual, and peak error."""
    proj, romerr, peaks, times_full, times_rom = [], [], [], [], []
    for p in test_params:
        t0 = time.perf_counter()
        t_full = rom.solve_full(p)
        times_full.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        t_rom = rom.solve_reduced(p)
        times_rom.append(time.perf_counter() - t0)

        proj.append(_errors(t_full, rom.project(t_full))["relative_l2"])
        e = _errors(t_full, t_rom)
        romerr.append(e["relative_l2"])
        peaks.append(e["peak_error_c"])

    return {
        "n_test": len(test_params),
        "projection_relative_l2": {"mean": float(np.mean(proj)),
                                   "max": float(np.max(proj))},
        "rom_relative_l2": {"mean": float(np.mean(romerr)),
                            "max": float(np.max(romerr))},
        "peak_error_c": {"mean_abs": float(np.mean(np.abs(peaks))),
                         "max_abs": float(np.max(np.abs(peaks))),
                         "signed_mean": float(np.mean(peaks))},
        "timing_s": {"full_solve_mean": float(np.mean(times_full)),
                     "reduced_solve_mean": float(np.mean(times_rom)),
                     "caveat": "internal ratio on this mesh and this hardware, "
                               "against this repo's own sparse solve. It is not "
                               "a speedup against any commercial tool."},
    }


def rank_sweep(rom: ThermalROM, test_params: list[HotspotParams],
               ranks: list[int]) -> list[dict]:
    """Truncation error as a function of retained modes."""
    original = rom.basis.rank
    out = []
    for r in ranks:
        if r > rom.basis.max_rank:
            continue
        rom.set_rank(r)
        res = evaluate(rom, test_params)
        out.append({"rank": r,
                    "retained_energy": rom.basis.retained_energy,
                    "projection_relative_l2_max": res["projection_relative_l2"]["max"],
                    "rom_relative_l2_max": res["rom_relative_l2"]["max"],
                    "peak_error_c_max_abs": res["peak_error_c"]["max_abs"]})
    rom.set_rank(original)
    return out


def build_reference() -> ThermalReference:
    """The 3DIC-X stack, from the same stackup the interchange layer emits."""
    stackup = REPO_ROOT / "physics_accelerated/results/golden_config.json"
    cfg = json.loads(stackup.read_text())
    vsp = cfg["voxel_stack_params"]
    k_map = dict(vsp["k_map"])
    k_map.update(cfg.get("packaging", {}).get("material_properties", {}))
    names = ["Die", "Hybrid_Bond", "Die", "C4_BGA", "Package"]
    thick = vsp["layer_thickness_um"]
    budget = float(cfg.get("max_power_budget_w", 60.0))
    # Power lives in the two active dies; the split is a ROM parameter.
    powers = [budget * 0.7, 0.0, budget * 0.3, 0.0, 0.0]
    layers = [Layer(n, thick[i] * 1e-6, k_map[n], powers[i], n_cells_z=2)
              for i, n in enumerate(names)]
    size = cfg["die_hierarchy"]["die_0"]["size_mm"]
    bc = Boundary(h_top_w_m2k=8000.0, h_bottom_w_m2k=50.0, h_side_w_m2k=0.0,
                  t_ambient_c=25.0)
    return ThermalReference(layers, size[0] * 1e-3, size[1] * 1e-3, bc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nx", type=int, default=32)
    ap.add_argument("--train", type=int, default=240)
    ap.add_argument("--test", type=int, default=32)
    ap.add_argument("--rank", type=int, default=240)
    ap.add_argument("--verify", action="store_true",
                    help="assert the ROM behaves and exit; write no report")
    args = ap.parse_args(argv)

    ref = build_reference()
    rom = ThermalROM(ref, nx=args.nx, ny=args.nx, refine_z=1)

    train = sample_params(args.train, seed=20260920)
    test = sample_params(args.test, seed=77)          # a separate stream

    t0 = time.perf_counter()
    basis = rom.fit(train, rank=min(args.rank, args.train))
    fit_s = time.perf_counter() - t0

    print(f"  mesh            : {rom.mesh['nx']}x{rom.mesh['ny']}x{rom.mesh['nz']} "
          f"= {rom.n} unknowns")
    print(f"  snapshots       : {args.train} train / {args.test} held-out")
    print(f"  POD rank        : {basis.rank} of {min(rom.n, args.train)} "
          f"(retained energy {basis.retained_energy:.10f})")
    print(f"  reduction       : {rom.n} -> {basis.rank} "
          f"({rom.n / basis.rank:.0f}x fewer unknowns)")
    print(f"  offline cost    : {fit_s:.2f} s for snapshots + SVD")

    res = evaluate(rom, test)
    print(f"\n  held-out accuracy at rank {basis.rank}:")
    print(f"    projection floor (best possible) : "
          f"{res['projection_relative_l2']['max']:.3e} relative L2 (max)")
    print(f"    ROM                              : "
          f"{res['rom_relative_l2']['max']:.3e} relative L2 (max)")
    print(f"    peak temperature error           : "
          f"{res['peak_error_c']['max_abs']:.4f} C (max abs), "
          f"{res['peak_error_c']['signed_mean']:+.4f} C (mean signed)")

    sweep = rank_sweep(rom, test, [1, 2, 4, 8, 16, 32, 64, 120, 180, 240])
    print("\n  truncation error vs retained modes:")
    print("    rank  retained energy   projection    ROM          peak err")
    for row in sweep:
        print(f"    {row['rank']:4d}  {row['retained_energy']:.12f}  "
              f"{row['projection_relative_l2_max']:.3e}  "
              f"{row['rom_relative_l2_max']:.3e}  "
              f"{row['peak_error_c_max_abs']:8.4f} C")

    # What a rank-32 basis looks like if you quote retained energy as accuracy.
    mid = next((r for r in sweep if r["rank"] == 32), None)
    if mid:
        print(f"\n  Retained energy is not accuracy: at rank {mid['rank']} the basis "
              f"holds {mid['retained_energy']*100:.4f}% of the snapshot energy while "
              f"the held-out peak temperature is still "
              f"{mid['peak_error_c_max_abs']:.2f} C out. Quote the truncation "
              f"error, never the energy fraction.")

    ok = True
    if res["rom_relative_l2"]["max"] > 3e-2:
        print(f"\n  ❌ ROM field error {res['rom_relative_l2']['max']:.3e} above the "
              f"3e-2 relative-L2 budget on held-out snapshots.")
        ok = False
    if res["peak_error_c"]["max_abs"] > 3.0:
        print(f"\n  ❌ Held-out peak error {res['peak_error_c']['max_abs']:.2f} C "
              f"above the 3 C budget.")
        ok = False
    falling = [a["rom_relative_l2_max"] >= b["rom_relative_l2_max"]
               for a, b in zip(sweep, sweep[1:])]
    if not all(falling):
        print("\n  ❌ Field error does not fall monotonically as modes are retained, "
              "which means the basis or the projection is wrong.")
        ok = False
    if not ok:
        return 1
    print("\n  ✅ ROM reproduces held-out snapshots; field error falls monotonically "
          "with rank.")

    if not args.verify:
        out = REPO_ROOT / "reports/thermal_rom_validation.json"
        out.write_text(json.dumps({
            "method": "POD-Galerkin on the reference solver's own operator",
            "note": "Truncation error is the reported quantity. The timing "
                    "ratio below is internal to this mesh and this hardware; "
                    "no commercial tool has been run.",
            "mesh": {"nx": rom.mesh["nx"], "ny": rom.mesh["ny"],
                     "nz": rom.mesh["nz"], "n_unknowns": rom.n},
            "snapshots": {"train": args.train, "test": args.test,
                          "test_seed_is_separate": True},
            "basis": {"rank": basis.rank,
                      "retained_energy": basis.retained_energy,
                      "singular_values": basis.singular_values[:32].tolist()},
            "offline_cost_s": fit_s,
            "held_out": res,
            "rank_sweep": sweep,
        }, indent=2) + "\n")
        print(f"  wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
