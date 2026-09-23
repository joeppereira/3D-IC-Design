"""A power map built from the floorplan the DEF emitter already uses.

Every thermal number in this repository so far has been solved on an *abstract*
power map: four 2x2 cells of uniform logic and one 4x4 memory block on a 16x16
grid, because that is what the search's parameterisation can express. The design
record underneath is far more structured and has been sitting there all along --
32 PHY macros at fixed origins with real footprints, three dies with real power
totals, one of them (15 x 15 mm) smaller than the domain it sits in.

This reads that record and rasterises it. Same solver, same stack, same total
watts; the only change is where the watts actually are.

What is real here and what is estimated, stated plainly because the distinction
is the whole point:

  **Real** (from `integrations/canonical.py`, the record DEF/LEF is emitted from)
    - 16 SERDES_224G_PHY at 600 x 900 um and 16 UCIE2_PHY at 900 x 600 um,
      with their fixed origins and orientations
    - die footprints and thicknesses, and the per-die power totals
      (39 W logic / 15 W SRAM / 6 W power-delivery = the 60 W budget)

  **Estimated** (and swept, because it is an assumption)
    - how each die's total splits between its macros and everything else.
      `--phy-share` is that split; the report carries a sensitivity sweep over
      it rather than a single number.

  **Still missing** (`critical_review.md` item 17)
    - structure *inside* a macro or inside the logic region. The submodel study
      measured that this is worth up to +36 C, so the map here is a floor, not
      a resolution. That is what an OpenROAD run would supply.

Orientation matters and has bitten this repository before: DEF places the
lower-left of the *oriented* bounding box, so a 900 x 600 macro placed E covers
600 x 900 of die. `canonical.footprint_um` owns that rule and is used here
rather than re-derived -- the last time it was re-derived, two macros silently
overlapped.

Run
---
    python floorplan_power.py              # writes reports/floorplan_power.json
    python floorplan_power.py --verify     # assertions only
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

from trust_guard import ReferenceCascade, build_context               # noqa: E402
from pareto_search import build_power_maps, GRID, SUB, N_SUB          # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"
sys.path.insert(0, str(REPO_ROOT))

from integrations.canonical import load_design, footprint_um          # noqa: E402

# Which solver layer each die lands on, for the 5-layer stack the reference
# solver is configured with (Die / Hybrid_Bond / Die / C4_BGA / Package).
DIE_LAYER = {"CXL_Switch_Logic": 0, "SRAM_Search_Die": 2,
             "Power_Delivery_Die": 4}


def rasterise(design, nx: int, ny: int, layers: int, phy_share: float = 0.45,
              die_w_um: float | None = None) -> dict:
    """The design record as a power map, watts conserved exactly.

    `phy_share` is the fraction of a die's power that sits in its macros; the
    rest spreads over the die area those macros do not cover. It is the one
    number here with no basis in the record, which is why the caller sweeps it.
    """
    if not 0.0 <= phy_share <= 1.0:
        raise ValueError("phy_share must be a fraction")
    dies = {d.name: d for d in design.dies}
    die_w = die_w_um or max(d.width_um for d in design.dies)
    die_h = die_w_um or max(d.height_um for d in design.dies)

    q = np.zeros((layers, ny, nx))
    detail = {}
    for name, die in dies.items():
        layer = DIE_LAYER.get(name)
        if layer is None or layer >= layers or die.power_w <= 0.0:
            continue
        macros = [m for m in design.macros if m.die == name]
        # The die's own footprint inside the (larger) domain, centred.
        dx0 = (die_w - die.width_um) / 2.0
        dy0 = (die_h - die.height_um) / 2.0

        macro_mask = np.zeros((ny, nx), dtype=bool)
        for m in macros:
            w, h = footprint_um(m.size_um, m.orient)
            x0, y0 = m.origin_um[0] + dx0, m.origin_um[1] + dy0
            i0 = int(np.floor(x0 / die_w * nx))
            j0 = int(np.floor(y0 / die_h * ny))
            i1 = max(i0 + 1, int(np.ceil((x0 + w) / die_w * nx)))
            j1 = max(j0 + 1, int(np.ceil((y0 + h) / die_h * ny)))
            macro_mask[np.clip(j0, 0, ny):np.clip(j1, 0, ny),
                       np.clip(i0, 0, nx):np.clip(i1, 0, nx)] = True

        die_mask = np.zeros((ny, nx), dtype=bool)
        di0 = int(np.floor(dx0 / die_w * nx))
        dj0 = int(np.floor(dy0 / die_h * ny))
        di1 = max(di0 + 1, int(np.ceil((dx0 + die.width_um) / die_w * nx)))
        dj1 = max(dj0 + 1, int(np.ceil((dy0 + die.height_um) / die_h * ny)))
        die_mask[np.clip(dj0, 0, ny):np.clip(dj1, 0, ny),
                 np.clip(di0, 0, nx):np.clip(di1, 0, nx)] = True
        macro_mask &= die_mask
        rest_mask = die_mask & ~macro_mask

        share = phy_share if macros else 0.0
        if macro_mask.any() and share > 0.0:
            q[layer][macro_mask] += die.power_w * share / macro_mask.sum()
        remainder = die.power_w * (1.0 - share) if macro_mask.any() \
            else die.power_w
        if rest_mask.any():
            q[layer][rest_mask] += remainder / rest_mask.sum()
        elif die_mask.any():
            q[layer][die_mask] += remainder / die_mask.sum()

        detail[name] = {
            "layer": layer, "power_w": die.power_w, "n_macros": len(macros),
            "macro_cells": int(macro_mask.sum()),
            "die_cells": int(die_mask.sum()),
            "die_area_fraction_of_domain": float(die_mask.mean()),
            "macro_area_fraction_of_die": float(macro_mask.sum()
                                                / max(die_mask.sum(), 1)),
        }
    return {"q": q, "per_die": detail, "phy_share": phy_share,
            "domain_um": (die_w, die_h)}


def concentration(q_layer: np.ndarray) -> dict:
    """How unevenly the power is spread -- the statistics an OpenROAD run would
    also produce, so the two are directly comparable."""
    lit = q_layer[q_layer > 0]
    if lit.size == 0:
        return {}
    total = float(lit.sum())
    order = np.sort(lit)[::-1]
    cum = np.cumsum(order) / total
    frac_cells = np.arange(1, order.size + 1) / q_layer.size

    def area_for(p: float) -> float:
        i = int(np.searchsorted(cum, p))
        return float(frac_cells[min(i, frac_cells.size - 1)])

    return {"peak_to_mean": float(lit.max() / lit.mean()),
            "peak_to_die_mean": float(lit.max() / (total / q_layer.size)),
            "active_area_fraction": float(lit.size / q_layer.size),
            "area_holding_50pct_power": area_for(0.5),
            "area_holding_90pct_power": area_for(0.9)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--nx", type=int, default=64)
    ap.add_argument("--refine", type=int, default=1,
                    help="solver mesh refinement relative to --nx")
    ap.add_argument("--phy-share", type=float, default=0.45)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/floorplan_power.json"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    total_w = float(cfg.get("max_power_budget_w", 60.0))
    layers = int(cfg["voxel_stack_params"]["layers"])
    _, cascade = build_context(Path(args.config))

    design = load_design()
    built = rasterise(design, args.nx, args.nx, layers, args.phy_share)
    q = built["q"]

    # The solver mesh: the map is already at nx, so refine only in z.
    sol = cascade.ref.solve(nx=args.nx, ny=args.nx, refine_z=2, power_map=
                            _to_mesh(q, cascade, args.nx, args.refine))
    peak = float(sol.t_field_c[0].max())

    # The abstraction the search has been using, same total watts, same mesh.
    rng = np.random.default_rng(0)
    abstract = build_power_maps(np.array([[5, 4, 11, 3, 8, 7, 10, 11, 1, 9]],
                                         dtype=float),
                                total_w * 0.75, total_w * 0.25, layers)[0].numpy()
    abstract_up = np.repeat(np.repeat(abstract, args.nx // GRID, axis=1),
                            args.nx // GRID, axis=2) / (args.nx // GRID) ** 2
    sol_abs = cascade.ref.solve(nx=args.nx, ny=args.nx, refine_z=2,
                                power_map=_to_mesh(abstract_up, cascade,
                                                   args.nx, args.refine))
    peak_abs = float(sol_abs.t_field_c[0].max())

    sweep = []
    for share in (0.2, 0.35, 0.45, 0.6, 0.8):
        b = rasterise(design, args.nx, args.nx, layers, share)
        s = cascade.ref.solve(nx=args.nx, ny=args.nx, refine_z=2,
                              power_map=_to_mesh(b["q"], cascade, args.nx,
                                                 args.refine))
        sweep.append({"phy_share": share,
                      "peak_c": float(s.t_field_c[0].max()),
                      **concentration(b["q"][0])})

    doc = {
        "question": ("what does the temperature look like on the floorplan the "
                     "DEF emitter actually carries, rather than on the search's "
                     "abstraction?"),
        "source": "integrations/canonical.py (the record DEF/LEF is emitted from)",
        "real": {"macros": len(design.macros),
                 "cells": sorted({m.cell for m in design.macros}),
                 "dies": {d.name: {"mm": [d.width_um / 1e3, d.height_um / 1e3],
                                   "power_w": d.power_w} for d in design.dies},
                 "total_power_w": sum(d.power_w for d in design.dies)},
        "estimated": {"phy_share": args.phy_share,
                      "meaning": "fraction of each die's power inside its macros",
                      "swept": [r["phy_share"] for r in sweep]},
        "mesh": {"nx": args.nx, "cell_um": built["domain_um"][0] / args.nx},
        "per_die": built["per_die"],
        "peak_c": {"floorplan": peak, "search_abstraction": peak_abs,
                   "delta_c": peak - peak_abs},
        "concentration": {"floorplan": concentration(q[0]),
                          "search_abstraction": concentration(abstract_up[0])},
        "phy_share_sweep": sweep,
        "caveats": [
            "no structure inside a macro or inside the logic region -- that is "
            "critical_review.md item 17, worth up to +36 C per the submodel "
            "study, and is what an OpenROAD run would supply",
            "the power split between macros and the rest is an estimate, which "
            "is why it is swept rather than quoted",
            "the three dies are mapped onto solver layers 0/2/4; the stack is "
            "the golden config's, not a re-derivation of the record's",
        ],
    }
    print_report(doc)
    ok = _assert_behaves(doc, q, design)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


def _to_mesh(q: np.ndarray, cascade: ReferenceCascade, nx: int, refine: int):
    """Spread a [layers, ny, nx] map over the solver's z-cells."""
    from trust_guard import expand_power_map
    a, b, mesh = cascade.ref.assemble(nx, nx, 2)
    return expand_power_map(q, 1, mesh["layer_of"])


def print_report(doc: dict) -> None:
    r, p = doc["real"], doc["peak_c"]
    print(f"🗺  Floorplan power map: {r['macros']} macros "
          f"({', '.join(r['cells'])}), {r['total_power_w']:.0f} W over "
          f"{len(r['dies'])} dies, {doc['mesh']['cell_um']:.0f} um cells\n")
    for name, d in doc["per_die"].items():
        print(f"    {name:22} layer {d['layer']}  {d['power_w']:5.1f} W  "
              f"{d['n_macros']:2d} macros covering "
              f"{d['macro_area_fraction_of_die']:5.1%} of a die that is "
              f"{d['die_area_fraction_of_domain']:5.1%} of the domain")
    print(f"\n  peak Tj on the floorplan     : {p['floorplan']:7.2f} C")
    print(f"  peak Tj on the abstraction   : {p['search_abstraction']:7.2f} C "
          f"({p['delta_c']:+.2f} C)")
    c = doc["concentration"]
    print(f"\n  {'':28} {'floorplan':>11} {'abstraction':>12}")
    for k in ("peak_to_die_mean", "active_area_fraction",
              "area_holding_50pct_power", "area_holding_90pct_power"):
        print(f"  {k:28} {c['floorplan'].get(k, float('nan')):11.3f} "
              f"{c['search_abstraction'].get(k, float('nan')):12.3f}")
    print(f"\n  sensitivity to the one estimate (power inside macros):")
    for row in doc["phy_share_sweep"]:
        print(f"    {row['phy_share']:4.0%} in macros -> peak "
              f"{row['peak_c']:7.2f} C, peak/mean "
              f"{row['peak_to_die_mean']:5.2f}")


def _assert_behaves(doc: dict, q: np.ndarray, design) -> bool:
    ok = True
    total = float(q.sum())
    want = sum(d.power_w for d in design.dies
               if DIE_LAYER.get(d.name, 99) < q.shape[0])
    if abs(total - want) > 1e-6:
        print(f"\n  ❌ the map carries {total:.4f} W, the record says "
              f"{want:.4f} W: rasterising lost power.")
        ok = False
    peaks = [r["peak_c"] for r in doc["phy_share_sweep"]]
    if not all(a <= b + 1e-9 for a, b in zip(peaks, peaks[1:])):
        print("\n  ❌ concentrating more power into the macros did not raise "
              "the peak monotonically.")
        ok = False
    if ok:
        print("\n  ✅ watts conserved against the design record, and the peak "
              "responds monotonically to the one estimated parameter.")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
