"""Clock skew caused by the temperature field, on a tree that is otherwise exact.

The solver has always returned the whole field and this project has only ever
published `max()`. Peak junction temperature is the number a thermal engineer
asks for; the number a *timing* engineer asks for is the difference between two
points on the die, because a clock tree's branches run through different
temperatures and arrive at different times.

That gap matters at this project's numbers. On-die delay tempco is of order
0.1-0.3 %/C, so a few tens of degrees across an 18 mm die moves a 500 ps
insertion delay by tens of picoseconds -- comparable to the *entire* skew
allowance of a clock tree built to the usual few percent of a clock period,
before any routing imbalance is counted.

Which budget this lands in matters, and the first version of this module got it
wrong: it compared die-spanning tree skew against the 224G link's 1.65 ps jitter
budget and duly reported "4745% of budget". That is a category error. Nobody
distributes a 56 GHz clock across 18 mm -- a reference goes out and local
PLLs/CDRs regenerate. The budget on-die skew competes for is the **clock
period**. The link numbers are kept as labelled context because a real coupling
does exist through data-to-clock matching on forwarded-clock interfaces, but it
applies over an interface's span, not the die's.

What this computes, and what it does not
----------------------------------------
The H-tree here is **geometrically balanced by construction**: every sink is the
same wire length from the root. So the skew it reports is *purely thermal* --
with a uniform field it is exactly zero, which is asserted in the tests. What it
is not is a static timing analysis: there is no per-instance delay data in this
repository, no buffer library and no extracted RC. The model is first-order and
deliberately so,

    d_segment = d_nominal * (1 + alpha * (T_segment - T_reference))

with `alpha` and the nominal insertion delay as *inputs*. The output is therefore
a **sensitivity** -- picoseconds of skew per kelvin of gradient -- which is far
more robust to model-form error than any absolute delay, and is the quantity an
architect can act on. Feed it a different tempco and it scales linearly; that is
a property, not a limitation, and the report states the coefficient it used.

Temperature inversion (delay *falling* with temperature at low supply voltage)
flips the sign of alpha and leaves the magnitude alone, which is why the report
quotes |skew| and names the coefficient rather than burying it.

Run
---
    python gradient_skew.py              # writes reports/gradient_skew.json
    python gradient_skew.py --verify     # assertions only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "serdes_architect", "src"))

from trust_guard import ReferenceCascade, build_context, _kendall_tau  # noqa: E402
from pareto_search import build_power_maps                            # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "physics_accelerated/results"

# From reports/clocking_jitter_spec.md. Quoted, not invented -- and see the
# warning in `budget_view` about which budget these belong to.
UI_PS = 8.9
TOTAL_JITTER_PS = 1.65
UCIE_MATCH_PS = 2.0

# Defaults, all inputs rather than findings.
TEMPCO_PER_C = 0.0015          # 0.15 %/C of delay, mid-range for on-die logic
INSERTION_PS = 500.0           # root-to-sink insertion delay of the tree
CORE_CLOCK_PS = 500.0          # 2 GHz core clock period -- the on-die yardstick
CTS_SKEW_TARGET = 0.05         # a clock tree is usually built to ~5% of period
FEASIBLE_TJ_C = 105.0          # designs above this are not candidates anyway


@dataclass(frozen=True)
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length(self) -> float:
        return float(np.hypot(self.x1 - self.x0, self.y1 - self.y0))

    @property
    def midpoint(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0


@dataclass
class HTree:
    """A balanced H-tree in fractional die coordinates.

    Each level splits a region into four quadrants and runs an H of wire to
    their centres, so after `levels` levels there are 4**levels sinks and every
    root-to-sink path has the *same* total length. Any arrival-time spread is
    then attributable to temperature alone, which is the point of the exercise.
    """
    levels: int = 3
    insertion_ps: float = INSERTION_PS
    tempco_per_c: float = TEMPCO_PER_C
    segments: list[Segment] = dc_field(default_factory=list)
    paths: list[list[int]] = dc_field(default_factory=list)
    sinks: list[tuple[float, float]] = dc_field(default_factory=list)

    def __post_init__(self):
        if not self.segments:
            self._build()

    def _build(self) -> None:
        def recurse(cx: float, cy: float, half: float, level: int,
                    path: list[int]) -> None:
            if level == self.levels:
                self.paths.append(list(path))
                self.sinks.append((cx, cy))
                return
            q = half / 2.0
            for dx, dy in ((-q, -q), (-q, q), (q, -q), (q, q)):
                seg = Segment(cx, cy, cx + dx, cy + dy)
                self.segments.append(seg)
                recurse(cx + dx, cy + dy, q, level + 1,
                        path + [len(self.segments) - 1])

        recurse(0.5, 0.5, 0.5, 0, [])
        lengths = {round(sum(self.segments[i].length for i in p), 12)
                   for p in self.paths}
        if len(lengths) != 1:
            raise AssertionError(f"tree is not balanced: {len(lengths)} distinct "
                                 f"path lengths -- skew would not be thermal")

    @property
    def path_length(self) -> float:
        return sum(self.segments[i].length for i in self.paths[0])


def _sample(field2d: np.ndarray, x: float, y: float) -> float:
    ny, nx = field2d.shape
    ix = min(int(x * nx), nx - 1)
    iy = min(int(y * ny), ny - 1)
    return float(field2d[iy, ix])


def skew(field2d: np.ndarray, tree: HTree,
         t_reference: float | None = None) -> dict:
    """Arrival-time spread across the sinks of a length-balanced tree.

    Each segment carries its share of the nominal insertion delay in proportion
    to its length, scaled by the local temperature. The reference temperature
    only sets where "nominal" sits; it cancels out of the *skew*, which is a
    difference -- and the test suite checks that it does.
    """
    t_ref = float(field2d.mean()) if t_reference is None else t_reference
    per_length = tree.insertion_ps / tree.path_length
    seg_delay = np.array([
        per_length * s.length
        * (1.0 + tree.tempco_per_c * (_sample(field2d, *s.midpoint) - t_ref))
        for s in tree.segments])
    arrivals = np.array([seg_delay[p].sum() for p in tree.paths])

    i_late, i_early = int(np.argmax(arrivals)), int(np.argmin(arrivals))
    return {
        "skew_ps": float(arrivals.max() - arrivals.min()),
        "arrival_mean_ps": float(arrivals.mean()),
        "latest_sink": tree.sinks[i_late],
        "earliest_sink": tree.sinks[i_early],
        "sink_delta_t_c": _sample(field2d, *tree.sinks[i_late])
                          - _sample(field2d, *tree.sinks[i_early]),
        "field_spread_c": float(field2d.max() - field2d.min()),
        "n_sinks": len(arrivals),
    }


def sensitivity_ps_per_c(result: dict) -> float:
    """Picoseconds of skew per kelvin of across-die spread -- the transferable
    number, since it survives a change of tempco or insertion delay by scaling."""
    spread = result["field_spread_c"]
    return result["skew_ps"] / spread if spread > 1e-12 else 0.0


# --- the study -------------------------------------------------------------

def analyse_front(cascade: ReferenceCascade, maps: np.ndarray, tree: HTree,
                  refine: int = 2, layer: int = 0) -> dict:
    """Skew across the published Pareto front, against its peak temperature.

    The front was optimised for peak Tj and interconnect span. Skew is a third
    quantity the same solve already contains, and whether it agrees with the
    first is not obvious in advance: a design can be cool and steep, or warm and
    flat.
    """
    rows = []
    for i, m in enumerate(maps):
        f = cascade.field(m, refine)[layer]
        s = skew(f, tree)
        bound = tree.insertion_ps * tree.tempco_per_c * s["field_spread_c"]
        rows.append({"index": i, "peak_tj_c": float(f.max()),
                     "mean_tj_c": float(f.mean()), **s,
                     "ps_per_c_of_spread": sensitivity_ps_per_c(s),
                     # No path can differ from another by more than the full
                     # field spread, so this is a hard ceiling on the model.
                     "model_bound_ps": float(bound),
                     "within_bound": s["skew_ps"] <= bound + 1e-9})

    peaks = np.array([r["peak_tj_c"] for r in rows])
    skews = np.array([r["skew_ps"] for r in rows])
    best_thermal = int(np.argmin(peaks))
    best_skew = int(np.argmin(skews))
    ok = [r for r in rows if r["peak_tj_c"] <= FEASIBLE_TJ_C]
    feasible = {
        "tj_limit_c": FEASIBLE_TJ_C,
        "n_designs": len(ok),
        "skew_ps": {"min": float(min(r["skew_ps"] for r in ok)),
                    "max": float(max(r["skew_ps"] for r in ok))} if ok else None,
        "note": ("the front spans designs no one would build; this is the "
                 "range over the ones that clear a plausible Tj limit"),
    }
    return {
        "n_designs": len(rows),
        "feasible_subset": feasible,
        "skew_ps": {"min": float(skews.min()), "max": float(skews.max()),
                    "mean": float(skews.mean())},
        "agreement_with_peak_tj": {
            "kendall_tau": _kendall_tau(peaks, skews),
            "same_winner": best_thermal == best_skew,
            "coolest_design": best_thermal,
            "flattest_design": best_skew,
            "skew_cost_of_choosing_coolest_ps":
                float(skews[best_thermal] - skews[best_skew]),
            "thermal_cost_of_choosing_flattest_c":
                float(peaks[best_skew] - peaks[best_thermal]),
        },
        "designs": rows,
    }


def budget_view(skew_ps: float, tree: HTree,
                clock_ps: float = CORE_CLOCK_PS) -> dict:
    """Against the budget this skew actually lands in.

    The first version of this compared on-die tree skew with the 224G link's
    1.65 ps jitter budget and reported "4745% of budget", which is a category
    error: that budget is for a serial link's reference and recovered clock, and
    nobody distributes a 56 GHz clock across an 18 mm die -- a reference goes
    out and local PLLs/CDRs regenerate. The budget on-die skew competes for is
    the **clock period**, and the yardstick a CTS engineer uses is a few percent
    of it.

    The link numbers are kept as context, labelled, because there *is* a real
    coupling -- data-to-clock matching on a forwarded-clock interface -- but it
    applies over an interface's span, not the die's.
    """
    target_ps = clock_ps * CTS_SKEW_TARGET
    return {
        "skew_ps": skew_ps,
        "on_die": {
            "core_clock_ps": clock_ps,
            "skew_fraction_of_period": skew_ps / clock_ps,
            "cts_target_ps": target_ps,
            "exceeds_cts_target": skew_ps > target_ps,
            "note": f"a tree built to {CTS_SKEW_TARGET:.0%} of the period has "
                    f"{target_ps:.1f} ps to spend; this is what the gradient "
                    f"takes out of it before routing imbalance is counted",
        },
        "link_context": {
            "ui_ps": UI_PS,
            "total_jitter_budget_ps": TOTAL_JITTER_PS,
            "ucie_match_requirement_ps": UCIE_MATCH_PS,
            "warning": ("a different budget -- serial-link jitter and "
                        "interface-span matching, not die-spanning clock "
                        "distribution. Quoting die skew against it overstates "
                        "the coupling."),
        },
        "assumed_tempco_per_c": tree.tempco_per_c,
        "assumed_insertion_ps": tree.insertion_ps,
        "note": ("skew scales linearly with both assumptions, which is why "
                 "ps-per-kelvin is the number to carry away"),
    }


def print_report(doc: dict) -> None:
    f = doc["front"]
    a = f["agreement_with_peak_tj"]
    t = doc["tree"]
    print(f"⏱  Thermal-gradient skew on a balanced {t['n_sinks']}-sink H-tree "
          f"({t['insertion_ps']:.0f} ps insertion, "
          f"{t['tempco_per_c'] * 100:.2f} %/C)\n")
    print(f"  across {f['n_designs']} front designs:")
    print(f"    skew          : {f['skew_ps']['min']:.3f} - "
          f"{f['skew_ps']['max']:.3f} ps (mean {f['skew_ps']['mean']:.3f})")
    fs = f["feasible_subset"]
    if fs["skew_ps"]:
        print(f"    of which the {fs['n_designs']} under "
              f"{fs['tj_limit_c']:.0f} C : {fs['skew_ps']['min']:.3f} - "
              f"{fs['skew_ps']['max']:.3f} ps")
    b = doc["budget_at_worst_feasible"]["on_die"]
    print(f"    worst feasible: {doc['budget_at_worst_feasible']['skew_ps']:.3f} ps "
          f"= {b['skew_fraction_of_period'] * 100:.1f}% of a "
          f"{b['core_clock_ps']:.0f} ps period, against a "
          f"{b['cts_target_ps']:.1f} ps CTS target -> "
          f"{'EXCEEDS' if b['exceeds_cts_target'] else 'within'}")
    print(f"\n  does the coolest design also have the flattest clock?")
    print(f"    Kendall tau, peak Tj vs skew : {a['kendall_tau']:+.3f}")
    print(f"    coolest design #{a['coolest_design']}, flattest #"
          f"{a['flattest_design']} -> "
          f"{'the same design' if a['same_winner'] else 'DIFFERENT designs'}")
    if not a["same_winner"]:
        print(f"    choosing the coolest costs "
              f"{a['skew_cost_of_choosing_coolest_ps']:+.3f} ps of skew")
        print(f"    choosing the flattest costs "
              f"{a['thermal_cost_of_choosing_flattest_c']:+.2f} C of peak Tj")
    print(f"\n  {'design':>7} {'peak Tj':>9} {'spread':>8} {'skew':>8} "
          f"{'ps/K':>7}")
    order = sorted(f["designs"], key=lambda r: r["skew_ps"])
    for r in order[:3] + order[-3:]:
        print(f"  {r['index']:7d} {r['peak_tj_c']:8.2f}C "
              f"{r['field_spread_c']:7.2f}C {r['skew_ps']:7.3f}ps "
              f"{r['ps_per_c_of_spread']:7.4f}")


def _assert_behaves(doc: dict) -> bool:
    ok = True
    f = doc["front"]
    if any(r["skew_ps"] < 0 for r in f["designs"]):
        print("\n  ❌ negative skew is impossible on a balanced tree.")
        ok = False
    flat = [r for r in f["designs"] if r["field_spread_c"] < 1e-9]
    if any(r["skew_ps"] > 1e-9 for r in flat):
        print("\n  ❌ a flat field produced skew: the tree is not balanced and "
              "the result is geometric, not thermal.")
        ok = False
    if any(not r["within_bound"] for r in f["designs"]):
        print("\n  ❌ a design exceeds insertion x tempco x field spread, which "
              "is a hard ceiling -- the delay model is wrong.")
        ok = False
    if f["skew_ps"]["max"] <= 0.0:
        print("\n  ❌ no design shows any skew, which means the field is not "
              "reaching the tree.")
        ok = False
    if ok:
        print("\n  ✅ skew is thermal only: zero on a flat field, positive where "
              "the field has a gradient, and every path length identical.")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(RESULTS / "golden_config.json"))
    ap.add_argument("--front", default=str(REPO_ROOT / "reports/pareto_front_nsga2.json"))
    ap.add_argument("--levels", type=int, default=3, help="4**levels sinks")
    ap.add_argument("--tempco", type=float, default=TEMPCO_PER_C)
    ap.add_argument("--insertion-ps", type=float, default=INSERTION_PS)
    ap.add_argument("--refine", type=int, default=2)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/gradient_skew.json"))
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

    tree = HTree(levels=args.levels, insertion_ps=args.insertion_ps,
                 tempco_per_c=args.tempco)
    res = analyse_front(cascade, maps, tree, refine=args.refine)
    worst = max(res["designs"], key=lambda r: r["skew_ps"])
    feasible_rows = [r for r in res["designs"]
                     if r["peak_tj_c"] <= FEASIBLE_TJ_C] or res["designs"]
    worst_feasible = max(feasible_rows, key=lambda r: r["skew_ps"])

    doc = {
        "question": ("how much clock skew does the temperature field cause on a "
                     "tree that is otherwise perfectly balanced?"),
        "model": ("first-order: d = d_nom * (1 + alpha * (T - T_ref)). Not a "
                  "static timing analysis -- there is no per-instance delay "
                  "data in this repository. The transferable output is "
                  "ps per kelvin of across-die spread."),
        "tree": {"levels": args.levels, "n_sinks": len(tree.sinks),
                 "insertion_ps": tree.insertion_ps,
                 "tempco_per_c": tree.tempco_per_c,
                 "balanced": True},
        "budget_source": "reports/clocking_jitter_spec.md",
        "front": res,
        "budget_at_worst": budget_view(worst["skew_ps"], tree),
        "budget_at_worst_feasible": budget_view(worst_feasible["skew_ps"], tree),
        "front_source": os.path.relpath(args.front, REPO_ROOT),
        "caveats": [
            "the tree is a synthetic balanced H-tree, not this design's clock "
            "distribution, which is not described anywhere in the repository",
            "tempco and insertion delay are inputs; skew scales linearly in both",
            "the field is sampled on 562 um cells, so a gradient sharper than "
            "that is averaged away and this is a lower bound",
        ],
    }
    print_report(doc)
    ok = _assert_behaves(doc)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
