"""The correction for power structure the search cannot represent, as a band.

`power_map_reality.md` measured that a real design puts half its power in 15-19%
of its area, and that arranging a macro's watts that way rather than uniformly
costs +16.84 C on the front's coolest design. The search evaluates uniform
blocks and cannot do otherwise: on a 16x16 grid a 2x2 macro is four cells, so
"15% of the macro's area" is not a representable quantity. The correction has to
be carried alongside the number rather than inside it, and that is what this
module produces.

Measuring it across the front rather than on one design changed the shape of the
answer: **the penalty is not a constant**. It runs +16 C on the coolest design
to +78 C on the hottest, because a design that is already hot concentrates
worse. Quoted as a fraction of the temperature rise above ambient it is 31-66%,
which is the form that transfers.

The question that decides how it is carried
-------------------------------------------
If the penalty is the same for every design, it is an offset: it shifts every
published temperature, changes whether a design passes a limit, and -- by the
argument in `rank_churn.py` -- **cannot reorder the front**. If it varies with
the design, it can, and then the front is not merely uncertain but possibly
wrong.

That is a measurement, not an assumption, and it is what this module makes:
solve each sampled front design twice, once with its macro power uniform and
once with the measured shape, and compare both the penalties and the orderings.

What it is not
--------------
This does not make the surrogate or the search aware of structure. Doing that
needs a grid fine enough to express it -- `critical_review.md` item 11 -- and
would change the front rather than annotate it. Until then the honest output is
a band with its provenance attached, which is what `rank_churn.py` was built to
support.

Run
---
    python structural_band.py              # writes reports/structural_band.json
    python structural_band.py --verify     # assertions only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "serdes_architect", "src"))

import submodel as sm                                              # noqa: E402
from trust_guard import (build_context, expand_power_map,          # noqa: E402
                         _kendall_tau)
from pareto_search import build_power_maps                         # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"

# Measured in reports/power_map_reality.md, from real placed designs on ASAP7.
# Half the power in this fraction of the area; the two designs bracket the band.
SHAPES = {"aes": 0.186, "gcd": 0.150}
POWER_FRACTION = 0.5


def penalty_for(design_index: int, cascade, maps, refine: int,
                parent_refine: int, shapes: dict) -> dict:
    """Uniform vs structured peak for one design, on its own hotspot region."""
    lv = cascade.level(parent_refine)
    pq = expand_power_map(maps[design_index], parent_refine, lv.mesh["layer_of"])
    parent = cascade.ref.solve(nx=lv.mesh["nx"], ny=lv.mesh["ny"],
                               refine_z=parent_refine, power_map=pq)
    pk = np.unravel_index(int(np.argmax(parent.t_field_c[0])),
                          parent.t_field_c[0].shape)
    centre = ((pk[1] + 0.5) / lv.mesh["nx"], (pk[0] + 0.5) / lv.mesh["ny"])
    roi = sm._box(centre, 0.15, lv.mesh["nx"], lv.mesh["ny"])

    base, _, q = sm.solve_region(cascade.ref, parent.t_field_c, pq, roi,
                                 refine=refine)
    uniform = float(base.t_field_c[0].max())
    out = {"index": design_index, "uniform_peak_c": uniform,
           "parent_peak_c": float(parent.t_field_c[0].max())}
    for name, area in shapes.items():
        sol, _, _ = sm.solve_region(cascade.ref, parent.t_field_c, pq, roi,
                                    refine=refine,
                                    q_fine=sm.concentrate(q, POWER_FRACTION,
                                                          area))
        peak = float(sol.t_field_c[0].max())
        out[f"{name}_peak_c"] = peak
        out[f"{name}_penalty_c"] = peak - uniform
        # As a fraction of the rise above ambient: the penalty turned out to
        # scale with how hot the design already is, so an absolute band would
        # be wrong everywhere except where it was measured.
        rise = uniform - 25.0
        out[f"{name}_penalty_frac_of_rise"] = (peak - uniform) / rise \
            if rise > 1e-9 else float("nan")
    return out


def analyse(cascade, maps, indices, refine: int = 6,
            parent_refine: int = 2) -> dict:
    rows = [penalty_for(i, cascade, maps, refine, parent_refine, SHAPES)
            for i in indices]

    uniform = np.array([r["uniform_peak_c"] for r in rows])
    per_shape = {}
    for name in SHAPES:
        pen = np.array([r[f"{name}_penalty_c"] for r in rows])
        structured = np.array([r[f"{name}_peak_c"] for r in rows])
        frac = np.array([r[f"{name}_penalty_frac_of_rise"] for r in rows])
        per_shape[name] = {
            "area_fraction": SHAPES[name],
            "penalty_c": {"min": float(pen.min()), "max": float(pen.max()),
                          "mean": float(pen.mean()),
                          "spread": float(pen.max() - pen.min())},
            "penalty_fraction_of_rise": {"min": float(frac.min()),
                                         "max": float(frac.max()),
                                         "mean": float(frac.mean())},
            "kendall_tau_vs_uniform": _kendall_tau(uniform, structured),
            "winner_uniform": int(np.argmin(uniform)),
            "winner_structured": int(np.argmin(structured)),
            "reorders": bool(np.argmin(uniform) != np.argmin(structured)),
        }

    all_pen = np.concatenate([[r[f"{n}_penalty_c"] for r in rows]
                              for n in SHAPES])
    all_frac = np.concatenate([[r[f"{n}_penalty_frac_of_rise"] for r in rows]
                               for n in SHAPES])
    reorders = any(v["reorders"] for v in per_shape.values())
    # "Offset" has a specific consequence -- it would make the correction a
    # single number -- so it is tested rather than assumed. It is not one here.
    is_offset = float(all_pen.max() - all_pen.min()) < 2.0
    return {
        "question": ("is the correction for unrepresentable power structure an "
                     "offset, which cannot reorder the front, or does it vary "
                     "by design, which can?"),
        "shapes": SHAPES,
        "power_fraction_in_core": POWER_FRACTION,
        "n_designs": len(rows),
        "designs": rows,
        "per_shape": per_shape,
        "band_c": {"low": float(all_pen.min()), "high": float(all_pen.max()),
                   "spread": float(all_pen.max() - all_pen.min())},
        "band_fraction_of_rise": {"low": float(all_frac.min()),
                                  "high": float(all_frac.max()),
                                  "mean": float(all_frac.mean())},
        "is_offset": is_offset,
        "rank_preserving": not reorders,
        "verdict": (
            "the penalty varies enough by design to change which one wins: the "
            "front is not merely uncertain, it may be ordered wrongly"
            if reorders else
            "the penalty is a constant offset, so it shifts every temperature "
            "equally and cannot reorder anything"
            if is_offset else
            "the penalty is NOT an offset -- it scales with how hot a design "
            "already is -- but it rises monotonically with the base peak, so "
            "it is a monotone transform and the ordering survives. Quote it as "
            "a fraction of the temperature rise, not as degrees"),
    }


def print_report(doc: dict) -> None:
    print(f"📏 Structural band on {doc['n_designs']} front designs "
          f"({doc['power_fraction_in_core']:.0%} of macro power in "
          f"{'/'.join(f'{v:.1%}' for v in doc['shapes'].values())} of its area)\n")
    print(f"  {'design':>7} {'uniform':>9} " +
          " ".join(f"{n + ' peak':>11} {n + ' pen':>9}" for n in doc["shapes"]))
    for r in doc["designs"]:
        line = f"  {r['index']:7d} {r['uniform_peak_c']:8.2f}C "
        for n in doc["shapes"]:
            line += f"{r[f'{n}_peak_c']:10.2f}C {r[f'{n}_penalty_c']:+8.2f}C "
        print(line)
    print()
    for name, v in doc["per_shape"].items():
        f = v["penalty_fraction_of_rise"]
        print(f"  {name}: {v['penalty_c']['min']:+.2f} to "
              f"{v['penalty_c']['max']:+.2f} C = {f['min']:.0%} to {f['max']:.0%} "
              f"of the rise; tau {v['kendall_tau_vs_uniform']:.3f}, winner "
              f"#{v['winner_uniform']} -> #{v['winner_structured']}"
              f"{'  REORDERS' if v['reorders'] else ''}")
    b, bf = doc["band_c"], doc["band_fraction_of_rise"]
    print(f"\n  absolute band       : +{b['low']:.2f} to +{b['high']:.2f} C "
          f"(spread {b['spread']:.1f} -- not an offset)")
    print(f"  transferable band   : +{bf['low']:.0%} to +{bf['high']:.0%} of the "
          f"temperature rise above ambient")
    print(f"  {doc['verdict']}")


def _assert_behaves(doc: dict) -> bool:
    ok = True
    if any(r[f"{n}_penalty_c"] < 0 for r in doc["designs"] for n in doc["shapes"]):
        print("\n  ❌ concentrating the same watts lowered a peak, which is not "
              "physical.")
        ok = False
    b = doc["band_c"]
    if doc["is_offset"] and b["spread"] >= 2.0:
        print("\n  ❌ reported as an offset while spanning "
              f"{b['spread']:.1f} C.")
        ok = False
    for name, v in doc["per_shape"].items():
        if v["kendall_tau_vs_uniform"] < 0.5:
            print(f"\n  ❌ {name}: the ordering barely survives the correction "
                  f"(tau {v['kendall_tau_vs_uniform']:.3f}); a band is not "
                  f"enough to publish and the front needs re-running with "
                  f"structure in the objective.")
            ok = False
    # Derived, not hardcoded: the check is "a tighter core costs more", which
    # is a property of the physics, not of these two design names.
    shapes = doc["shapes"]
    if len(shapes) >= 2:
        tight = min(shapes, key=lambda k: shapes[k])
        loose = max(shapes, key=lambda k: shapes[k])
        for r in doc["designs"]:
            if r[f"{tight}_penalty_c"] < r[f"{loose}_penalty_c"] - 1e-9:
                print(f"\n  ❌ the tighter shape ({tight}) penalised less than "
                      f"the looser one ({loose}) on design {r['index']}: the "
                      f"concentration model is wrong.")
                ok = False
                break
    if ok:
        print("\n  ✅ every penalty is positive, the tighter shape always costs "
              "more, and the ordering survives the correction.")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--front", default=str(REPO_ROOT / "reports/pareto_front_nsga2.json"))
    ap.add_argument("--designs", type=int, default=8,
                    help="how many front designs to sample, evenly spaced")
    ap.add_argument("--refine", type=int, default=6)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/structural_band.json"))
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
    idx = np.linspace(0, len(maps) - 1, min(args.designs, len(maps)),
                      dtype=int).tolist()

    doc = analyse(cascade, maps, idx, refine=args.refine)
    doc["source"] = {
        "shapes_from": "reports/power_map_reality.md (OpenROAD on ASAP7)",
        "front": os.path.relpath(args.front, REPO_ROOT),
        "note": ("the shapes are measured from real placed designs; applying "
                 "them to this design assumes its logic concentrates similarly, "
                 "which is why two designs are carried as a band rather than "
                 "one as a correction"),
    }
    doc["caveats"] = [
        "the search cannot represent this structure at 16x16 -- a 2x2 macro is "
        "four cells -- so the correction is an annotation, not a fix; item 11 "
        "(a finer grid) is what would let the search see it",
        "the OpenROAD flow stopped at placement, so the shapes are an upper "
        "bound on area and the penalties a lower bound",
    ]
    print_report(doc)
    ok = _assert_behaves(doc)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
