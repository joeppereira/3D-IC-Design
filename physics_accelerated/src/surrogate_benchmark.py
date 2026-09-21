"""The retrained surrogate against the old one, on the distributions that matter.

The trust guard's finding was that the surrogate's training set and the
optimiser's search space barely overlapped, and that the network was 6.8x worse
where the optimiser looks than where it was fitted. `dataset.py` fixes the
training distribution; this script is the measurement that says whether it
worked, and it is deliberately arranged so that it can say no:

  * **held-out**, never in-sample -- the old numbers this project published were
    training-set RMSE, which cannot fall when a model overfits;
  * on **both** distributions, so a model that trades the old capability for the
    new one is visible rather than reported as an improvement;
  * at **optimiser-selected designs**, which is the only place the number is
    actually used, against the reference solver on the mesh the surrogate was
    trained on (so this is network error, not discretisation);
  * and both models are asked the same questions about the same designs.

Run
---
    python surrogate_benchmark.py                 # writes reports/surrogate_retrain.json
    python surrogate_benchmark.py --verify        # assertions only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "serdes_architect", "src"))

from trust_guard import (DistributionGuard, ReferenceCascade,        # noqa: E402
                         build_context, load_training_maps, training_set_for)
from pareto_search import build_power_maps, load_surrogate           # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"
DATA = REPO_ROOT / "serdes_architect/data"

MODELS = {
    "legacy": {"model": RESULTS / "fno_model_lam0p1.pt",
               "stats": RESULTS / "norm_stats_legacy_lam0p1.pt",
               "trained_on": "240 hotspot maps (data_gen.py), labels from the "
                             "FDM solver"},
    "retrained": {"model": RESULTS / "fno_model_mixed_lam0p1.pt",
                  "stats": RESULTS / "norm_stats_mixed_lam0p1.pt",
                  "trained_on": "3000 mixed layout/hotspot maps (dataset.py), "
                                "labels from the reference solver"},
}


def peaks_and_fields(model, mean, std, x: torch.Tensor, batch: int = 64):
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            out.append(model(x[i:i + batch]) * std + mean)
    return torch.cat(out)


def on_manifest(model, mean, std, manifest: Path, residual_op) -> dict:
    doc = json.loads(manifest.read_text())
    info = doc["splits"]["test"]
    x = torch.load(REPO_ROOT / info["x"])
    y = torch.load(REPO_ROOT / info["y"])
    pred = peaks_and_fields(model, mean, std, x)
    err = (pred - y).flatten()
    pk = pred[:, 0].amax(dim=(1, 2)) - y[:, 0].amax(dim=(1, 2))
    with torch.no_grad():
        res = float(residual_op.rms_k(pred, x))
    return {"n": int(len(x)), "distribution": doc["distribution"],
            "field_rmse_k": float(torch.sqrt((err ** 2).mean())),
            "peak_mean_abs_k": float(pk.abs().mean()),
            "peak_max_abs_k": float(pk.abs().max()),
            "peak_mean_signed_k": float(pk.mean()),
            "heat_residual_k": res}


def at_optimum(model, mean, std, cascade: ReferenceCascade, maps: torch.Tensor,
               guard: DistributionGuard) -> dict:
    """Error at the designs an optimiser selected, split the way the fixes split."""
    pred = peaks_and_fields(model, mean, std, maps)[:, 0].amax(dim=(1, 2)).numpy()
    m = maps.numpy()
    same_mesh = cascade.peaks(m, 1)          # the mesh the surrogate was trained on
    refined = cascade.peaks(m, 2)
    d = guard.distance(m)
    net, total = pred - same_mesh, pred - refined
    return {
        "n": int(len(m)),
        "network_error_k": {"mean_abs": float(np.abs(net).mean()),
                            "max_abs": float(np.abs(net).max()),
                            "mean_signed": float(net.mean())},
        "total_error_vs_refined_k": {"mean_abs": float(np.abs(total).mean()),
                                     "max_abs": float(np.abs(total).max()),
                                     "mean_signed": float(total.mean())},
        "mahalanobis": {"min": float(d.min()), "max": float(d.max()),
                        "threshold": guard.threshold,
                        "flagged_fraction": float((d > guard.threshold).mean())},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--front", default=str(REPO_ROOT / "reports/pareto_front_nsga2.json"))
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/surrogate_retrain.json"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    layers = int(cfg["voxel_stack_params"]["layers"])
    solver, cascade = build_context(Path(args.config))

    from heat_residual import HeatEquationResidual
    residual_op = HeatEquationResidual.from_solver(solver)

    # The designs an optimiser selected: whatever front is currently published.
    # Both models answer for the *same* designs, so the comparison is not
    # confounded by one of them having searched somewhere easier -- but note
    # that re-running the search moves this set, because a better surrogate
    # leads the optimiser somewhere else. The legacy model's error at the front
    # it led to itself was 14.21 K; here it is measured wherever the current
    # front sits.
    front = json.loads(Path(args.front).read_text())
    keys = front["genome_keys"]
    genomes = np.array([[g[k] for k in keys] for g in front["front_genomes"]])
    front_maps = build_power_maps(genomes, total_w * 0.75, total_w * 0.25, layers)

    evals = {"layouts": DATA / "manifest_layouts_eval.json",
             "hotspots": DATA / "manifest_hotspots_eval.json"}

    report = {
        "question": ("does training on the distribution the optimiser searches "
                     "reduce the error where the optimiser looks, without "
                     "losing the distribution the surrogate already handled?"),
        "held_out": True,
        "front_designs": {"source": os.path.relpath(args.front, REPO_ROOT),
                          "n": int(len(genomes)),
                          "note": "the currently published front; both models are "
                                  "measured on these same designs, and this set "
                                  "moves when pareto_search.py is re-run"},
        "models": {},
    }

    for name, spec in MODELS.items():
        if not Path(spec["model"]).exists():
            print(f"  ⚠️  {name}: {spec['model']} not found, skipping")
            continue
        model, mean, std = load_surrogate(str(spec["model"]), str(spec["stats"]),
                                          layers)
        train_set = training_set_for(spec["model"])
        guard = DistributionGuard.fit(load_training_maps(train_set))
        entry = {
            "model": os.path.relpath(spec["model"], REPO_ROOT),
            "trained_on": spec["trained_on"],
            "training_set": os.path.relpath(train_set, REPO_ROOT),
            "norm_stats": {"mean": mean, "std": std},
            "test_sets": {k: on_manifest(model, mean, std, v, residual_op)
                          for k, v in evals.items() if v.exists()},
            "at_optimiser_selected_designs": at_optimum(model, mean, std,
                                                        cascade, front_maps,
                                                        guard),
        }
        report["models"][name] = entry

    print_report(report)
    ok = _assert_improvement(report)
    if not args.verify:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


def print_report(r: dict) -> None:
    print("📐 Surrogate retraining benchmark (all numbers held out)\n")
    print(f"  {'':12} {'layouts':>22} {'hotspots':>22} {'at the optimum':>22}")
    print(f"  {'model':12} {'RMSE':>10} {'peak':>11} {'RMSE':>10} {'peak':>11} "
          f"{'net err':>10} {'flagged':>11}")
    for name, m in r["models"].items():
        ts = m["test_sets"]
        o = m["at_optimiser_selected_designs"]
        lay, hot = ts.get("layouts", {}), ts.get("hotspots", {})
        print(f"  {name:12} {lay.get('field_rmse_k', float('nan')):9.3f}K "
              f"{lay.get('peak_mean_abs_k', float('nan')):10.3f}K "
              f"{hot.get('field_rmse_k', float('nan')):9.3f}K "
              f"{hot.get('peak_mean_abs_k', float('nan')):10.3f}K "
              f"{o['network_error_k']['mean_abs']:9.3f}K "
              f"{o['mahalanobis']['flagged_fraction'] * 100:10.0f}%")
    names = list(r["models"])
    if len(names) == 2:
        a, b = (r["models"][n]["at_optimiser_selected_designs"] for n in names)
        print(f"\n  network error at optimiser-selected designs: "
              f"{a['network_error_k']['mean_abs']:.2f} K -> "
              f"{b['network_error_k']['mean_abs']:.2f} K "
              f"({a['network_error_k']['mean_abs'] / b['network_error_k']['mean_abs']:.1f}x better)")
        print(f"  worst single design                        : "
              f"{a['network_error_k']['max_abs']:.2f} K -> "
              f"{b['network_error_k']['max_abs']:.2f} K")
        print(f"  designs outside the training distribution  : "
              f"{a['mahalanobis']['flagged_fraction'] * 100:.0f}% -> "
              f"{b['mahalanobis']['flagged_fraction'] * 100:.0f}% "
              f"(Mahalanobis {a['mahalanobis']['max']:.1f} -> "
              f"{b['mahalanobis']['max']:.1f})")


def _assert_improvement(r: dict) -> bool:
    """A benchmark that cannot fail is a press release."""
    if len(r["models"]) < 2:
        print("\n  ⚠️  only one model present; nothing to compare")
        return True
    old, new = (r["models"][n] for n in ("legacy", "retrained"))
    ok = True
    o_net = old["at_optimiser_selected_designs"]["network_error_k"]["mean_abs"]
    n_net = new["at_optimiser_selected_designs"]["network_error_k"]["mean_abs"]
    if n_net >= o_net:
        print(f"\n  ❌ retraining did not reduce the error where the optimiser "
              f"looks ({o_net:.2f} K -> {n_net:.2f} K).")
        ok = False
    o_hot = old["test_sets"]["hotspots"]["field_rmse_k"]
    n_hot = new["test_sets"]["hotspots"]["field_rmse_k"]
    if n_hot > 2.0 * o_hot:
        print(f"\n  ❌ the retrained model lost the old distribution "
              f"({o_hot:.2f} K -> {n_hot:.2f} K on held-out hotspot maps).")
        ok = False
    if new["at_optimiser_selected_designs"]["mahalanobis"]["flagged_fraction"] > 0.25:
        print("\n  ❌ the optimiser's designs are still outside the new training "
              "distribution; the dataset does not cover the search space.")
        ok = False
    if ok:
        print("\n  ✅ error at optimiser-selected designs is down, the old "
              "distribution is retained, and the search space is now covered.")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
