"""The surrogate's spectral convolution is circular. The die's sides are not.

A Fourier neural operator multiplies in the frequency domain, which is a
*circular* convolution: column 0 of the grid is adjacent to column 15. Our
reference model has adiabatic sides (`h_side_w_m2k=0.0` in
`trust_guard.reference_from_solver`), so the real stack has no such adjacency --
heat at the left edge of the die leaves vertically, it does not reappear on the
right.

NVIDIA PhysicsNeMo's FNO takes `padding=8` by default for exactly this reason:
zero-extending the domain before the FFT is the standard mitigation for a
non-periodic problem. Our FNO2d has no padding parameter and was trained
without one. This script measures what that costs, three ways:

    rings      held-out error as a function of distance to the nearest die edge
    probe      one hot macro walked inward from the edge, surrogate vs the
               reference solver, reading the temperature on the *opposite* edge
    coupling   edge error regressed on opposite-edge power, in-distribution,
               controlled for total map power

The probe is the mechanism and the coupling is the in-distribution evidence.
Writes reports/boundary_artifact.json.

Run from the repository root:

    python physics_accelerated/src/boundary_artifact.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "serdes_architect/src"))

from train import FNO2d                                        # noqa: E402
from thermal.solver import ThermalSolver                        # noqa: E402
from trust_guard import ReferenceCascade, reference_from_solver  # noqa: E402

CFG = REPO / "physics_accelerated/results/golden_config.json"
CKPT = REPO / "physics_accelerated/results/fno_model_mixedz2_lam0p1.pt"
STATS = REPO / "physics_accelerated/results/norm_stats_mixedz2_lam0p1.pt"
DATA = REPO / "physics_accelerated/data"
OUT = REPO / "reports/boundary_artifact.json"
GRID = 16
SUB = 2                      # the shattered sub-macro footprint, as in pareto_search


def load():
    state = torch.load(CKPT, map_location="cpu", weights_only=True)
    stats = torch.load(STATS, map_location="cpu", weights_only=True)
    model = FNO2d(modes1=8, modes2=8, width=32, layers=state["fc2.bias"].numel())
    model.load_state_dict(state)
    model.eval()
    return model, float(stats["mean"]), float(stats["std"])


def rings(err: np.ndarray) -> dict:
    """Mean error per ring, ring 0 being the cells touching the die edge."""
    ii, jj = np.meshgrid(np.arange(GRID), np.arange(GRID), indexing="ij")
    dist = np.minimum.reduce([ii, jj, GRID - 1 - ii, GRID - 1 - jj])
    out = {}
    print("ring  cells  mean|err| K    bias K")
    for r in range(GRID // 2):
        m = dist == r
        e = err[:, :, m]
        out[str(r)] = {"cells_per_map": int(m.sum()),
                       "mean_abs_k": float(np.abs(e).mean()),
                       "mean_signed_k": float(e.mean())}
        print(f"  {r}   {m.sum():4d}     {out[str(r)]['mean_abs_k']:.4f}      "
              f"{out[str(r)]['mean_signed_k']:+.4f}")
    out["outer_over_inner"] = (out["0"]["mean_abs_k"]
                               / out[str(GRID // 2 - 1)]["mean_abs_k"])
    print(f"outer ring / innermost ring: {out['outer_over_inner']:.2f}x")
    return out


def probe(model, mean: float, std: float, per_layer: int, layers: int,
          hot_w: float) -> list:
    """One hot macro walked in from the edge. Power is held constant, so only
    position varies -- extrapolation cannot explain a spike at one position."""
    solver = ThermalSolver(str(CFG))
    cascade = ReferenceCascade(reference_from_solver(solver))
    rows = []
    print("\n x   ref far-edge   surr far-edge    delta K   ref peak  surr peak")
    for x0 in (0, 1, 2, 4, 7):
        pmap = np.zeros((layers, GRID, GRID))
        y0 = GRID // 2 - SUB // 2
        pmap[0, y0:y0 + SUB, x0:x0 + SUB] = hot_w / (SUB * SUB)

        ref = cascade.field(pmap, refine=1, refine_z=per_layer)
        t = torch.from_numpy(pmap).float().unsqueeze(0)
        t = torch.repeat_interleave(t, per_layer, dim=1) / per_layer
        with torch.no_grad():
            sur = (model(t)[0] * std + mean).numpy()

        far = GRID - 1 if x0 < GRID // 2 else 0
        r_far, s_far = float(ref[0, :, far].max()), float(sur[0, :, far].max())
        rows.append({"macro_x": x0, "ref_far_edge_c": r_far,
                     "surrogate_far_edge_c": s_far, "delta_k": s_far - r_far,
                     "ref_peak_c": float(ref[0].max()),
                     "surrogate_peak_c": float(sur[0].max())})
        print(f" {x0}      {r_far:8.3f}       {s_far:8.3f}    {s_far - r_far:+8.3f}  "
              f"{float(ref[0].max()):8.2f}  {float(sur[0].max()):8.2f}")
    return rows


def coupling(err: np.ndarray, power: np.ndarray) -> dict:
    """Edge error against power on the opposite edge, pooled over four edges.

    Controlled for total map power, because a map with much edge power is also
    a hotter map and hotter maps have larger errors everywhere -- which would
    manufacture this correlation with no wrap involved. Same-edge power is the
    second control: a circular convolution couples opposite edges specifically.
    """
    opp, e_edge, same = [], [], []
    for a, b in ((0, -1), (-1, 0)):
        opp.append(power[:, :, a].sum(1)); e_edge.append(err[:, :, b].mean(1))
        same.append(power[:, :, b].sum(1))
        opp.append(power[:, a, :].sum(1)); e_edge.append(err[:, b, :].mean(1))
        same.append(power[:, b, :].sum(1))
    opp, e_edge, same = map(np.concatenate, (opp, e_edge, same))
    total = np.tile(power.sum(axis=(1, 2)), 4)

    def fit(*cols):
        a = np.column_stack(list(cols) + [np.ones(len(e_edge))])
        return np.linalg.lstsq(a, e_edge, rcond=None)[0]

    simple = fit(opp)
    ctrl = fit(opp, total)
    both = fit(opp, total, same)
    out = {
        "slope_k_per_w": float(simple[0]),
        "pearson_r": float(np.corrcoef(opp, e_edge)[0, 1]),
        "slope_controlled_for_total_power": float(ctrl[0]),
        "slope_controlled_for_total_and_same_edge": float(both[0]),
        "total_power_coefficient": float(ctrl[1]),
        "corr_opposite_edge_power_vs_total": float(np.corrcoef(opp, total)[0, 1]),
        "n": int(len(e_edge)),
    }
    print(f"\nedge error vs opposite-edge power : {out['slope_k_per_w']:+.4f} K/W "
          f"(r {out['pearson_r']:+.3f})")
    print(f"  controlled for total power      : "
          f"{out['slope_controlled_for_total_power']:+.4f} K/W")
    print(f"  controlled for total + same edge: "
          f"{out['slope_controlled_for_total_and_same_edge']:+.4f} K/W")
    return out


def front_exposure() -> dict:
    """How many published designs put a macro against a die edge, where the
    artifact is largest. The trust guard re-solves what the search *selects*;
    it never sees what the search discarded on the way."""
    path = REPO / "reports/pareto_front_nsga2.json"
    if not path.exists():
        return {"available": False}
    doc = json.loads(path.read_text())
    keys = doc.get("genome_keys") or list(doc["front_genomes"][0])
    g = np.round(np.array([[m[k] for k in keys] for m in doc["front_genomes"]])).astype(int)
    sub, mem = g[:, :8], g[:, 8:]
    on_sub = ((sub == 0) | (sub == GRID - SUB)).any(axis=1)
    on_mem = ((mem == 0) | (mem == GRID - 4)).any(axis=1)
    out = {"available": True, "members": int(len(g)),
           "logic_submacro_on_edge": int(on_sub.sum()),
           "memory_block_on_edge": int(on_mem.sum()),
           "min_submacro_coord": int(sub.min()),
           "max_submacro_coord": int(sub.max())}
    print(f"\npublished front: {out['logic_submacro_on_edge']}/{out['members']} "
          f"members with a logic sub-macro on a die edge, "
          f"{out['memory_block_on_edge']}/{out['members']} with the memory block")
    return out


def main() -> int:
    model, mean, std = load()
    cfg = json.loads(CFG.read_text())
    layers = int(cfg["voxel_stack_params"]["layers"])
    channels = int(model.fc2.bias.numel())
    per_layer = channels // layers

    x = torch.load(DATA / "x_mixed_z2_test.pt", map_location="cpu", weights_only=True)
    y = torch.load(DATA / "y_mixed_z2_test.pt", map_location="cpu", weights_only=True)
    with torch.no_grad():
        err = ((model(x) * std + mean) - y).numpy()

    doc = {
        "question": "the surrogate's spectral convolution is circular and the "
                    "die's sides are adiabatic; what does the missing domain "
                    "padding cost?",
        "model": str(CKPT.relative_to(REPO)),
        "z_refine": per_layer,
        "test_set": {"n": int(x.shape[0]), "grid": GRID},
        "error_by_edge_distance": rings(err),
        "edge_hotspot_probe": probe(model, mean, std, per_layer, layers,
                                    float(cfg["max_power_budget_w"]) * 0.75),
        "antipodal_coupling": coupling(err[:, 0], x.numpy().sum(axis=1)),
        "published_front_exposure": front_exposure(),
    }
    p = doc["edge_hotspot_probe"]
    doc["wrap_signal_k"] = {
        "macro_on_edge": p[0]["delta_k"],
        "macro_centred": p[-1]["delta_k"],
        "attributable_to_position": p[0]["delta_k"] - p[-1]["delta_k"],
    }
    print(f"\nfar-edge error with the macro on the edge: {p[0]['delta_k']:+.2f} K")
    print(f"                        macro centred     : {p[-1]['delta_k']:+.2f} K")
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
