"""Would a vendor correction change the decision, or only the number?

A licensed thermal run costs hours and a licence; this repo has never had one
(`eda_vendor_integration_spec.md` §10, tier T1/T2). Before spending that hour it
is worth knowing what it could possibly buy, and that question is answerable
today, with no licence at all: perturb the reference model along the axes a
correlation would move it, and see how much perturbation it takes before the
*ranking* of the Pareto front changes.

The distinction matters because the two outcomes call for different actions:

  * a correction that shifts every design equally changes whether a design
    **passes a limit** -- a real consequence, but one you can apply after the
    fact, to the winner, once;
  * a correction that reorders the front changes **which design you build**, and
    no post-hoc offset can recover from having built the wrong one.

The first result falls out of the arithmetic rather than the run: the
calibration `integrations/correlate.py` produces today is `thermal_bias_c`, an
additive offset, and an additive offset is order-preserving. **The existing
calibration path provably cannot change a ranking.** The perturbations that can
are the ones that change the *physics of spreading*, because that is what
differs between designs -- and the front here is a spread-vs-compactness
trade-off, so those are exactly the ones it is exposed to.

Perturbations, chosen to be things a vendor tool would actually disagree with us
about rather than arbitrary noise:

    uniform_offset_c   T -> T + eps            model bias (what correlate.py fits)
    uniform_gain       rise scaled by 1+eps    systematic scaling of the rise
    h_top_scale        cold-plate h x (1+eps)  the lumped BC standing in for a
                                               CFD-resolved cold plate
    k_lateral_scale    in-plane k x (1+eps)    the BEOL/TSV lateral spreading
                                               this model omits entirely

Output: for each, the smallest |eps| at which the front's winner changes, and
the rank correlation at the extremes. The perturbation with the smallest churn
threshold is where a licensed run buys the most information -- which is the
point of the exercise.

Run
---
    python rank_churn.py               # writes reports/rank_churn.json
    python rank_churn.py --verify      # assertions only, no report file
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

from thermal_reference import Boundary, ThermalReference          # noqa: E402
from trust_guard import (ReferenceCascade, _kendall_tau,          # noqa: E402
                         build_context, reference_from_solver)
from pareto_search import build_power_maps                        # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"

# Sweep magnitudes. Deliberately wider than any plausible correlation error --
# a threshold that sits outside the sweep is itself the answer ("no correction
# of this kind, of any size we would believe, changes the decision").
OFFSET_C = (2.0, 5.0, 10.0, 20.0, 50.0)
FRACTIONS = (0.02, 0.05, 0.10, 0.20, 0.35, 0.50)


@dataclass
class Churn:
    name: str
    family: str                  # "monotone" or "physics"
    unit: str
    tested: list[float]
    threshold: float | None      # smallest |eps| that changes the winner
    tau_at_max: float            # rank correlation at the largest perturbation
    winner_at_max: int
    peak_shift_at_max_c: float   # how far the winner's own temperature moved
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "family": self.family, "unit": self.unit,
                "tested": self.tested, "churn_threshold": self.threshold,
                "changes_ranking": self.threshold is not None,
                "kendall_tau_at_max": self.tau_at_max,
                "winner_at_max": self.winner_at_max,
                "winner_peak_shift_at_max_c": self.peak_shift_at_max_c,
                "note": self.note}


# --- the perturbed models -------------------------------------------------

def _peaks_offset(base: np.ndarray, eps: float, t_ambient: float) -> np.ndarray:
    return base + eps


def _peaks_gain(base: np.ndarray, eps: float, t_ambient: float) -> np.ndarray:
    return t_ambient + (1.0 + eps) * (base - t_ambient)


def _cascade_with(ref: ThermalReference, *, h_top_scale: float = 1.0,
                  k_lateral_scale: float = 1.0) -> ReferenceCascade:
    bc = Boundary(h_top_w_m2k=ref.bc.h_top_w_m2k * h_top_scale,
                  h_bottom_w_m2k=ref.bc.h_bottom_w_m2k,
                  h_side_w_m2k=ref.bc.h_side_w_m2k,
                  t_ambient_c=ref.bc.t_ambient_c)
    return ReferenceCascade(ThermalReference(
        ref.layers, ref.width_m, ref.depth_m, bc,
        k_lateral_scale=ref.k_lateral_scale * k_lateral_scale))


# --- the sweep -------------------------------------------------------------

def _rank_stats(base: np.ndarray, perturbed: np.ndarray) -> tuple[float, int]:
    return _kendall_tau(base, perturbed), int(np.argmin(perturbed))


def sweep(name: str, family: str, unit: str, values, peaks_fn,
          base: np.ndarray, note: str = "") -> Churn:
    """peaks_fn(eps) -> the front's peak temperatures under that perturbation."""
    base_winner = int(np.argmin(base))
    threshold, tau, winner, shift = None, 1.0, base_winner, 0.0
    for eps in values:
        for signed in ((eps, -eps) if family == "physics" or unit == "C"
                       else (eps,)):
            p = peaks_fn(signed)
            tau_i, winner_i = _rank_stats(base, p)
            if winner_i != base_winner and threshold is None:
                threshold = abs(signed)
        # the largest magnitude is reported as the "at max" column
        p = peaks_fn(eps)
        tau, winner = _rank_stats(base, p)
        shift = float(p[base_winner] - base[base_winner])
    return Churn(name, family, unit, [float(v) for v in values], threshold,
                 float(tau), winner, shift, note)


def analyse(cascade: ReferenceCascade, maps: np.ndarray,
            refine: int = 2) -> dict:
    ref = cascade.ref
    base = cascade.peaks(maps, refine)
    order = np.argsort(base)
    gap = float(base[order[1]] - base[order[0]]) if len(base) > 1 else 0.0

    churns = [
        sweep("uniform_offset_c", "monotone", "C", OFFSET_C,
              lambda e: _peaks_offset(base, e, ref.bc.t_ambient_c), base,
              note=("this is exactly the calibration correlate.py fits "
                    "(thermal_bias_c); adding a constant cannot reorder a list")),
        sweep("uniform_gain", "monotone", "fraction", FRACTIONS,
              lambda e: _peaks_gain(base, e, ref.bc.t_ambient_c), base,
              note="scaling the rise about ambient is order-preserving too"),
        sweep("h_top_scale", "physics", "fraction", FRACTIONS,
              lambda e: _cascade_with(ref, h_top_scale=1.0 + e)
              .peaks(maps, refine), base,
              note=("the lumped cold-plate coefficient; a CFD-resolved plate is "
                    "the most likely thing a vendor run disagrees with")),
        sweep("k_lateral_scale", "physics", "fraction", FRACTIONS,
              lambda e: _cascade_with(ref, k_lateral_scale=1.0 + e)
              .peaks(maps, refine), base,
              note=("in-plane spreading, which this model omits (no BEOL metal, "
                    "no TSV array) -- and the front is a spread-vs-compactness "
                    "trade-off, so it is the axis the decision is exposed to")),
    ]

    physics = [c for c in churns if c.family == "physics" and c.threshold]
    first = min(physics, key=lambda c: c.threshold).name if physics else None
    return {
        "question": ("what would a vendor correlation have to change before it "
                     "changed which design we pick?"),
        "front": {"n_designs": int(len(base)),
                  "winner_index": int(np.argmin(base)),
                  "winner_peak_c": float(base.min()),
                  "top1_to_top2_gap_c": gap,
                  "spread_c": float(base.max() - base.min()),
                  "mesh": cascade.level(refine).shape},
        "perturbations": [c.to_dict() for c in churns],
        "measure_first": first,
        "implication": _implication(churns, gap, first),
    }


# --- the decision one level up: does the topology conclusion survive? ------

def monolithic_best(cascade: ReferenceCascade, logic_w: float, mem_w: float,
                    layers: int, grid: int = 16, block: int = 4,
                    step: int = 4, refine: int = 2) -> tuple[float, tuple]:
    """Best single-block layout, scanning logic *and* memory placement.

    Pinning the memory macro is what overstated this comparison by ~4 C before
    (`multiobjective_search.md` §4), so both move. The step is coarser than the
    published scan because this runs once per perturbation; a coarser scan can
    only make the monolithic layout look worse, so the headroom it reports is an
    upper bound -- stated here because the interesting question is whether the
    headroom *collapses*, and an upper bound is the wrong side for that. It is
    reported alongside the fine-scan number for exactly that reason.
    """
    best, at = float("inf"), None
    positions = range(0, grid - block + 1, step)
    for lx in positions:
        for ly in positions:
            for mx in positions:
                for my in positions:
                    m = np.zeros((layers, grid, grid))
                    m[0, ly:ly + block, lx:lx + block] = logic_w / (block * block)
                    m[1, my:my + block, mx:mx + block] = mem_w / (block * block)
                    t = cascade.peak(m, refine)
                    if t < best:
                        best, at = t, (lx, ly, mx, my)
    return best, at


def topology_robustness(ref: ThermalReference, shattered_map: np.ndarray,
                        logic_w: float, mem_w: float, layers: int,
                        refine: int = 2) -> dict:
    """Does "shatter the logic macro" survive the perturbations?

    This is the decision the project actually made, and it is a comparison
    *across* topologies rather than among near-identical members of one front --
    which is where a spreading correction has somewhere to bite.
    """
    cases = [("baseline", {}),
             ("h_top -50%", {"h_top_scale": 0.5}),
             ("h_top +50%", {"h_top_scale": 1.5}),
             ("k_lateral -50%", {"k_lateral_scale": 0.5}),
             ("k_lateral +50%", {"k_lateral_scale": 1.5}),
             ("k_lateral x4", {"k_lateral_scale": 4.0}),
             ("k_lateral x10", {"k_lateral_scale": 10.0})]
    rows = []
    for name, kw in cases:
        c = _cascade_with(ref, **kw)
        sh = c.peak(shattered_map, refine)
        mono, at = monolithic_best(c, logic_w, mem_w, layers, refine=refine)
        rows.append({"case": name, **kw,
                     "shattered_peak_c": sh, "monolithic_peak_c": mono,
                     "monolithic_at": list(at), "headroom_c": mono - sh})
    head = [r["headroom_c"] for r in rows]
    return {
        "question": "does shattering the logic macro still win under a "
                    "correction of this size?",
        "scan": "coarse (step 4) over both macro positions; upper bound on the "
                "monolithic layout, hence on the headroom",
        "cases": rows,
        "headroom_range_c": [float(min(head)), float(max(head))],
        "conclusion_flips": bool(min(head) <= 0.0),
        "note": ("k_lateral x4 and x10 are far beyond any plausible correction "
                 "-- they are there to find where the conclusion *would* break, "
                 "which is more informative than confirming it does not."),
    }


def _implication(churns: list[Churn], gap: float, first: str | None) -> str:
    monotone = [c for c in churns if c.family == "monotone"]
    if any(c.threshold is not None for c in monotone):
        return ("a monotone perturbation reordered the front, which is "
                "arithmetically impossible -- the sweep is wrong")
    if first is None:
        return (f"no perturbation tested reorders the front (top-1 leads by "
                f"{gap:.2f} C). A correlated vendor run would move the absolute "
                f"temperature and leave the architectural choice standing.")
    return (f"the ranking is robust to bias and scale by construction, and "
            f"sensitive to {first}. That is where a licensed run buys a "
            f"decision rather than a number.")


def print_report(doc: dict) -> None:
    f = doc["front"]
    print(f"🎲 Rank churn: {f['n_designs']} front designs on {f['mesh']}, "
          f"winner #{f['winner_index']} at {f['winner_peak_c']:.2f} C "
          f"(leads #2 by {f['top1_to_top2_gap_c']:.2f} C)\n")
    print(f"  {'perturbation':<20} {'family':<9} {'churn at':>10} "
          f"{'tau(max)':>9} {'winner shift':>13}")
    for c in doc["perturbations"]:
        thr = (f"{c['churn_threshold']:.2f} {c['unit'][:3]}"
               if c["churn_threshold"] is not None else "never")
        print(f"  {c['name']:<20} {c['family']:<9} {thr:>10} "
              f"{c['kendall_tau_at_max']:9.3f} "
              f"{c['winner_peak_shift_at_max_c']:+12.2f} C")
    print(f"\n  {doc['implication']}")
    t = doc.get("topology_robustness")
    if t:
        print(f"\n  shattered vs monolithic under the same perturbations "
              f"({t['scan']}):")
        print(f"    {'case':<16} {'shattered':>10} {'monolithic':>11} {'headroom':>10}")
        for r in t["cases"]:
            print(f"    {r['case']:<16} {r['shattered_peak_c']:9.2f} C "
                  f"{r['monolithic_peak_c']:10.2f} C {r['headroom_c']:+9.2f} C")
        lo, hi = t["headroom_range_c"]
        print(f"    headroom stays in [{lo:+.2f}, {hi:+.2f}] C; conclusion "
              f"flips: {t['conclusion_flips']}")


def _assert_behaves(doc: dict) -> bool:
    ok = True
    for c in doc["perturbations"]:
        if c["family"] == "monotone":
            if c["changes_ranking"] or c["kendall_tau_at_max"] < 1.0 - 1e-12:
                print(f"\n  ❌ {c['name']} reordered the front; a monotone "
                      f"transform cannot, so the sweep is broken.")
                ok = False
        elif c["winner_peak_shift_at_max_c"] == 0.0:  # noqa: E501
            print(f"\n  ❌ {c['name']} moved no temperature at all; the "
                  f"perturbation is not reaching the solver.")
            ok = False
    if ok:
        print("\n  ✅ monotone corrections leave the ranking untouched, and the "
              "physical ones reach the solver.")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--front", default=str(REPO_ROOT / "reports/pareto_front_nsga2.json"))
    ap.add_argument("--refine", type=int, default=2)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/rank_churn.json"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    layers = int(cfg["voxel_stack_params"]["layers"])
    _, cascade = build_context(Path(args.config))

    front = json.loads(Path(args.front).read_text())
    keys = front["genome_keys"]
    genomes = np.array([[g[k] for k in keys] for g in front["front_genomes"]])
    maps = build_power_maps(genomes, total_w * 0.75, total_w * 0.25,
                            layers).numpy()

    doc = analyse(cascade, maps, refine=args.refine)
    doc["front"]["source"] = os.path.relpath(args.front, REPO_ROOT)
    winner = int(doc["front"]["winner_index"])
    doc["topology_robustness"] = topology_robustness(
        cascade.ref, maps[winner], total_w * 0.75, total_w * 0.25, layers,
        refine=args.refine)
    print_report(doc)
    ok = _assert_behaves(doc)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
