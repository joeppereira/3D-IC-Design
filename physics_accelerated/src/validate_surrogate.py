"""Validate the surrogate and the Pareto winners against the reference solver.

Training RMSE measures the surrogate on data drawn like its training set. It says
nothing about accuracy at the *optimum*, which is where an optimiser deliberately
pushes -- exactly where a surrogate is least trustworthy. This script checks the
designs the search actually selected, against:

    1. the same-mesh FDM solver  (solver agreement)
    2. the grid-converged reference (discretisation + model error)

Writes reports/thermal_validation.json.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "serdes_architect", "src"))

from thermal.solver import ThermalSolver                          # noqa: E402
# reference_from_solver moved to trust_guard when the guard took over the
# solver cascade; re-exported here because this script's name is the one the
# reports cite.
from trust_guard import ReferenceCascade, reference_from_solver   # noqa: E402
from pareto_search import (load_surrogate, build_power_maps, GRID, BLOCK,  # noqa: E402
                           SUB, N_SUB, surrogate_peaks)


def solve_reference(cascade: ReferenceCascade, power_map: torch.Tensor,
                    refine: int = 1) -> float:
    """Peak temperature of layer 0 on a mesh `refine` times finer than the map.

    This used to monkeypatch the reference solver's private `_power_density` and
    re-assemble the matrix on every call. `ReferenceCascade` assembles and
    factorises each mesh once and takes the power map through the solver's
    public `power_map=` argument, so the exhaustive monolithic scan below costs
    one factorisation rather than twenty-five.
    """
    return cascade.peak(power_map[0].numpy(), refine)


def main():
    cfg_path = "results/golden_config.json"
    cfg = json.loads(Path(cfg_path).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    logic_w, mem_w = total_w * 0.75, total_w * 0.25
    layers = int(cfg["voxel_stack_params"]["layers"])

    solver = ThermalSolver(cfg_path)
    cascade = ReferenceCascade(reference_from_solver(solver))
    model, mean, std = load_surrogate("results/fno_model_mixedz2_lam0p1.pt",
                                      "results/norm_stats_mixedz2_lam0p1.pt",
                                      layers)

    front_doc = json.loads(Path("../reports/pareto_front_nsga2.json").read_text())
    genomes = front_doc["front_genomes"]
    keys = front_doc.get("genome_keys") or list(genomes[0].keys())
    expected = 2 * N_SUB + 2
    if len(keys) != expected:
        raise ValueError(f"front genomes have {len(keys)} variables, expected "
                         f"{expected}; re-run pareto_search.py")

    # coolest, hottest and median members of the front
    picks = {"front_coolest": 0, "front_median": len(genomes) // 2,
             "front_hottest": len(genomes) - 1}
    rows = []
    for label, idx in picks.items():
        g = np.array([[genomes[idx][k] for k in keys]])
        pmap = build_power_maps(g, logic_w, mem_w, layers)
        surro = float(surrogate_peaks(model, mean, std, pmap, layers)[0])
        fdm = float(solver.solve_steady_state(pmap)[0, 0].max())
        r1 = solve_reference(cascade, pmap, refine=1)
        r2 = solve_reference(cascade, pmap, refine=2)
        rows.append({
            "design": label,
            "surrogate_peak_c": surro,
            "fdm_same_mesh_peak_c": fdm,
            "reference_same_mesh_peak_c": r1,
            "reference_refined_peak_c": r2,
            "surrogate_error_vs_reference_k": surro - r2,
            "fdm_error_vs_reference_k": fdm - r2,
            "solver_agreement_k": fdm - r1,
        })
        print(f"  {label:16} surrogate {surro:7.2f} | FDM {fdm:7.2f} | "
              f"ref {r1:7.2f} | ref(2x) {r2:7.2f} | surrogate err "
              f"{surro - r2:+6.2f} K")

    # --- does the shattering claim survive the reference solver? ------------
    sv = front_doc["shattered_vs_monolithic"]
    best_sh = np.array([[genomes[0][k] for k in keys]])
    sh_map = build_power_maps(best_sh, logic_w, mem_w, layers)
    sh_ref = solve_reference(cascade, sh_map, refine=2)

    # Best monolithic, scanned on the reference solver directly -- over the
    # memory block's placement as well as the logic block's. Pinning the memory
    # block at the die centre, as this scan used to, handicaps the monolithic
    # side of a comparison whose shattered side optimises both: the same class
    # of unfair comparison that produced the discarded "+52 C" figure. With the
    # operator prefactorised the full 4-variable scan is ~600 solves, about a
    # second.
    mono_best, mono_at = float("inf"), None
    for lx in range(0, GRID - BLOCK + 1, 2):
        for ly in range(0, GRID - BLOCK + 1, 2):
            for mx in range(0, GRID - BLOCK + 1, 2):
                for my in range(0, GRID - BLOCK + 1, 2):
                    m = torch.zeros((1, layers, GRID, GRID))
                    m[0, 0, ly:ly + BLOCK, lx:lx + BLOCK] = logic_w / (BLOCK * BLOCK)
                    m[0, 1, my:my + BLOCK, mx:mx + BLOCK] = mem_w / (BLOCK * BLOCK)
                    t = solve_reference(cascade, m, refine=1)
                    if t < mono_best:
                        mono_best, mono_at = t, (lx, ly, mx, my)
    print(f"\n  shattering claim, checked on the reference solver:")
    print(f"    monolithic best (reference)  : {mono_best:7.2f} C at "
          f"logic {mono_at[:2]}, memory {mono_at[2:]}")
    print(f"    shattered  best (reference)  : {sh_ref:7.2f} C")
    print(f"    headroom recovered           : {mono_best - sh_ref:+7.2f} C")
    print(f"    surrogate predicted          : {sv['headroom_recovered_c']:+7.2f} C")

    doc = {
        "reference_solver": {
            "module": "physics_accelerated/src/thermal_reference.py",
            "method": "finite volume, harmonic-mean face conductance, Robin BCs, "
                      "direct sparse solve",
            "verified_against": "analytic 1D slab (1e-9 C) and global energy balance "
                                "(8e-12 relative)",
        },
        "surrogate": "results/fno_model_mixedz2_lam0p1.pt (FNO + heat-equation "
                     "residual, retrained on the search distribution, labels "
                     "on a z-refined stack)",
        "designs": rows,
        "surrogate_error_vs_reference_k": {
            "mean_abs": float(np.mean([abs(r["surrogate_error_vs_reference_k"]) for r in rows])),
            "max_abs": float(np.max([abs(r["surrogate_error_vs_reference_k"]) for r in rows])),
        },
        "solver_agreement_k": {
            "max_abs": float(np.max([abs(r["solver_agreement_k"]) for r in rows])),
        },
        "shattered_vs_monolithic": {
            "reference_monolithic_peak_c": mono_best,
            "reference_shattered_peak_c": sh_ref,
            "reference_headroom_c": mono_best - sh_ref,
            "surrogate_headroom_c": sv["headroom_recovered_c"],
        },
        "caveat": ("Errors are measured at the designs the optimiser selected, which "
                   "is where a surrogate is least reliable -- not on a random test "
                   "split."),
    }
    out = Path("../reports/thermal_validation.json")
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
