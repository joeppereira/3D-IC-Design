"""Surrogate trust guard: re-solve what the optimiser picked, and say when the
surrogate is being asked to extrapolate.

Why this exists
---------------
`reports/multiobjective_search.md` §5 measured the surrogate at three of the
designs the
search selects and found it **+8 to +40 K** wrong against the reference solver,
against a training-distribution RMSE of 2.03 K, always over-predicting. The
conclusion written there -- *"use the front for ranking, not absolute
temperatures; re-solve selected candidates before quoting a number"* -- was a
caveat a reader had to remember and act on by hand. This module does it
automatically, and adds the question the caveat did not answer: *why* is the
error at the optimum an order of magnitude larger than the training error?

Two mechanisms, and they need different fixes:

  * **Extrapolation.** The FNO was trained on `data_gen.py` power maps: random
    r=3 discs on the logic die and *single hot cells* on the memory die. The
    search evaluates four 2x2 sub-macro blocks plus a solid 4x4 memory block.
    Those are different distributions, and the guard measures how different --
    every design the optimiser can express is outside the training set.
  * **Discretisation.** The surrogate inherits the 16x16 mesh of its training
    labels, which over-predicts the peak against a 32x32 solve of the same
    problem. That part is not the network's fault and is not fixed by
    retraining.

The guard reports the split, because a reader who sees one number cannot tell
which fix applies.

The cascade
-----------
    tier 0  FNO surrogate                ~0.1 ms  the search's inner loop
    tier 1  reference solve, 32x32x10       ~2 ms   every design worth ranking
    tier 2  reference solve, 64x64x20      ~65 ms   the few designs to be quoted

The operator A is parameter-independent -- geometry and boundary conditions
only -- so each tier is assembled and factorised **once** and every design after
that is a back-substitution. That is what makes tier 1 cheap enough to run on an
entire Pareto front rather than on a sampled three.

On the POD ROM as a middle tier
-------------------------------
The open-issues list suggested re-ranking on the POD ROM from
`thermal_rom.py` and reserving full solves for the final few. Measured
(`--calibrate-screen`), that does not pay *at this mesh*: because A is
prefactorised, an exact solve is a 2 ms back-substitution, while a ROM accurate
enough to rank to <1 C needs a basis of ~300 snapshots -- 300 exact solves of
offline cost -- to then run at 1.5 ms. The break-even is above the number of
designs a front contains. The measurement is kept and reported rather than
asserted, because the conclusion flips at a mesh where factorisation is
infeasible: at tier 2 a solve is 65 ms and a reduced solve is still ~1.5 ms.

Run
---
    python trust_guard.py                    # audit the published front
    python trust_guard.py --calibrate-screen # ROM-vs-exact, the numbers above
    python trust_guard.py --verify           # assertions only, no report file
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.sparse.linalg as spla

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from thermal_reference import Boundary, Layer, ThermalReference     # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TRAINING_SET = REPO_ROOT / "serdes_architect/data/x_physics.pt"


# --- is this design one the surrogate was trained on? --------------------

FEATURE_NAMES = (
    "total_power_w",
    "logic_power_fraction",
    "logic_peak_to_mean",
    "logic_active_fraction",
    "logic_gyration_cells",
    "memory_peak_to_mean",
    "memory_active_fraction",
    "memory_gyration_cells",
)


def power_map_features(q: np.ndarray) -> np.ndarray:
    """Eight scalars describing *how the power is arranged*, not where.

    Position is deliberately excluded: the training set covers the die, so a
    hotspot in an unusual corner is not out of distribution, while a hotspot of
    an unusual *shape* is. Peak-to-mean and active fraction separate a solid
    block from a disc; the radius of gyration separates one blob from four.
    """
    q = np.asarray(q, dtype=float)
    total = float(q.sum())
    if total <= 0.0:
        raise ValueError("power map carries no power")
    out = [total, float(q[0].sum() / total)]
    for plane in (q[0], q[1]):
        s = float(plane.sum())
        if s <= 0.0:
            out.extend([0.0, 0.0, 0.0])
            continue
        w = plane / s
        ys, xs = np.mgrid[0:plane.shape[0], 0:plane.shape[1]]
        cy, cx = float((w * ys).sum()), float((w * xs).sum())
        out.append(float(plane.max() / (s / plane.size)))
        out.append(float((plane > 0.01 * plane.max()).mean()))
        out.append(float(np.sqrt((w * ((ys - cy) ** 2 + (xs - cx) ** 2)).sum())))
    return np.asarray(out, dtype=float)


@dataclass
class DistributionGuard:
    """Mahalanobis distance in feature space, calibrated on the training set.

    The threshold is conformal-style rather than chi-squared: the 99th
    percentile of the *training* distances, so by construction at most 1% of the
    data the surrogate was fitted on is flagged. No normality assumption is
    made about the features, and none holds -- `memory_active_fraction` on the
    training set is a spike at 1/256.
    """
    mean: np.ndarray
    std: np.ndarray
    inv_cov: np.ndarray
    threshold: float
    train_distances: np.ndarray = field(repr=False)
    n_train: int = 0

    @classmethod
    def fit(cls, train_maps: np.ndarray, quantile: float = 0.99,
            ridge: float = 1e-6) -> "DistributionGuard":
        f = np.asarray([power_map_features(m) for m in train_maps])
        mean, std = f.mean(axis=0), f.std(axis=0)
        std = np.where(std < 1e-12, 1.0, std)
        z = (f - mean) / std
        cov = np.cov(z.T) + ridge * np.eye(f.shape[1])
        inv_cov = np.linalg.inv(cov)
        d = np.sqrt(np.einsum("ij,jk,ik->i", z - 0.0, inv_cov, z - 0.0))
        return cls(mean=mean, std=std, inv_cov=inv_cov,
                   threshold=float(np.quantile(d, quantile)),
                   train_distances=d, n_train=len(f))

    def z_scores(self, maps: np.ndarray) -> np.ndarray:
        f = np.asarray([power_map_features(m) for m in maps])
        return (f - self.mean) / self.std

    def distance(self, maps: np.ndarray) -> np.ndarray:
        z = self.z_scores(maps)
        return np.sqrt(np.einsum("ij,jk,ik->i", z, self.inv_cov, z))

    def dominant_feature(self, one_map: np.ndarray) -> tuple[str, float]:
        z = self.z_scores([one_map])[0]
        i = int(np.argmax(np.abs(z)))
        return FEATURE_NAMES[i], float(z[i])


def load_training_maps(path: Path = TRAINING_SET) -> np.ndarray:
    import torch                       # local: the guard's maths needs no torch
    return torch.load(path).numpy()


# --- the solver tiers ----------------------------------------------------

def expand_power_map(power_map: np.ndarray, refine: int,
                     layer_of: np.ndarray) -> np.ndarray:
    """A [layers, G, G] design map onto the reference mesh's [nz, ny, nx] cells.

    Each coarse cell's watts are split evenly over the `refine^2` fine cells it
    becomes and over the z-cells of its layer, so total power is conserved
    exactly -- which the energy balance then checks.
    """
    q = np.asarray(power_map, dtype=float)
    f = int(refine)
    out = np.zeros((len(layer_of), q.shape[1] * f, q.shape[2] * f))
    for li in range(q.shape[0]):
        cells = np.where(layer_of == li)[0]
        if not len(cells):
            if q[li].any():
                raise ValueError(f"layer {li} carries power but has no mesh cells")
            continue
        up = np.repeat(np.repeat(q[li], f, axis=0), f, axis=1) / (f * f)
        for cz in cells:
            out[cz] = up / len(cells)
    return out


@dataclass
class MeshLevel:
    refine: int
    a: object
    b_boundary: np.ndarray
    mesh: dict
    lu: object
    assemble_s: float
    factorise_s: float

    @property
    def n(self) -> int:
        return self.a.shape[0]

    @property
    def shape(self) -> str:
        return f"{self.mesh['nx']}x{self.mesh['ny']}x{self.mesh['nz']}"


class ReferenceCascade:
    """Exact reference solves at several mesh levels, each factorised once."""

    def __init__(self, ref: ThermalReference, grid: int = 16):
        self.ref = ref
        self.grid = grid
        self._levels: dict[int, MeshLevel] = {}

    def level(self, refine: int) -> MeshLevel:
        if refine not in self._levels:
            n = self.grid * refine
            t0 = time.perf_counter()
            a, b, mesh = self.ref.assemble(n, n, refine)
            t_asm = time.perf_counter() - t0
            t0 = time.perf_counter()
            lu = spla.splu(a.tocsc())
            t_lu = time.perf_counter() - t0
            # b = boundary terms + this mesh's own load; subtracting the load
            # leaves the parameter-independent part, so every later design is
            # one vector add and one back-substitution.
            self._levels[refine] = MeshLevel(
                refine=refine, a=a, b_boundary=b - mesh["q"].reshape(-1),
                mesh=mesh, lu=lu, assemble_s=t_asm, factorise_s=t_lu)
        return self._levels[refine]

    def rhs(self, power_map: np.ndarray, refine: int) -> np.ndarray:
        lv = self.level(refine)
        q = expand_power_map(power_map, refine, lv.mesh["layer_of"])
        return lv.b_boundary + q.reshape(-1)

    def field(self, power_map: np.ndarray, refine: int) -> np.ndarray:
        lv = self.level(refine)
        t = lv.lu.solve(self.rhs(power_map, refine))
        return t.reshape(lv.mesh["nz"], lv.mesh["ny"], lv.mesh["nx"])

    def peak(self, power_map: np.ndarray, refine: int, layer: int = 0) -> float:
        return float(self.field(power_map, refine)[layer].max())

    def peaks(self, power_maps, refine: int, layer: int = 0) -> np.ndarray:
        return np.asarray([self.peak(m, refine, layer) for m in power_maps])


# --- the audit -----------------------------------------------------------

def _kendall_tau(a: np.ndarray, b: np.ndarray) -> float:
    """Rank agreement, written out rather than imported: the whole point of the
    guard is that it must run wherever the search runs."""
    n = len(a)
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = np.sign(a[i] - a[j]) * np.sign(b[i] - b[j])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    total = conc + disc
    return float((conc - disc) / total) if total else 1.0


def _stats(e: np.ndarray) -> dict:
    return {"mean_signed_k": float(e.mean()), "mean_abs_k": float(np.abs(e).mean()),
            "max_abs_k": float(np.abs(e).max()),
            "min_signed_k": float(e.min()), "max_signed_k": float(e.max())}


class SurrogateTrustGuard:
    """Ties the distribution flag and the solver cascade to one decision.

    `surrogate_peaks` is whatever the search believed. Everything the guard
    reports is measured against the same reference solver the rest of the
    project is verified with.
    """

    def __init__(self, cascade: ReferenceCascade, guard: DistributionGuard,
                 work_refine: int = 2, confirm_refine: int = 4):
        self.cascade = cascade
        self.guard = guard
        self.work_refine = work_refine
        self.confirm_refine = confirm_refine

    def audit(self, power_maps, surrogate_peaks: np.ndarray,
              top_k: int | None = None, confirm_k: int = 0,
              fdm_peaks: np.ndarray | None = None) -> dict:
        maps = [np.asarray(m, dtype=float) for m in power_maps]
        surrogate_peaks = np.asarray(surrogate_peaks, dtype=float)
        if len(maps) != len(surrogate_peaks):
            raise ValueError("one surrogate prediction per design is required")

        order = np.argsort(surrogate_peaks)           # coolest first
        sel = order if top_k is None else order[:max(1, top_k)]

        md = self.guard.distance(maps)
        flagged = md > self.guard.threshold

        # Warm the level first: assembly and factorisation are one-off costs
        # and are reported separately, so folding them into the per-design
        # timing would overstate what a re-solve costs.
        lv = self.cascade.level(self.work_refine)
        t0 = time.perf_counter()
        ref_peaks = self.cascade.peaks([maps[i] for i in sel], self.work_refine)
        t_resolve = time.perf_counter() - t0

        err = surrogate_peaks[sel] - ref_peaks

        designs = []
        for rank, i in enumerate(sel):
            feature, z = self.guard.dominant_feature(maps[i])
            designs.append({
                "index": int(i),
                "surrogate_rank": rank,
                "surrogate_peak_c": float(surrogate_peaks[i]),
                "reference_peak_c": float(ref_peaks[rank]),
                "surrogate_error_k": float(surrogate_peaks[i] - ref_peaks[rank]),
                "mahalanobis": float(md[i]),
                "in_distribution": bool(not flagged[i]),
                "dominant_feature": feature,
                "dominant_feature_z": z,
            })

        # Ranking is the property the front is actually used for.
        ref_order = np.argsort(ref_peaks)
        best_by_surrogate = 0                          # sel is sorted by surrogate
        regret = float(ref_peaks[best_by_surrogate] - ref_peaks[ref_order[0]])

        report = {
            "n_designs": len(maps),
            "n_resolved": int(len(sel)),
            "tier_1": {
                "mesh": lv.shape, "unknowns": lv.n,
                "assemble_s": lv.assemble_s, "factorise_s": lv.factorise_s,
                "ms_per_design": t_resolve / len(sel) * 1e3,
                "total_s": t_resolve,
            },
            "surrogate_error_vs_reference": _stats(err),
            "ranking": {
                "kendall_tau": _kendall_tau(surrogate_peaks[sel], ref_peaks),
                "selection_regret_c": regret,
                "note": ("regret is how much hotter the surrogate's own pick is "
                         "than the coolest design the reference solver finds, "
                         "in the set that was re-solved"),
            },
            "distribution_guard": {
                "training_set": str(TRAINING_SET.relative_to(REPO_ROOT)),
                "n_train": self.guard.n_train,
                "features": list(FEATURE_NAMES),
                "threshold_mahalanobis": self.guard.threshold,
                "train_distance": {
                    "mean": float(self.guard.train_distances.mean()),
                    "p99": float(np.quantile(self.guard.train_distances, 0.99)),
                    "max": float(self.guard.train_distances.max())},
                "audited_distance": {"min": float(md.min()),
                                     "max": float(md.max())},
                "flagged_fraction": float(flagged.mean()),
                "mean_z_by_feature": dict(zip(
                    FEATURE_NAMES,
                    (float(v) for v in self.guard.z_scores(maps).mean(axis=0)))),
            },
            "designs": designs,
        }

        if fdm_peaks is not None:
            # Split the error the way the fixes split. The training labels came
            # from the FDM solver on the 16x16 mesh, so:
            #   network      surrogate vs that solver, same mesh   -> retrain
            #   solver       that solver vs the reference, same mesh -> neither,
            #                and it is ~0, which is what makes the split valid
            #   discretisation  16x16 reference vs the working mesh -> re-solve
            # The three sum to the total by construction.
            fdm = np.asarray(fdm_peaks, dtype=float)[sel]
            coarse = self.cascade.peaks([maps[i] for i in sel], 1)
            report["error_budget_k"] = {
                "network_extrapolation": _stats(surrogate_peaks[sel] - fdm),
                "solver_agreement_same_mesh": _stats(fdm - coarse),
                "training_mesh_discretisation": _stats(coarse - ref_peaks),
                "total": _stats(err),
                "closes_to_k": float(np.abs(
                    (surrogate_peaks[sel] - fdm) + (fdm - coarse)
                    + (coarse - ref_peaks) - err).max()),
                "note": ("network_extrapolation is the surrogate against the "
                         "solver that produced its training labels, on the mesh "
                         "it was trained on; discretisation is that mesh against "
                         f"{lv.shape}. Retraining fixes only the first."),
            }

        if confirm_k > 0:
            report["tier_2"] = self._confirm(maps, sel, ref_peaks, confirm_k)
        return report

    def in_distribution_control(self, surrogate_fn, train_maps=None,
                                n: int = 32, seed: int = 5,
                                fdm_fn=None) -> dict:
        """The same measurement on designs the surrogate *was* trained on.

        Without it, "100% of the front is flagged" could equally mean the
        detector is broken. With it, the flag is calibrated: the same network
        checked the same way against the same solver.
        """
        maps = load_training_maps() if train_maps is None else train_maps
        idx = np.random.default_rng(seed).choice(len(maps), min(n, len(maps)),
                                                 replace=False)
        ctrl = np.asarray(maps)[idx]
        predicted = np.asarray(surrogate_fn(ctrl))
        err = predicted - self.cascade.peaks(ctrl, self.work_refine)
        d = self.guard.distance(ctrl)
        out = {
            "n": int(len(ctrl)),
            "source": "training maps, re-solved on the same reference mesh",
            "mahalanobis": {"min": float(d.min()), "max": float(d.max())},
            "flagged_fraction": float((d > self.guard.threshold).mean()),
            "surrogate_error_vs_reference": _stats(err),
        }
        if fdm_fn is not None:
            # The comparable term: the network against the solver that made its
            # labels, on the mesh it was trained on. Comparing the *total*
            # error in and out of distribution would credit the network with
            # discretisation error it did not cause.
            out["network_error_k"] = _stats(predicted
                                            - np.asarray(fdm_fn(ctrl)))
        return out

    def _confirm(self, maps, sel, ref_peaks, confirm_k: int) -> dict:
        """The few designs anyone would actually quote, on the finer mesh."""
        k = min(confirm_k, len(sel))
        picks = np.argsort(ref_peaks)[:k]
        lv = self.cascade.level(self.confirm_refine)
        t0 = time.perf_counter()
        fine = self.cascade.peaks([maps[sel[p]] for p in picks],
                                  self.confirm_refine)
        t_fine = time.perf_counter() - t0
        delta = ref_peaks[picks] - fine
        return {
            "mesh": lv.shape, "unknowns": lv.n,
            "assemble_s": lv.assemble_s, "factorise_s": lv.factorise_s,
            "ms_per_design": t_fine / k * 1e3,
            "designs": [{"index": int(sel[p]),
                         "reference_peak_c": float(ref_peaks[p]),
                         "refined_peak_c": float(fine[j]),
                         "discretisation_delta_c": float(delta[j])}
                        for j, p in enumerate(picks)],
            "max_abs_discretisation_delta_c": float(np.abs(delta).max()),
            "quotable_peak_c": float(fine.min()),
        }


# --- is a ROM screen worth it at this mesh? ------------------------------

def calibrate_screen(cascade: ReferenceCascade, sample_maps, refine: int = 2,
                     n_snapshots: int = 300, n_test: int = 40,
                     ranks=(8, 32, 64, 128, 200, 300)) -> dict:
    """POD-Galerkin ROM over the *search space*, measured against exact solves.

    The ROM in `thermal_rom.py` is parameterised by hotspot position; the
    optimiser's designs are block layouts, so the basis has to be built from
    snapshots of the space actually being searched. Same method, different
    loads: `fit_rhs` takes the right-hand sides directly.
    """
    from thermal_rom import ThermalROM

    lv = cascade.level(refine)
    maps = [np.asarray(m, dtype=float) for m in sample_maps]
    if len(maps) < n_snapshots + n_test:
        raise ValueError(f"need {n_snapshots + n_test} sample maps, got {len(maps)}")
    rhs = [cascade.rhs(m, refine) for m in maps[:n_snapshots + n_test]]

    t0 = time.perf_counter()
    exact = [lv.lu.solve(r) for r in rhs]
    t_exact = (time.perf_counter() - t0) / len(rhs)

    rom = ThermalROM.from_operator(cascade.ref, lv.a, lv.mesh, lv.lu, refine)

    t0 = time.perf_counter()
    rom.fit_rhs(rhs[:n_snapshots], rank=max(ranks))
    t_offline = time.perf_counter() - t0

    nz, ny, nx = lv.mesh["nz"], lv.mesh["ny"], lv.mesh["nx"]
    rows = []
    for rank in ranks:
        if rank > rom.basis.max_rank:
            continue
        rom.set_rank(rank)
        t0 = time.perf_counter()
        peak_err, rel = [], []
        for i in range(n_snapshots, n_snapshots + n_test):
            t = rom.solve_reduced_rhs(rhs[i])
            rel.append(float(np.linalg.norm(t - exact[i]) / np.linalg.norm(exact[i])))
            peak_err.append(float(t.reshape(nz, ny, nx)[0].max()
                                  - exact[i].reshape(nz, ny, nx)[0].max()))
        t_rom = (time.perf_counter() - t0) / n_test
        rows.append({"rank": rank,
                     "retained_energy": rom.basis.retained_energy,
                     "rom_relative_l2_max": float(np.max(rel)),
                     "peak_error_c_max_abs": float(np.max(np.abs(peak_err))),
                     "ms_per_design": t_rom * 1e3})
    good = [r for r in rows if r["peak_error_c_max_abs"] < 1.0]
    return {
        "mesh": lv.shape, "unknowns": lv.n,
        "exact_ms_per_design": t_exact * 1e3,
        "exact_factorise_s": lv.factorise_s,
        "offline_snapshots": n_snapshots,
        "offline_s": t_offline,
        "ranks": rows,
        "rank_for_1c": good[0]["rank"] if good else None,
        "verdict": ("exact solve" if not good or
                    good[0]["ms_per_design"] > t_exact * 1e3 * 0.5
                    else "rom screen"),
        "why": ("A is parameter-independent and prefactorised, so an exact solve "
                "is one back-substitution. A ROM only pays where that "
                "factorisation is unaffordable or where the number of designs "
                "far exceeds the snapshots its basis needs."),
    }


# --- CLI -----------------------------------------------------------------

def reference_from_solver(solver) -> ThermalReference:
    """The reference model of the stack the FDM solver is configured for.

    Same geometry, same conductivities, same boundary conditions, different
    discretisation and a direct solve -- which is what makes agreement between
    the two evidence rather than tautology.
    """
    layers = [Layer(m, float(solver.dz[i]), float(solver.k[i]), 0.0, n_cells_z=1)
              for i, m in enumerate(solver.layer_materials)]
    return ThermalReference(layers, solver.width_m, solver.depth_m,
                            Boundary(h_top_w_m2k=solver.h_top,
                                     h_bottom_w_m2k=solver.h_bottom,
                                     h_side_w_m2k=0.0,
                                     t_ambient_c=solver.t_ambient))


def build_context(config_path: Path):
    """The same reference model the rest of the physics reports are built on."""
    sys.path.insert(0, str(REPO_ROOT / "serdes_architect/src"))
    from thermal.solver import ThermalSolver
    solver = ThermalSolver(str(config_path))
    return solver, ReferenceCascade(reference_from_solver(solver))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config",
                    default=str(REPO_ROOT / "physics_accelerated/results/golden_config.json"))
    ap.add_argument("--front", default=str(REPO_ROOT / "reports/pareto_front_nsga2.json"))
    ap.add_argument("--model", default=str(REPO_ROOT / "physics_accelerated/results/fno_model_lam0p1.pt"))
    ap.add_argument("--stats", default=str(REPO_ROOT / "physics_accelerated/results/norm_stats.pt"))
    ap.add_argument("--top-k", type=int, default=0, help="0 = every design")
    ap.add_argument("--confirm-k", type=int, default=3)
    ap.add_argument("--calibrate-screen", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/surrogate_trust_report.json"))
    args = ap.parse_args(argv)

    import torch
    from pareto_search import build_power_maps, load_surrogate, GRID, SUB, N_SUB

    cfg = json.loads(Path(args.config).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    logic_w, mem_w = total_w * 0.75, total_w * 0.25
    layers = int(cfg["voxel_stack_params"]["layers"])

    solver, cascade = build_context(Path(args.config))
    train_maps = load_training_maps()
    dguard = DistributionGuard.fit(train_maps)
    tguard = SurrogateTrustGuard(cascade, dguard)

    model, mean, std = load_surrogate(args.model, args.stats, layers)

    def surrogate(maps: torch.Tensor) -> np.ndarray:
        with torch.no_grad():
            return (model(maps) * std + mean)[:, 0].amax(dim=(1, 2)).numpy()

    front = json.loads(Path(args.front).read_text())
    keys = front["genome_keys"]
    genomes = np.array([[g[k] for k in keys] for g in front["front_genomes"]])
    maps_t = build_power_maps(genomes, logic_w, mem_w, layers)
    maps = maps_t.numpy()

    report = tguard.audit(maps, surrogate(maps_t),
                          top_k=args.top_k or None,
                          confirm_k=args.confirm_k,
                          fdm_peaks=solver.solve_steady_state(maps_t)[:, 0]
                          .amax(dim=(1, 2)).numpy())

    # The in-distribution control, computed the same way the search computes
    # it, so the two reports cannot disagree.
    report["in_distribution_control"] = tguard.in_distribution_control(
        lambda m: surrogate(torch.from_numpy(np.asarray(m)).float()),
        train_maps=train_maps,
        fdm_fn=lambda m: solver.solve_steady_state(
            torch.from_numpy(np.asarray(m)).float())[:, 0]
        .amax(dim=(1, 2)).numpy())

    print_report(report)

    if args.calibrate_screen:
        rng = np.random.default_rng(1)
        sample = build_power_maps(
            rng.uniform(0, GRID - SUB, (340, 2 * N_SUB + 2)),
            logic_w, mem_w, layers).numpy()
        report["rom_screen_calibration"] = calibrate_screen(cascade, sample)
        print_screen(report["rom_screen_calibration"])

    ok = _assert_guard_behaves(report)
    if not args.verify:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


def print_report(r: dict) -> None:
    g = r["distribution_guard"]
    e = r["surrogate_error_vs_reference"]
    print(f"🛡  Surrogate trust guard: {r['n_resolved']} of {r['n_designs']} designs "
          f"re-solved on the reference ({r['tier_1']['mesh']}, "
          f"{r['tier_1']['ms_per_design']:.1f} ms each)")
    print(f"\n  surrogate vs reference : {e['min_signed_k']:+.2f} to "
          f"{e['max_signed_k']:+.2f} K (mean {e['mean_signed_k']:+.2f})")
    print(f"  ranking agreement      : Kendall tau {r['ranking']['kendall_tau']:.3f}, "
          f"selection regret {r['ranking']['selection_regret_c']:+.2f} C")
    print(f"  out of distribution    : {g['flagged_fraction']*100:.0f}% of designs "
          f"(Mahalanobis {g['audited_distance']['min']:.1f}-"
          f"{g['audited_distance']['max']:.1f} vs threshold {g['threshold_mahalanobis']:.1f})")
    worst = sorted(g["mean_z_by_feature"].items(), key=lambda kv: -abs(kv[1]))[:3]
    print("  furthest features      : " +
          ", ".join(f"{k} {v:+.1f}σ" for k, v in worst))
    if "in_distribution_control" in r:
        c = r["in_distribution_control"]
        print(f"  control (in-dist, n={c['n']}) : Mahalanobis "
              f"{c['mahalanobis']['min']:.1f}-{c['mahalanobis']['max']:.1f}, "
              f"surrogate error {c['surrogate_error_vs_reference']['mean_abs_k']:.2f} K "
              f"mean abs")
        if "network_error_k" in c and "error_budget_k" in r:
            here = r["error_budget_k"]["network_extrapolation"]["mean_abs_k"]
            there = c["network_error_k"]["mean_abs_k"]
            print(f"  network error, in-dist vs at the optimum: "
                  f"{there:.2f} K -> {here:.2f} K "
                  f"({here / there:.1f}x worse where the optimiser looks)")
    if "error_budget_k" in r:
        b = r["error_budget_k"]
        print(f"\n  error budget at the selected designs:")
        print(f"    network extrapolation      : "
              f"{b['network_extrapolation']['mean_signed_k']:+7.2f} K mean, "
              f"{b['network_extrapolation']['max_abs_k']:6.2f} K max")
        print(f"    training-mesh discretisation: "
              f"{b['training_mesh_discretisation']['mean_signed_k']:+7.2f} K mean, "
              f"{b['training_mesh_discretisation']['max_abs_k']:6.2f} K max")
        print(f"    total                      : {b['total']['mean_signed_k']:+7.2f} K mean, "
              f"{b['total']['max_abs_k']:6.2f} K max")
    print(f"\n  {'design':>8} {'surrogate':>10} {'reference':>10} {'error':>8} "
          f"{'MD':>7}  flag")
    for d in r["designs"][:6]:
        print(f"  {d['index']:8d} {d['surrogate_peak_c']:10.2f} "
              f"{d['reference_peak_c']:10.2f} {d['surrogate_error_k']:+8.2f} "
              f"{d['mahalanobis']:7.1f}  "
              f"{'ok' if d['in_distribution'] else 'EXTRAPOLATING'}")
    if len(r["designs"]) > 6:
        print(f"  ... and {len(r['designs']) - 6} more")
    if "tier_2" in r:
        t2 = r["tier_2"]
        print(f"\n  tier 2 ({t2['mesh']}, {t2['ms_per_design']:.0f} ms/design after a "
              f"{t2['factorise_s']:.1f} s factorisation):")
        for d in t2["designs"]:
            print(f"    design {d['index']:3d}: {d['reference_peak_c']:7.2f} C -> "
                  f"{d['refined_peak_c']:7.2f} C  "
                  f"({d['discretisation_delta_c']:+.2f} C discretisation)")
        print(f"    quotable peak Tj for the coolest design: "
              f"{t2['quotable_peak_c']:.2f} C")


def print_screen(c: dict) -> None:
    print(f"\n  ROM screen vs exact solve at {c['mesh']} ({c['unknowns']} unknowns):")
    print(f"    exact: {c['exact_ms_per_design']:.2f} ms/design after a "
          f"{c['exact_factorise_s']:.2f} s factorisation")
    print(f"    {'rank':>5} {'rel L2 max':>11} {'peak err max':>13} {'ms/design':>10}")
    for row in c["ranks"]:
        print(f"    {row['rank']:5d} {row['rom_relative_l2_max']:11.2e} "
              f"{row['peak_error_c_max_abs']:12.3f}C {row['ms_per_design']:10.2f}")
    print(f"    rank needed for <1 C: {c['rank_for_1c']} "
          f"(from {c['offline_snapshots']} snapshots, {c['offline_s']:.1f} s offline)")
    print(f"    verdict: {c['verdict']} -- {c['why']}")


def _assert_guard_behaves(r: dict) -> bool:
    """The guard is only useful if its own claims hold on this run."""
    ok = True
    g = r["distribution_guard"]
    c = r.get("in_distribution_control")
    if c and c["mahalanobis"]["max"] > g["threshold_mahalanobis"] * 1.5:
        print("\n  ❌ in-distribution control is itself flagged: the detector is "
              "not calibrated.")
        ok = False
    if c and c["surrogate_error_vs_reference"]["mean_abs_k"] >= \
            r["surrogate_error_vs_reference"]["mean_abs_k"]:
        print("\n  ❌ the surrogate is no worse at the flagged designs than at "
              "in-distribution ones, so the flag carries no information.")
        ok = False
    if r["ranking"]["selection_regret_c"] < -1e-9:
        print("\n  ❌ negative regret is impossible; the re-solve is inconsistent.")
        ok = False
    if ok:
        print("\n  ✅ guard calibrated: in-distribution designs pass, the "
              "optimiser's designs are flagged, and every reported temperature "
              "is a reference solve.")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
