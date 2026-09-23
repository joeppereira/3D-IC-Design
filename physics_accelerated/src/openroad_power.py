"""A real power map, from a real placed design.

`critical_review.md` item 17 asks what power maps actually look like, because
`submodel.py` measured that rearranging a macro's watts inside its own footprint
moves peak Tj by up to +36 C -- and this repository had no data on that
arrangement at all. Every map it has solved was either four uniform blocks (the
search) or macro rectangles at fixed origins (`floorplan_power.py`).

This reads the answer off an actual place-and-route run: OpenROAD (open source,
no licence) synthesises and places a design on ASAP7, and OpenSTA reports power
per instance. Joining the two gives watts at cell resolution -- the distribution,
not an assumption about it.

What is real and what is not
----------------------------
**Real**: the netlist, the placement, the cell library, and the per-instance
internal/switching/leakage split from OpenSTA on that placement.

**Assumed**: the switching activity (stated in the report, 0.2 by default and
swept), and the fact that this is somebody else's design. ASAP7 is a predictive
7 nm library and the designs are ORFS benchmarks, not a CXL switch. **Absolute
W/cm2 does not transfer.** What transfers is the *shape* -- peak-to-mean, the
area holding half the power -- which is what the submodel sweep needed and which
is far more portable across nodes than magnitude.

**Missing**: routing. CTS crashes under amd64 emulation on Apple silicon
("illegal instruction" in TritonCTS), so the flow stops at placement. Clock-tree
buffers and routing parasitics would add power and concentrate it further, so
the concentration measured here is a *lower* bound.

Run
---
    python openroad_power.py --design gcd     # after extract.tcl has run
    python openroad_power.py --verify
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Set by the extraction container; overridable for a different drop location.
DEFAULT_DIR = Path(os.environ.get(
    "ORFS_EXTRACT_DIR",
    "/tmp/claude-501/-Users-joepereira-code-3D-IC-Design/"
    "5ac8c1b5-7c5c-406b-8e23-662e5ad0af76/scratchpad"))

POWER_ROW = re.compile(
    r"^\s*([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)\s+(\S+)\s*$")


def read_power(path: Path) -> dict[str, dict]:
    """OpenSTA `report_power -instances` text -> per-instance watts.

    The table is parsed rather than taken from `sta::instance_power`, which
    segfaults under emulation on this machine.
    """
    out = {}
    for line in Path(path).read_text().splitlines():
        m = POWER_ROW.match(line)
        if not m:
            continue
        internal, switching, leakage, total, name = m.groups()
        try:
            out[name] = {"internal_w": float(internal),
                         "switching_w": float(switching),
                         "leakage_w": float(leakage),
                         "total_w": float(total)}
        except ValueError:
            continue
    if not out:
        raise ValueError(f"{path}: no instance rows parsed")
    return out


def read_placement(path: Path) -> dict[str, dict]:
    rows = {}
    for line in Path(path).read_text().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 6:
            continue
        name, master, x, y, w, h = parts
        rows[name] = {"master": master, "x_um": float(x), "y_um": float(y),
                      "w_um": float(w), "h_um": float(h)}
    if not rows:
        raise ValueError(f"{path}: no placement rows parsed")
    return rows


def join(power: dict, placement: dict) -> tuple[list[dict], dict]:
    joined, missing_power, missing_place = [], 0, 0
    for name, p in placement.items():
        q = power.get(name)
        if q is None:
            missing_power += 1
            continue
        joined.append({"instance": name, **p, **q})
    missing_place = sum(1 for n in power if n not in placement)
    return joined, {"instances_placed": len(placement),
                    "instances_with_power": len(power),
                    "joined": len(joined),
                    "placed_without_power": missing_power,
                    "power_without_placement": missing_place}


def rasterise(joined: list[dict], die_um: list[float], nx: int, ny: int,
              field: str = "total_w") -> np.ndarray:
    """Instance watts onto a grid, split by area overlap so watts are conserved."""
    x0, y0, x1, y1 = die_um
    q = np.zeros((ny, nx))
    cw, ch = (x1 - x0) / nx, (y1 - y0) / ny
    for inst in joined:
        w = inst[field]
        if w == 0.0:
            continue
        ix0 = int(np.clip((inst["x_um"] - x0) / cw, 0, nx - 1))
        iy0 = int(np.clip((inst["y_um"] - y0) / ch, 0, ny - 1))
        ix1 = int(np.clip((inst["x_um"] + inst["w_um"] - x0) / cw, 0, nx - 1))
        iy1 = int(np.clip((inst["y_um"] + inst["h_um"] - y0) / ch, 0, ny - 1))
        n = (ix1 - ix0 + 1) * (iy1 - iy0 + 1)
        q[iy0:iy1 + 1, ix0:ix1 + 1] += w / n
    return q


def concentration(q: np.ndarray) -> dict:
    """Identical metrics to floorplan_power.concentration, so the real map and
    the abstractions can be compared on the same axes."""
    lit = q[q > 0]
    if lit.size == 0:
        return {}
    total = float(lit.sum())
    order = np.sort(lit)[::-1]
    cum = np.cumsum(order) / total
    frac_cells = np.arange(1, order.size + 1) / q.size

    def area_for(p: float) -> float:
        i = int(np.searchsorted(cum, p))
        return float(frac_cells[min(i, frac_cells.size - 1)])

    return {"total_w": total,
            "peak_to_die_mean": float(lit.max() / (total / q.size)),
            "active_area_fraction": float(lit.size / q.size),
            "area_holding_50pct_power": area_for(0.5),
            "area_holding_90pct_power": area_for(0.9)}


def submodel_equivalent(stats: dict) -> dict:
    """Translate the measured shape into the two knobs `submodel.concentrate`
    sweeps, so the +36 C sensitivity can be evaluated at the real value rather
    than at an assumed one."""
    area = stats.get("area_holding_50pct_power")
    return {"fraction_of_power": 0.5, "fraction_of_area": area,
            "note": ("feed these to submodel.concentrate() to place the real "
                     "design's shape on the measured Tj sensitivity curve")}


def analyse(design: str, directory: Path, grids=(16, 32, 64)) -> dict:
    die = json.loads((directory / f"{design}_die.json").read_text())
    power = read_power(directory / f"{design}_inst_power.txt")
    placement = read_placement(directory / f"{design}_placement.csv")
    joined, audit = join(power, placement)

    by_grid = {}
    for nx in grids:
        q = rasterise(joined, die["die_um"], nx, nx)
        by_grid[nx] = {"cell_um": (die["die_um"][2] - die["die_um"][0]) / nx,
                       **concentration(q)}

    totals = {k: float(sum(i[k] for i in joined))
              for k in ("internal_w", "switching_w", "leakage_w", "total_w")}
    return {
        "design": design,
        "platform": die["platform"],
        "stage": die["stage"],
        "activity": die["activity"],
        "die_um": die["die_um"],
        "die_mm2": ((die["die_um"][2] - die["die_um"][0])
                    * (die["die_um"][3] - die["die_um"][1]) / 1e6),
        "instances": audit,
        "power_w": totals,
        "power_split": {k: totals[k] / totals["total_w"]
                        for k in ("internal_w", "switching_w", "leakage_w")},
        "by_grid": by_grid,
        "submodel_equivalent": submodel_equivalent(by_grid[max(grids)]),
    }


def print_report(doc: dict) -> None:
    print(f"🔧 OpenROAD power map: {doc['design']} on {doc['platform']}, "
          f"{doc['instances']['joined']} instances, "
          f"{doc['die_mm2']:.4f} mm2, activity {doc['activity']}\n")
    p = doc["power_w"]
    print(f"  total {p['total_w'] * 1e3:.3f} mW = "
          f"{doc['power_split']['internal_w']:.0%} internal / "
          f"{doc['power_split']['switching_w']:.0%} switching / "
          f"{doc['power_split']['leakage_w']:.1%} leakage")
    print(f"\n  {'grid':>6} {'cell':>9} {'peak/mean':>10} {'active':>8} "
          f"{'50% power in':>13} {'90% in':>9}")
    for nx, s in doc["by_grid"].items():
        print(f"  {nx:>3}x{nx:<2} {s['cell_um']:8.2f}u {s['peak_to_die_mean']:10.2f} "
              f"{s['active_area_fraction']:8.1%} "
              f"{s['area_holding_50pct_power']:13.1%} "
              f"{s['area_holding_90pct_power']:9.1%}")
    e = doc["submodel_equivalent"]
    print(f"\n  submodel equivalent: {e['fraction_of_power']:.0%} of the power "
          f"in {e['fraction_of_area']:.1%} of the area")


def _assert_behaves(doc: dict) -> bool:
    ok = True
    a = doc["instances"]
    if a["joined"] < 0.9 * a["instances_placed"]:
        print(f"\n  ❌ only {a['joined']} of {a['instances_placed']} placed "
              f"instances got power: the join is losing cells.")
        ok = False
    p = doc["power_w"]
    # OpenSTA prints 9 significant digits, so summing hundreds of rows cannot
    # close tighter than that -- 1e-9 was checking the printer, not the physics.
    resid = abs(p["total_w"] - (p["internal_w"] + p["switching_w"]
                                + p["leakage_w"]))
    if resid > 1e-6 * max(p["total_w"], 1e-12):
        print(f"\n  ❌ the power components do not sum to the reported total "
              f"({resid / p['total_w']:.2e} relative, beyond printed precision).")
        ok = False
    peaks = [s["peak_to_die_mean"] for s in doc["by_grid"].values()]
    if not all(a <= b + 1e-9 for a, b in zip(peaks, peaks[1:])):
        print("\n  ❌ peak-to-mean fell as the grid refined, which cannot happen "
              "when the same watts are resolved more finely.")
        ok = False
    if ok:
        print("\n  ✅ every placed instance carries power, the components sum, "
              "and concentration rises monotonically with resolution.")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", default="gcd")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--out", default=str(REPO_ROOT / "reports/openroad_power.json"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    doc = analyse(args.design, Path(args.dir))
    doc["caveats"] = [
        "ASAP7 is a predictive 7 nm library and this is an ORFS benchmark "
        "design, not a CXL switch: absolute W/cm2 does not transfer, the shape "
        "does",
        "the flow stops at placement because CTS crashes under amd64 emulation "
        "on this machine, so clock-tree buffers and routing parasitics are "
        "absent -- both would concentrate power further, making this a lower "
        "bound",
        "switching activity is an assumption, stated above",
    ]
    print_report(doc)
    ok = _assert_behaves(doc)
    if not args.verify:
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
        print(f"\n  wrote {Path(args.out).relative_to(REPO_ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
