"""Where does the memory go? Stacked, PoP, or beside the SoC.

This is the first study in the repository that treats **memory junction
temperature as the decision variable** rather than a diagnostic. It exists
because DRAM is the part of a module with a thermal *knee* rather than a slope:
retention falls roughly by half per 10 C, and above ~85 C a device runs in
extended temperature range with refresh at double rate. A knee makes an
architectural question decidable -- you are on one side of it or the other --
where a smooth penalty would not.

Three attach options, all on the same footprint, cooling and ambient, so only
the heat path differs:

    stacked    memory on logic through a 5 um Cu-Cu hybrid bond (k = 300)
    pop        memory above logic across a mold gap (k ~ 0.8), package-on-package
    adjacent   memory *beside* logic at the same height, coupled through the
               substrate -- which needs in-plane material heterogeneity, and is
               why `Region` exists

What is computed, and why it is exact rather than sampled: the conduction
problem is linear with fixed boundary conditions, so memory Tj is an **affine
function of the power dissipated**. Two solves give the whole line. That yields
the number an architect actually wants --

    dTj_memory / dP_logic   [C/W]      thermal coupling between the two dies
    P_logic at the knee     [W]        the SoC budget this attach option affords

-- exactly, not by sweeping. The script asserts the linearity it relies on.

Caveats, stated because the absolute numbers depend on them: the mold and PoP
gap thicknesses are representative, not a datasheet; the cooling is this
project's liquid cold plate (h = 8000 W/m2K), which is a module, not a phone;
and 85 C is used as a general DRAM knee, not a quotation from any JEDEC
document. The comparison between options, and its robustness under the
`rank_churn.py` perturbations, is what this is for.

Run
---
    python memory_attach.py                # writes reports/memory_attach.json
    python memory_attach.py --verify       # assertions only
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

from thermal_reference import (Boundary, Layer, Region,              # noqa: E402
                               ThermalReference)

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"

# Decision thresholds. General DRAM behaviour, configurable, and deliberately
# not presented as a quotation from a JEDEC document.
KNEE_C = 85.0          # above this, extended temperature range: refresh x2
LIMIT_C = 105.0        # above this, most devices are out of spec entirely

MOLD_K = 0.8           # epoxy mold compound
SUBSTRATE_K = 0.8      # organic substrate, in-plane average
LID_K = 400.0          # copper lid / integrated heat spreader


@dataclass
class Attach:
    name: str
    ref: ThermalReference
    logic_region: str | None      # None -> the logic is a whole layer
    memory_region: str | None
    logic_layer: int
    memory_layer: int
    description: str


H_PLATE, H_BOARD = 8000.0, 50.0


def _bc(cool_from: str = "logic") -> Boundary:
    """This project's cooling coefficients, on one side or the other.

    Which face the cold plate sits on is not a detail: in this stack the memory
    reaches the plate *through* the logic die, so an insulating gap between them
    protects the memory from the logic and blocks its own escape at the same
    time. Flipping the plate to the memory side reverses that, and a study that
    reported only one orientation would generalise a module result to a phone.
    """
    if cool_from not in ("logic", "memory"):
        raise ValueError("cool_from must be 'logic' or 'memory'")
    top = H_PLATE if cool_from == "logic" else H_BOARD
    return Boundary(h_top_w_m2k=top, h_bottom_w_m2k=H_PLATE + H_BOARD - top,
                    h_side_w_m2k=0.0, t_ambient_c=25.0)


def _assemble(name: str, spec: list, w_m: float, d_m: float, cool_from: str,
              lid_um: float, regions_at: str | None = None,
              regions: list | None = None, description: str = "") -> Attach:
    """Build an Attach from a (layer_name, thickness_um, k) list, optionally
    with a copper lid on the cold-plate side.

    A lid is not decoration: it is the only lateral path a die surrounded by
    mold has. Leaving it out of one option and not the others would decide the
    comparison by stackup choice rather than by attach -- the same class of
    unfairness that once put +52 C on the shattered-macro claim.
    """
    items = list(spec)
    if lid_um > 0.0:
        items.insert(0, ("Lid", lid_um, LID_K))
    layers = [Layer(n, t * 1e-6, k) for n, t, k in items]
    names = [n for n, _, _ in items]
    shift = 1 if lid_um > 0.0 else 0
    regs = [Region(r.layer + shift, r.name, r.k_w_mk, r.x0, r.y0, r.x1, r.y1,
                   r.power_w) for r in (regions or [])]
    ref = ThermalReference(layers, w_m, d_m, _bc(cool_from), regions=regs)
    if regions_at is not None:
        li = mi = names.index(regions_at)
        lr, mr = "logic", "memory"
    else:
        li, mi = names.index("Logic_Die"), names.index("Memory_Die")
        lr = mr = None
    return Attach(name, ref, lr, mr, li, mi, description)


def stacked(w_m: float, d_m: float, cool_from: str = "logic",
            lid_um: float = 0.0) -> Attach:
    return _assemble("stacked",
                     [("Logic_Die", 50.0, 140.0), ("Hybrid_Bond", 5.0, 300.0),
                      ("Memory_Die", 50.0, 140.0), ("C4_BGA", 40.0, 50.0),
                      ("Package", 775.0, 100.0)],
                     w_m, d_m, cool_from, lid_um,
                     description="memory bonded under the logic die, 5 um Cu-Cu")


def pop(w_m: float, d_m: float, cool_from: str = "logic", lid_um: float = 0.0,
        gap_um: float = 150.0) -> Attach:
    """Package-on-package: the same z-order, a mold gap instead of a bond."""
    return _assemble("pop",
                     [("Logic_Die", 50.0, 140.0), ("Mold_Gap", gap_um, MOLD_K),
                      ("Memory_Die", 50.0, 140.0), ("C4_BGA", 40.0, 50.0),
                      ("Package", 775.0, 100.0)],
                     w_m, d_m, cool_from, lid_um,
                     description=f"memory above logic across a {gap_um:g} um "
                                 f"mold gap")


def adjacent(w_m: float, d_m: float, cool_from: str = "logic",
             lid_um: float = 0.0, gap_frac: float = 0.10) -> Attach:
    """Side by side at the same height, coupled through the substrate.

    The die layer is mold everywhere except two silicon patches -- the case a
    per-layer conductivity cannot express at all, and the normal way an LPDDR
    package sits next to an SoC.
    """
    die_w = (1.0 - gap_frac) / 2.0
    regions = [Region(0, "logic", 140.0, 0.0, 0.2, die_w, 0.8),
               Region(0, "memory", 140.0, die_w + gap_frac, 0.2, 1.0, 0.8)]
    return _assemble("adjacent",
                     [("Die_Level", 50.0, MOLD_K), ("Mold_Under", 150.0, MOLD_K),
                      ("Substrate", 200.0, SUBSTRATE_K), ("C4_BGA", 40.0, 50.0),
                      ("Package", 775.0, 100.0)],
                     w_m, d_m, cool_from, lid_um, regions_at="Die_Level",
                     regions=regions,
                     description=f"memory beside logic, gap "
                                 f"{gap_frac * 100:.0f}% of the footprint")


# --- the measurement -------------------------------------------------------

def _model_at(a: Attach, logic_w: float, memory_w: float) -> ThermalReference:
    ref = a.ref
    if a.logic_region is None:
        layers = [Layer(l.name, l.thickness_m, l.k_w_mk,
                        logic_w if i == a.logic_layer else
                        (memory_w if i == a.memory_layer else 0.0), l.n_cells_z)
                  for i, l in enumerate(ref.layers)]
        regions = ref.regions
    else:
        layers = [Layer(l.name, l.thickness_m, l.k_w_mk, 0.0, l.n_cells_z)
                  for l in ref.layers]
        regions = [Region(r.layer, r.name, r.k_w_mk, r.x0, r.y0, r.x1, r.y1,
                          logic_w if r.name == a.logic_region else
                          (memory_w if r.name == a.memory_region else 0.0))
                   for r in ref.regions]
    return ThermalReference(layers, ref.width_m, ref.depth_m, ref.bc,
                            k_lateral_scale=ref.k_lateral_scale, regions=regions)


def _die_cells(a: Attach, sol, nx: int, which: str) -> np.ndarray:
    """Boolean mask over the solved field selecting one die's cells."""
    layer_of = np.repeat(np.arange(len(a.ref.layers)),
                         [max(1, l.n_cells_z * (sol.nz // sum(
                             max(1, x.n_cells_z) for x in a.ref.layers)))
                          for l in a.ref.layers])
    mask = np.zeros(sol.t_field_c.shape, dtype=bool)
    region = a.logic_region if which == "logic" else a.memory_region
    layer = a.logic_layer if which == "logic" else a.memory_layer
    zs = np.where(layer_of == layer)[0]
    if region is None:
        mask[zs] = True
    else:
        r = next(x for x in a.ref.regions if x.name == region)
        mask[np.ix_(zs)] = r.mask(nx, nx)
    return mask


def _affine_law(a: Attach, memory_w: float, nx: int, refine: int,
                probe_w: float = 40.0) -> dict:
    """Per-cell coefficients of T = a + b * P_logic, which is exact.

    The *field* is affine in the load; the *peak* is a max over cells of affine
    functions, so it is convex piecewise-linear and not affine itself -- fitting
    a line to two peak values is wrong wherever the hotspot moves between them,
    which is exactly what happens when the neighbouring die's power changes. So
    the coefficients are kept per cell and every peak below is a max over them.
    """
    s0 = _model_at(a, 0.0, memory_w).solve(nx=nx, ny=nx, refine_z=refine)
    s1 = _model_at(a, probe_w, memory_w).solve(nx=nx, ny=nx, refine_z=refine)
    a0, b0 = s0.t_field_c, (s1.t_field_c - s0.t_field_c) / probe_w
    return {"a": a0, "b": b0, "sol0": s0, "sol1": s1,
            "logic": _die_cells(a, s0, nx, "logic"),
            "memory": _die_cells(a, s0, nx, "memory")}


def _peak(law: dict, which: str, p: float) -> float:
    m = law[which]
    return float((law["a"][m] + law["b"][m] * p).max())


def _crossing(law: dict, which: str, threshold: float) -> float:
    """Smallest logic power at which any cell of this die reaches `threshold`.

    Exact: each cell crosses at (threshold - a_c) / b_c, and the die crosses
    when the first of them does.
    """
    m = law[which]
    av, bv = law["a"][m], law["b"][m]
    hot = bv > 1e-12
    if not hot.any():
        return float("inf")
    p = (threshold - av[hot]) / bv[hot]
    return float(max(0.0, p.min()))


def characterise(a: Attach, memory_w: float, nx: int = 32, refine: int = 2,
                 probe_w: float = 40.0, operating_w: float = 40.0,
                 logic_limit_c: float = 105.0) -> dict:
    """What SoC power this attach option affords before *either* die runs out.

    Reporting only the memory's budget rewards decoupling the dies at any cost
    to the logic -- the `adjacent` option looks unbeatable on memory Tj precisely
    because its logic die is surrounded by mold and heats three times faster.
    The decision metric is therefore the binding one of the two.
    """
    law = _affine_law(a, memory_w, nx, refine, probe_w)
    p_mem_knee = _crossing(law, "memory", KNEE_C)
    p_mem_limit = _crossing(law, "memory", LIMIT_C)
    p_logic = _crossing(law, "logic", logic_limit_c)
    binding = "memory_knee" if p_mem_knee <= p_logic else "logic_limit"

    # dPeak/dP at the operating point: the coefficient of whichever cell is
    # hottest there, which is the meaningful local sensitivity.
    def slope(which: str) -> float:
        m = law[which]
        i = int(np.argmax(law["a"][m] + law["b"][m] * operating_w))
        return float(law["b"][m][i])

    mid = _model_at(a, probe_w / 2.0, memory_w).solve(nx=nx, ny=nx,
                                                      refine_z=refine)
    resid = float(np.abs(law["a"] + law["b"] * (probe_w / 2.0)
                         - mid.t_field_c).max())

    return {
        "attach": a.name,
        "description": a.description,
        "memory_w": memory_w,
        "memory_only_tj_c": _peak(law, "memory", 0.0),
        "logic_tj_per_w": slope("logic"),
        "memory_tj_per_w": slope("memory"),
        "coupling_ratio": slope("memory") / slope("logic") if slope("logic") else None,
        "logic_budget_at_memory_knee_w": p_mem_knee,
        "logic_budget_at_memory_limit_w": p_mem_limit,
        "logic_budget_at_logic_limit_w": p_logic,
        "feasible_logic_w": min(p_mem_knee, p_logic),
        "binding_constraint": binding,
        "field_linearity_residual_c": resid,
        "at_operating_point": {
            "logic_w": operating_w,
            "logic_tj_c": _peak(law, "logic", operating_w),
            "memory_tj_c": _peak(law, "memory", operating_w),
            "die_to_die_delta_c": _peak(law, "logic", operating_w)
                                  - _peak(law, "memory", operating_w)},
    }


def refresh_fixed_point(row: dict, logic_w: float,
                        refresh_multiplier: float = 2.0,
                        refresh_fraction: float = 0.35) -> dict:
    """Does the refresh loop close, or does it run away?

    Above the knee a device refreshes at double rate, so part of the memory's
    own power *doubles* -- which raises its temperature, which can push it
    further above the knee. Two-level model: the refresh share of memory power
    is multiplied when Tj > knee. Crude on purpose; what it produces is a yes/no
    on closure and the margin to the boundary, which is the architectural
    question. A continuous retention model would change the numbers and not the
    structure.
    """
    base_m = row["memory_w"]
    slope_m = row["memory_tj_per_w"]
    t_no_logic = row["memory_only_tj_c"]

    def tj(mem_w: float) -> float:
        # memory self-heating scales with its own power; the logic term is fixed
        return (t_no_logic - 25.0) * (mem_w / base_m) + 25.0 + slope_m * logic_w

    state, history = base_m, []
    for _ in range(50):
        t = tj(state)
        nxt = base_m * (1.0 + refresh_fraction * (refresh_multiplier - 1.0)) \
            if t > KNEE_C else base_m
        history.append({"memory_w": state, "tj_c": t})
        if abs(nxt - state) < 1e-9:
            break
        state = nxt
    final = tj(state)
    return {"logic_w": logic_w, "converged_memory_w": state,
            "memory_tj_c": final, "above_knee": final > KNEE_C,
            "above_limit": final > LIMIT_C,
            "iterations": len(history),
            "closed": len(history) < 50,
            "model": (f"refresh share {refresh_fraction:.0%} of memory power, "
                      f"x{refresh_multiplier:g} above {KNEE_C:g} C")}


def robustness(build, memory_w: float, nx: int, refine: int) -> list[dict]:
    """The same comparison under the perturbations rank_churn.py sweeps.

    An architectural choice that survives +/-50% on the cooling coefficient and
    on lateral spreading does not need a licensed run to be made; one that does
    not, does.
    """
    cases = [("baseline", 1.0, 1.0), ("h_top -50%", 0.5, 1.0),
             ("h_top +50%", 1.5, 1.0), ("k_lateral -50%", 1.0, 0.5),
             ("k_lateral +50%", 1.0, 1.5)]
    out = []
    for name, hs, ks in cases:
        row = {"case": name}
        for a in build():
            bc = Boundary(h_top_w_m2k=a.ref.bc.h_top_w_m2k * hs,
                          h_bottom_w_m2k=a.ref.bc.h_bottom_w_m2k,
                          h_side_w_m2k=a.ref.bc.h_side_w_m2k,
                          t_ambient_c=a.ref.bc.t_ambient_c)
            perturbed = Attach(a.name,
                               ThermalReference(a.ref.layers, a.ref.width_m,
                                                a.ref.depth_m, bc,
                                                k_lateral_scale=ks,
                                                regions=a.ref.regions),
                               a.logic_region, a.memory_region,
                               a.logic_layer, a.memory_layer, a.description)
            c = characterise(perturbed, memory_w, nx=nx, refine=refine)
            row[a.name] = round(c["feasible_logic_w"], 2)
            row[f"{a.name}_binds"] = c["binding_constraint"]
        ranked = sorted((k for k in row if k != "case" and not k.endswith("_binds")),
                        key=lambda k: -row[k])
        row["ranking"] = ranked
        out.append(row)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--memory-w", type=float, default=3.0,
                    help="memory package power, W (LPDDR-class default)")
    ap.add_argument("--logic-w", type=float, default=40.0,
                    help="logic power for the reported operating point")
    ap.add_argument("--nx", type=int, default=32)
    ap.add_argument("--refine", type=int, default=2)
    ap.add_argument("--lid-um", type=float, default=500.0,
                    help="copper lid thickness for the lidded scenarios")
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/memory_attach.json"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    size = cfg["die_hierarchy"]["die_0"]["size_mm"]
    w_m, d_m = size[0] * 1e-3, size[1] * 1e-3

    scenarios = {}
    for cool_from in ("logic", "memory"):
      for lid_um in (0.0, args.lid_um):
        key = f"{cool_from}_side_{'lid' if lid_um else 'bare'}"

        def build(c=cool_from, L=lid_um):
            return [stacked(w_m, d_m, c, L), pop(w_m, d_m, c, L),
                    adjacent(w_m, d_m, c, L)]

        rows = [characterise(a, args.memory_w, nx=args.nx, refine=args.refine,
                             operating_w=args.logic_w)
                for a in build()]
        for r in rows:
            r["refresh_loop"] = refresh_fixed_point(r, args.logic_w)
        scenarios[key] = {
            "cold_plate_on": f"the {cool_from} side",
            "lid_um": lid_um,
            "options": rows,
            "robustness": robustness(build, args.memory_w, args.nx, args.refine),
        }

    rows = scenarios["logic_side_bare"]["options"]
    doc = {
        "question": ("which attach option gives the SoC the most power budget "
                     "before the memory crosses its refresh knee?"),
        "footprint_mm": size,
        "cooling": {"h_top_w_m2k": 8000.0, "h_bottom_w_m2k": 50.0,
                    "t_ambient_c": 25.0,
                    "note": "this project's liquid cold plate, unchanged"},
        "thresholds_c": {"refresh_knee": KNEE_C, "device_limit": LIMIT_C,
                         "note": "general DRAM behaviour, not a JEDEC quotation"},
        "memory_w": args.memory_w,
        "mesh": f"{args.nx}x{args.nx}, refine_z={args.refine}",
        "scenarios": scenarios,
        "caveats": [
            "mold and PoP gap thicknesses are representative, not a datasheet",
            "no in-plane resolution below the cell size, so a hotspot inside "
            "either die is smeared -- the comparison is between heat paths, not "
            "a sign-off temperature",
            "refresh feedback is a two-level model; it answers closure, not "
            "retention",
            "power is spread uniformly over each die, so this compares heat "
            "paths and not floorplans -- the floorplan question is "
            "pareto_search.py",
        ],
    }
    print_report(doc)
    ok = _assert_behaves(doc)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


def print_report(doc: dict) -> None:
    print(f"🧠 Memory attach study: {doc['memory_w']:.1f} W memory, "
          f"{doc['footprint_mm'][0]}x{doc['footprint_mm'][1]} mm, "
          f"knee {doc['thresholds_c']['refresh_knee']:.0f} C\n")
    for key, sc in doc["scenarios"].items():
        lid = (f"{sc['lid_um']:.0f} um Cu lid" if sc["lid_um"] else "no lid")
        head = f"cold plate on {sc['cold_plate_on']}, {lid}"
        print(f"  ── {head} {'─' * max(2, 62 - len(head))}")
        print(f"  {'option':<10} {'Tj_mem/W':>9} {'Tj_logic/W':>11} "
              f"{'coupling':>9} {'mem knee':>9} {'logic max':>10} "
              f"{'feasible':>9}  binds")
        for r in sc["options"]:
            print(f"  {r['attach']:<10} {r['memory_tj_per_w']:8.3f}C "
                  f"{r['logic_tj_per_w']:10.3f}C {r['coupling_ratio']:9.2f} "
                  f"{r['logic_budget_at_memory_knee_w']:8.1f}W "
                  f"{r['logic_budget_at_logic_limit_w']:9.1f}W "
                  f"{r['feasible_logic_w']:8.1f}W  {r['binding_constraint']}")
        op = sc["options"][0]["at_operating_point"]["logic_w"]
        print(f"    at {op:.0f} W of logic:")
        for r in sc["options"]:
            a, f = r["at_operating_point"], r["refresh_loop"]
            print(f"      {r['attach']:<10} logic {a['logic_tj_c']:6.1f} C, "
                  f"memory {a['memory_tj_c']:6.1f} C "
                  f"(delta {a['die_to_die_delta_c']:+.1f}) -> refresh loop "
                  f"{'closes' if f['closed'] else 'RUNS AWAY'}"
                  f"{', above knee' if f['above_knee'] else ''}"
                  f"{', ABOVE LIMIT' if f['above_limit'] else ''}")
        names = [r["attach"] for r in sc["options"]]
        print(f"    feasible logic power under perturbation (W):")
        print(f"      {'case':<16} " + " ".join(f"{n:>10}" for n in names)
              + "   ranking")
        for row in sc["robustness"]:
            print(f"      {row['case']:<16} "
                  + " ".join(f"{row[n]:10.1f}" for n in names)
                  + "   " + " > ".join(row["ranking"]))
        print()


def _assert_behaves(doc: dict) -> bool:
    ok = True
    for cool_from, sc in doc["scenarios"].items():
        for r in sc["options"]:
            if r["field_linearity_residual_c"] > 1e-6:
                print(f"\n  ❌ {cool_from}/{r['attach']}: the field is not affine "
                      f"in power ({r['field_linearity_residual_c']:.2e} C off), "
                      f"so the two-point characterisation is invalid.")
                ok = False
            if r["memory_tj_per_w"] <= 0 or r["logic_tj_per_w"] <= 0:
                print(f"\n  ❌ {cool_from}/{r['attach']}: power does not heat a die.")
                ok = False
            if r["coupling_ratio"] > 1.0 + 1e-9:
                print(f"\n  ❌ {cool_from}/{r['attach']}: logic power heats the "
                      f"memory more than it heats the logic, which is not a "
                      f"heat path.")
                ok = False
        rankings = {tuple(row["ranking"]) for row in sc["robustness"]}
        order = " > ".join(sc["robustness"][0]["ranking"])
        if len(rankings) == 1:
            print(f"  ✅ {cool_from}: {order} holds under every perturbation "
                  f"-- no licensed run needed to choose.")
        else:
            print(f"  ⚠️  {cool_from}: the ordering changes under perturbation "
                  f"({len(rankings)} orders) -- that is a decision a correlated "
                  f"vendor run would settle.")
    orders = [tuple(sc["robustness"][0]["ranking"])
              for sc in doc["scenarios"].values()]
    if len(set(orders)) > 1:
        print("  ↳ and the scenarios disagree with each other, so the cooling "
              "side and the lid decide the attach choice -- not the attach.")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
