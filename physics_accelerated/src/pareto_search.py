"""Multi-objective shattered-macro floorplan search over the thermal surrogate.

The search variable is the placement of N logic sub-macros plus the memory
block -- the "shattered macro" topology the project claims recovers thermal
headroom. With 4 sub-macros that is a 10-dimensional problem, which is where
dominance-based search starts to matter; an earlier 4-variable version was small
enough that random sampling nearly matched NSGA-II.

Three objectives that genuinely conflict:

    logic peak Tj      minimise -- spreading the sub-macros cools the logic
    memory peak Tj     minimise -- but heat dumped near the memory die hurts it,
                                   and DRAM/SRAM has a far lower Tj limit
    interconnect span  minimise -- spreading anything costs latency and energy

An earlier objective set used thermal spread (max - mean), which turned out to be
almost perfectly correlated with peak Tj -- a redundant objective that inflates
the apparent front without adding information.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import FNO2d                       # noqa: E402
from pareto import nsga2, random_search, hypervolume, pareto_front  # noqa: E402

GRID = 16
BLOCK = 4                 # monolithic logic block footprint
SUB = 2                   # shattered sub-macro footprint
N_SUB = 4                 # number of logic sub-macros
# Two objectives, deliberately. Logic peak and memory peak turned out to track
# each other to within ~0.5 K, because a 5 um Cu-Cu bond at k=300 W/mK couples
# the dies tightly -- a redundant objective inflates the front without adding
# information. Memory dT is reported as a diagnostic, not optimised.
OBJECTIVES = ("logic_peak_tj_c", "interconnect_span_cells")
GENOME_KEYS = [f"{a}{i}" for i in range(N_SUB) for a in ("x", "y")] + ["mx", "my"]


def load_surrogate(model_path: str, stats_path: str, layers: int = 5):
    model = FNO2d(modes1=8, modes2=8, width=32, layers=layers)
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    model.eval()
    stats = torch.load(stats_path, map_location="cpu")
    return model, float(stats["mean"]), float(stats["std"])


def build_power_maps(genomes: np.ndarray, logic_w: float, mem_w: float,
                     layers: int = 5) -> torch.Tensor:
    """Genome is (x,y) per logic sub-macro then (mx,my) for the memory block."""
    n = len(genomes)
    maps = torch.zeros((n, layers, GRID, GRID))
    per_sub = logic_w / N_SUB
    sub_cells = SUB * SUB
    mem_cells = BLOCK * BLOCK
    for i, g in enumerate(genomes):
        for s_ in range(N_SUB):
            x = int(np.clip(round(g[2 * s_]), 0, GRID - SUB))
            y = int(np.clip(round(g[2 * s_ + 1]), 0, GRID - SUB))
            maps[i, 0, y:y + SUB, x:x + SUB] += per_sub / sub_cells
        mx = int(np.clip(round(g[2 * N_SUB]), 0, GRID - BLOCK))
        my = int(np.clip(round(g[2 * N_SUB + 1]), 0, GRID - BLOCK))
        maps[i, 1, my:my + BLOCK, mx:mx + BLOCK] = mem_w / mem_cells
    return maps


def monolithic_power_map(logic_w: float, mem_w: float, layers: int,
                         lx: int, ly: int, mx: int, my: int) -> torch.Tensor:
    """One solid logic block, for the shattered-vs-monolithic comparison."""
    maps = torch.zeros((1, layers, GRID, GRID))
    maps[0, 0, ly:ly + BLOCK, lx:lx + BLOCK] = logic_w / (BLOCK * BLOCK)
    maps[0, 1, my:my + BLOCK, mx:mx + BLOCK] = mem_w / (BLOCK * BLOCK)
    return maps


def surrogate_peaks(model, mean, std, maps) -> np.ndarray:
    """Predicted logic-die peak temperature for already-built power maps."""
    t = maps if torch.is_tensor(maps) else torch.from_numpy(np.asarray(maps)).float()
    with torch.no_grad():
        return ((model(t) * std + mean)[:, 0].amax(dim=(1, 2))).numpy()


def make_evaluator(model, mean, std, logic_w, mem_w, layers=5, counter=None):
    def evaluate(genomes: np.ndarray) -> np.ndarray:
        maps = build_power_maps(genomes, logic_w, mem_w, layers)
        with torch.no_grad():
            t = model(maps) * std + mean
        logic_peak = t[:, 0].amax(dim=(1, 2)).numpy()
        # Total interconnect: sub-macro spread plus the hop to the memory block.
        span = []
        for g in genomes:
            pts = [(g[2 * s_], g[2 * s_ + 1]) for s_ in range(N_SUB)]
            cx = sum(p[0] for p in pts) / N_SUB
            cy = sum(p[1] for p in pts) / N_SUB
            internal = sum(abs(p[0] - cx) + abs(p[1] - cy) for p in pts)
            to_mem = abs(cx - g[2 * N_SUB]) + abs(cy - g[2 * N_SUB + 1])
            span.append(internal + to_mem)
        if counter is not None:
            counter[0] += len(genomes)
        return np.stack([logic_peak, np.asarray(span)], axis=1)
    return evaluate


def run_trust_guard(genomes: np.ndarray, surrogate_peaks: np.ndarray, args,
                    logic_w: float, mem_w: float, layers: int,
                    surrogate_fn=None) -> dict:
    """Re-solve what the search selected, before any of it is published.

    The surrogate is 8-47 K optimistic at these designs and every one of them is
    outside its training distribution -- see reports/surrogate_trust_report.json
    for the measurement. The search therefore does not get to publish a
    temperature it predicted itself.
    """
    from trust_guard import (DistributionGuard, SurrogateTrustGuard,   # noqa: E402
                             build_context, load_training_maps, print_report)

    solver, cascade = build_context(Path(args.config))
    guard = SurrogateTrustGuard(cascade,
                                DistributionGuard.fit(load_training_maps()))
    maps = build_power_maps(genomes, logic_w, mem_w, layers)
    fdm = solver.solve_steady_state(maps)[:, 0].amax(dim=(1, 2)).numpy()

    print()
    report = guard.audit(maps.numpy(), surrogate_peaks,
                         top_k=args.trust_k or None,
                         confirm_k=args.confirm_k, fdm_peaks=fdm)
    if surrogate_fn is not None:
        report["in_distribution_control"] = guard.in_distribution_control(
            surrogate_fn,
            fdm_fn=lambda m: solver.solve_steady_state(
                torch.from_numpy(np.asarray(m)).float())[:, 0]
            .amax(dim=(1, 2)).numpy())
    print_report(report)
    out = Path(args.out) / "surrogate_trust_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"  wrote {out}")
    return report


def _front_entry(row: np.ndarray, trust: dict | None, i: int) -> dict:
    """One published front member: the surrogate's objectives, plus the
    reference temperature for the members the guard re-solved."""
    entry = dict(zip(OBJECTIVES, map(float, row)))
    if trust is None:
        return entry
    checked = {d["index"]: d for d in trust["designs"]}
    d = checked.get(i)
    if d is None:
        return entry                 # outside --trust-k; surrogate only
    entry["reference_peak_tj_c"] = d["reference_peak_c"]
    entry["surrogate_error_k"] = d["surrogate_error_k"]
    entry["in_training_distribution"] = d["in_distribution"]
    return entry


def _trust_summary(trust: dict) -> dict:
    t2 = trust.get("tier_2", {})
    return {
        "report": "reports/surrogate_trust_report.json",
        "resolved_on_reference": trust["n_resolved"],
        "of_designs": trust["n_designs"],
        "mesh": trust["tier_1"]["mesh"],
        "surrogate_error_vs_reference_k": trust["surrogate_error_vs_reference"],
        "ranking": trust["ranking"],
        "out_of_distribution_fraction":
            trust["distribution_guard"]["flagged_fraction"],
        "refined_confirmation": {
            "mesh": t2.get("mesh"),
            "quotable_peak_c": t2.get("quotable_peak_c"),
            "max_abs_discretisation_delta_c":
                t2.get("max_abs_discretisation_delta_c"),
        } if t2 else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="results/fno_model_lam0p1.pt")
    ap.add_argument("--stats", default="results/norm_stats.pt")
    ap.add_argument("--config", default="results/golden_config.json")
    ap.add_argument("--pop", type=int, default=48)
    ap.add_argument("--generations", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="../reports")
    ap.add_argument("--trust-k", type=int, default=0,
                    help="re-solve the k coolest front members on the reference "
                         "solver; 0 means the whole front")
    ap.add_argument("--confirm-k", type=int, default=3,
                    help="of those, how many to re-solve again on the refined "
                         "mesh; 0 skips the refined tier")
    ap.add_argument("--no-trust-guard", action="store_true",
                    help="publish surrogate predictions unchecked (not advised: "
                         "they are 8-47 K optimistic at these designs)")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    logic_w, mem_w = total_w * 0.75, total_w * 0.25
    layers = int(cfg["voxel_stack_params"]["layers"])

    model, mean, std = load_surrogate(args.model, args.stats, layers)
    evaluate = make_evaluator(model, mean, std, logic_w, mem_w, layers)

    n_vars = 2 * N_SUB + 2
    lo = np.zeros(n_vars)
    hi = np.concatenate([np.full(2 * N_SUB, GRID - SUB), np.full(2, GRID - BLOCK)])
    # Reference point for hypervolume: a shared, pessimistic corner so both
    # searches are measured on exactly the same box.
    probe = evaluate(lo + np.random.default_rng(99).random((2000, n_vars)) * (hi - lo))
    # Fixed box, shared by both searches and every generation.
    reference = probe.max(axis=0) * 1.02
    ideal = np.minimum(probe.min(axis=0) * 0.98, probe.min(axis=0) - 1e-9)

    print(f"🔍 NSGA-II shattered-macro search: {N_SUB} logic sub-macros + memory, "
          f"{n_vars} variables")
    print(f"   power: {logic_w:.1f} W logic / {mem_w:.1f} W memory")
    nsga = nsga2(evaluate, lo, hi, pop_size=args.pop,
                 generations=args.generations, seed=args.seed,
                 reference=reference, ideal=ideal)
    rand = random_search(evaluate, lo, hi, evaluations=nsga.evaluations,
                         seed=args.seed, reference=reference, ideal=ideal)

    hv_n = hypervolume(nsga.objectives, reference, ideal)
    hv_r = hypervolume(rand.objectives, reference, ideal)
    print(f"  evaluations (both) : {nsga.evaluations}")
    print(f"  NSGA-II hypervolume: {hv_n:.4f}   front size {len(nsga.front_index)}")
    print(f"  random  hypervolume: {hv_r:.4f}   front size {len(rand.front_index)}")
    print(f"  improvement        : {(hv_n / hv_r - 1) * 100:+.1f}%" if hv_r else "")
    print(f"  HV first -> last gen: {nsga.history[0]:.4f} -> {nsga.history[-1]:.4f}")

    front = nsga.front
    order = np.argsort(front[:, 0])
    print(f"\n  Pareto front ({len(front)} non-dominated designs), by peak Tj:")
    print(f"    {'logic Tj':>9} {'span':>7}")
    for row in front[order][:8]:
        print(f"    {row[0]:9.2f} {row[1]:7.1f}")
    if len(front) > 8:
        print(f"    ... and {len(front) - 8} more")

    # --- does shattering actually help? Same optimiser, same budget. -------
    # The earlier version compared an NSGA-II-optimised shattered layout against
    # a coarse grid scan of monolithic layouts with the memory block pinned,
    # which is not a fair comparison.
    def monolithic_eval(genomes):
        maps = torch.zeros((len(genomes), layers, GRID, GRID))
        for i, g in enumerate(genomes):
            lx = int(np.clip(round(g[0]), 0, GRID - BLOCK))
            ly = int(np.clip(round(g[1]), 0, GRID - BLOCK))
            mx = int(np.clip(round(g[2]), 0, GRID - BLOCK))
            my = int(np.clip(round(g[3]), 0, GRID - BLOCK))
            maps[i, 0, ly:ly + BLOCK, lx:lx + BLOCK] = logic_w / (BLOCK * BLOCK)
            maps[i, 1, my:my + BLOCK, mx:mx + BLOCK] = mem_w / (BLOCK * BLOCK)
        with torch.no_grad():
            t = model(maps) * std + mean
        peak = t[:, 0].amax(dim=(1, 2)).numpy()
        span = np.array([abs(g[0] - g[2]) + abs(g[1] - g[3]) for g in genomes])
        return np.stack([peak, span], axis=1)

    mono_lo, mono_hi = np.zeros(4), np.full(4, GRID - BLOCK)
    mono = nsga2(monolithic_eval, mono_lo, mono_hi, pop_size=args.pop,
                 generations=args.generations, seed=args.seed)
    best_mono = float(mono.front[:, 0].min())
    best_shattered = float(front[:, 0].min())
    print(f"\n  Shattered vs monolithic logic, identical power and optimiser:")
    print(f"    monolithic (1 x 4x4 block)  best logic peak Tj : {best_mono:8.2f} C")
    print(f"    shattered  ({N_SUB} x {SUB}x{SUB} blocks) best logic peak Tj : "
          f"{best_shattered:8.2f} C")
    print(f"    headroom recovered by shattering : {best_mono - best_shattered:+.2f} C")
    print(f"    (both {mono.evaluations} evaluations; same power density per cell)")

    # --- trust guard: nothing here is published as a temperature until the
    # reference solver has seen it. ---------------------------------------
    front_genomes = nsga.genomes[nsga.front_index][order]
    front_sorted = front[order]
    trust = None
    if not args.no_trust_guard:
        # front_genomes and the objectives must be in the same order: passing
        # the unsorted objectives alongside sorted genomes pairs each design
        # with another design's prediction, which shows up as a Kendall tau
        # near zero rather than as an error.
        trust = run_trust_guard(front_genomes, front_sorted[:, 0], args,
                                logic_w, mem_w, layers,
                                surrogate_fn=lambda m: surrogate_peaks(model, mean,
                                                                       std, m))

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    doc = {
        "method": "NSGA-II (non-dominated sorting + crowding, SBX, polynomial mutation)",
        "objectives": list(OBJECTIVES),
        "all_minimised": True,
        "surrogate": args.model,
        "evaluations": int(nsga.evaluations),
        "population": args.pop,
        "generations": args.generations,
        "reference_point": reference.tolist(),
        "hypervolume": {"nsga2": hv_n, "random_search": hv_r,
                        "improvement_pct": (hv_n / hv_r - 1) * 100 if hv_r else None},
        "hypervolume_history": nsga.history,
        "front": [_front_entry(row, trust, i)
                  for i, row in enumerate(front_sorted)],
        # Key names must cover every variable: zipping against a 4-name tuple
        # silently truncated a 10-variable genome, so the published front could
        # not be reproduced from its own JSON.
        "genome_keys": GENOME_KEYS,
        "front_genomes": [dict(zip(GENOME_KEYS, map(float, g)))
                          for g in nsga.genomes[nsga.front_index][order]],
        "shattered_vs_monolithic": {
            "best_monolithic_logic_peak_c": best_mono,
            "best_shattered_logic_peak_c": best_shattered,
            "headroom_recovered_c": best_mono - best_shattered,
            "evaluations_each": int(mono.evaluations),
            "method": "both optimised with NSGA-II at identical budget",
        },
        "note": ("Objectives are surrogate predictions. Every front member also "
                 "carries reference_peak_tj_c, solved on the grid-converged "
                 "reference solver by the trust guard -- quote that one."),
    }
    if trust is not None:
        doc["trust_guard"] = _trust_summary(trust)
    (outdir / "pareto_front_nsga2.json").write_text(json.dumps(doc, indent=2) + "\n")
    with open(outdir / "pareto_front_nsga2.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        # The header used to name four variables (lx, ly, mx, my) for a
        # ten-variable genome, so every row was six columns wider than its
        # header -- the same defect class as the truncated genome_keys above.
        w.writerow(list(OBJECTIVES) + ["reference_peak_tj_c"] + GENOME_KEYS)
        for i, (row, g) in enumerate(zip(front_sorted, front_genomes)):
            ref_c = doc["front"][i].get("reference_peak_tj_c")
            w.writerow([f"{v:.4f}" for v in row]
                       + [f"{ref_c:.4f}" if ref_c is not None else ""]
                       + [int(round(x)) for x in g])
    print(f"\n  wrote {outdir}/pareto_front_nsga2.json and .csv")


if __name__ == "__main__":
    main()
