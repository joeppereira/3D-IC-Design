"""Training sets for the thermal surrogate, and the distribution they come from.

Why this exists
---------------
The trust guard measured that the surrogate's training set and the optimiser's
search space barely overlap: `data_gen.py` draws random r=3 discs on the logic
die and *single hot cells* on the memory die, while `pareto_search.py` evaluates
2x2 sub-macro blocks and a solid 4x4 memory macro. Every design the search can
express sat 8-15x beyond the out-of-distribution threshold, and the network was
6.8x worse there (14.21 K) than where it was fitted (2.10 K). That is a training
set problem, not a network problem, and this module is where it is fixed.

Two changes from `data_gen.py`:

  * **The distribution is explicit and selectable.** `layouts` draws macro
    placements -- a deliberate *superset* of the search's parameterisation, so
    that measuring the retrained surrogate at optimiser-selected designs is
    still a generalisation test rather than a lookup. `hotspots` reproduces the
    old distribution so the comparison is like-for-like, and `mixed` is both,
    which is what the shipped model is trained on: covering the search space is
    the point, forgetting the rest is not.

  * **Labels come from a direct solve, not a relaxation.** The reference solver
    factorises the same 16x16x5 discretisation once and back-substitutes, which
    is exact for that mesh, ~300x faster than iterating the FDM solver to a
    tolerance, and cannot be stopped early. (`data_gen.py` once capped its solve
    at 200 iterations -- 4% of the way to convergence -- and trained the network
    on fields 21 C too cold.) The two agree to **0.0031 K** across the field,
    which is the same agreement the project reports between its two solvers.

Splits are drawn from separate RNG streams: held out means held out.

Run
---
    python dataset.py --distribution mixed --train 3000 --val 400 --test 400
    python dataset.py --distribution hotspots --train 240 --tag legacy
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from trust_guard import ReferenceCascade, build_context, expand_power_map

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "physics_accelerated/results/golden_config.json"
DEFAULT_OUT = REPO_ROOT / "serdes_architect/data"


# --- the two distributions -----------------------------------------------

def hotspot_maps(n: int, rng: np.random.Generator, total_w: float,
                 layers: int, grid: int) -> np.ndarray:
    """`data_gen.py`'s distribution: discs on the logic die, single cells on
    the memory die. Kept so the old and new models can be compared on it."""
    maps = np.zeros((n, layers, grid, grid), dtype=np.float32)
    ys, xs = np.ogrid[0:grid, 0:grid]
    for i in range(n):
        target = total_w * 0.75
        acc = 0.0
        while acc < target:
            cy, cx = rng.integers(0, grid, 2)
            p = rng.uniform(target * 0.1, target * 0.3)
            mask = (xs - cx) ** 2 + (ys - cy) ** 2 <= 9.0
            maps[i, 0][mask] += p / mask.sum()
            acc += p
        target1 = total_w * 0.25
        acc = 0.0
        while acc < target1:
            cy, cx = rng.integers(2, grid - 2, 2)
            p = rng.uniform(target1 * 0.2, target1 * 0.5)
            maps[i, 1, cy, cx] += p
            acc += p
    return maps


def layout_maps(n: int, rng: np.random.Generator, total_w: float,
                layers: int, grid: int) -> np.ndarray:
    """Macro placements: a superset of what the optimiser searches.

    The search is exactly four 2x2 logic sub-macros, one 4x4 memory macro, a
    fixed 75/25 split and a fixed 60 W. Training on precisely that would make
    the later measurement circular -- the network would be tested on its own
    training parameterisation. So each of those is widened:

        sub-macros     1 to 8          (search: 4)
        sub-macro edge 2 to 4 cells    (search: 2)
        memory edge    3 to 5 cells    (search: 4)
        logic fraction 0.50 to 0.90    (search: 0.75)
        total power    40 to 80 W      (search: 60)

    The search's own setting is an interior point of every range, so designs it
    selects are interpolation rather than a lookup.
    """
    maps = np.zeros((n, layers, grid, grid), dtype=np.float32)
    for i in range(n):
        total = rng.uniform(total_w * 2 / 3, total_w * 4 / 3)
        frac = rng.uniform(0.50, 0.90)
        logic_w, mem_w = total * frac, total * (1.0 - frac)

        n_sub = int(rng.integers(1, 9))
        per_sub = logic_w / n_sub
        for _ in range(n_sub):
            e = int(rng.integers(2, 5))
            x = int(rng.integers(0, grid - e + 1))
            y = int(rng.integers(0, grid - e + 1))
            maps[i, 0, y:y + e, x:x + e] += per_sub / (e * e)

        e = int(rng.integers(3, 6))
        x = int(rng.integers(0, grid - e + 1))
        y = int(rng.integers(0, grid - e + 1))
        maps[i, 1, y:y + e, x:x + e] += mem_w / (e * e)
    return maps


def mixed_maps(n: int, rng: np.random.Generator, total_w: float,
               layers: int, grid: int) -> np.ndarray:
    """Half each. Covering the search space is the point; losing the
    distribution the surrogate already handled is not."""
    k = n // 2
    return np.concatenate([layout_maps(n - k, rng, total_w, layers, grid),
                           hotspot_maps(k, rng, total_w, layers, grid)])


SAMPLERS = {"hotspots": hotspot_maps, "layouts": layout_maps,
            "mixed": mixed_maps}


# --- labels ---------------------------------------------------------------

def solve_labels(maps: np.ndarray, cascade: ReferenceCascade,
                 refine_z: int = 1) -> np.ndarray:
    """Exact steady-state fields, on a mesh refined `refine_z` times in z.

    One z-cell per layer leaves +1.77 C of discretisation error in the peak,
    measured across the front and consistently positive -- the dominant term
    once the network was retrained. Labelling on the refined stack moves that
    error out of the surrogate rather than correcting for it afterwards. The
    field returned has `layers * refine_z` channels, and the power maps are
    expanded to match.
    """
    lv = cascade.level(1)
    if refine_z == 1:
        return np.stack([cascade.field(m, 1) for m in maps]).astype(np.float32)
    a, b, mesh = cascade.ref.assemble(maps.shape[-1], maps.shape[-2], refine_z)
    import scipy.sparse.linalg as spla
    lu = spla.splu(a.tocsc())
    bc = b - mesh["q"].reshape(-1)
    out = []
    for m in maps:
        q = expand_power_map(m, 1, mesh["layer_of"])
        t = lu.solve(bc + q.reshape(-1))
        out.append(t.reshape(mesh["nz"], mesh["ny"], mesh["nx"]))
    return np.stack(out).astype(np.float32)


def expand_maps_z(maps: np.ndarray, refine_z: int) -> np.ndarray:
    """Power maps onto the refined stack: each layer's watts split evenly over
    its sub-layers, so the total is unchanged."""
    if refine_z == 1:
        return maps
    return np.repeat(maps, refine_z, axis=1) / refine_z


def _rel(path: Path) -> str:
    """Repo-relative when it can be, absolute when it cannot -- `run_full_cycle.sh`
    passes a spec file by a relative path from a different directory."""
    path = Path(path).resolve()
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def build(distribution: str, counts: dict, config: Path, out_dir: Path,
          tag: str | None = None, seed: int = 20260920,
          refine_z: int = 1) -> dict:
    config = Path(config).resolve()
    out_dir = Path(out_dir).resolve()
    solver, cascade = build_context(config)
    cfg = json.loads(config.read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    layers = int(cfg["voxel_stack_params"]["layers"])
    grid = int(cfg["voxel_stack_params"]["grid_size"])
    sampler = SAMPLERS[distribution]

    out_dir.mkdir(parents=True, exist_ok=True)
    name = tag or distribution
    manifest = {
        "distribution": distribution,
        "config": _rel(config),
        "grid": grid, "layers": layers, "refine_z": refine_z,
        "channels": layers * refine_z,
        "nominal_total_power_w": total_w,
        "label_method": ("reference solver, direct sparse solve on the same "
                         "16x16x5 discretisation the FDM solver uses "
                         "(agreement 0.0031 K across the field)"),
        "splits": {},
    }
    for i, (split, n) in enumerate(counts.items()):
        if not n:
            continue
        # One stream per split, so growing the training set cannot pull a
        # sample the test set already holds.
        rng = np.random.default_rng([seed, i])
        t0 = time.perf_counter()
        x = sampler(n, rng, total_w, layers, grid)
        t_sample = time.perf_counter() - t0
        t0 = time.perf_counter()
        y = solve_labels(x, cascade, refine_z)
        x = expand_maps_z(x, refine_z)
        t_label = time.perf_counter() - t0

        xp = out_dir / f"x_{name}_{split}.pt"
        yp = out_dir / f"y_{name}_{split}.pt"
        torch.save(torch.from_numpy(x), xp)
        torch.save(torch.from_numpy(y), yp)
        manifest["splits"][split] = {
            "n": int(n),
            "x": _rel(xp),
            "y": _rel(yp),
            "total_power_w": {"min": float(x.sum(axis=(1, 2, 3)).min()),
                              "max": float(x.sum(axis=(1, 2, 3)).max())},
            "peak_c": {"min": float(y[:, 0].max(axis=(1, 2)).min()),
                       "max": float(y[:, 0].max(axis=(1, 2)).max())},
            "sample_s": t_sample, "label_s": t_label,
        }
        print(f"  {split:5} {n:5d} maps  peak Tj "
              f"{manifest['splits'][split]['peak_c']['min']:6.1f}"
              f"-{manifest['splits'][split]['peak_c']['max']:6.1f} C  "
              f"({t_label:.1f} s of solves)")

    # The residual of the labels themselves: a label set that does not satisfy
    # the discrete heat equation cannot be fixed by any amount of training.
    import sys
    sys.path.insert(0, str(REPO_ROOT / "serdes_architect/src"))
    from heat_residual import HeatEquationResidual
    res = HeatEquationResidual.from_solver(solver, refine_z=refine_z)
    split = next(iter(manifest["splits"]))
    x = torch.load(REPO_ROOT / manifest["splits"][split]["x"])
    y = torch.load(REPO_ROOT / manifest["splits"][split]["y"])  # _rel keeps this valid
    manifest["label_heat_residual_k"] = float(res.rms_k(y, x))
    print(f"  heat-equation residual of the labels: "
          f"{manifest['label_heat_residual_k']:.3e} K")

    path = out_dir / f"manifest_{name}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  wrote {_rel(path)}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--distribution", choices=sorted(SAMPLERS), default="mixed")
    ap.add_argument("--train", type=int, default=3000)
    ap.add_argument("--val", type=int, default=400)
    ap.add_argument("--test", type=int, default=400)
    ap.add_argument("--tag", default=None,
                    help="file-name stem (default: the distribution name)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=20260920)
    ap.add_argument("--refine-z", type=int, default=1,
                    help="z-cells per layer in the labels; 2 removes the "
                         "+1.77 C vertical discretisation error")
    args = ap.parse_args(argv)

    print(f"📦 {args.distribution} dataset: {args.train} train / {args.val} val "
          f"/ {args.test} test")
    build(args.distribution,
          {"train": args.train, "val": args.val, "test": args.test},
          Path(args.config), Path(args.out), tag=args.tag, seed=args.seed,
          refine_z=args.refine_z)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
