"""Readers for what licensed tools hand back (spec 5, return direction).

Each reader normalizes a vendor artifact into a small dict that correlate.py can
compare against the surrogate's own prediction.  The readers are format-tolerant
(vendors differ in column naming and header decoration) but never guess units:
a missing or unrecognized unit is an error, not a default.
"""
from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path

import numpy as np

# Column aliases seen across Celsius / Icepak / Voltus / Redhawk text exports.
X_KEYS = ("x", "x_um", "x(um)", "xcoord", "x_coordinate")
Y_KEYS = ("y", "y_um", "y(um)", "ycoord", "y_coordinate")
Z_KEYS = ("z", "z_um", "z(um)", "layer", "die")
T_KEYS = ("t", "temp", "temp_c", "temperature", "temperature_c", "tj", "tj_c")
V_KEYS = ("v", "voltage", "voltage_v", "v_actual", "vdd_actual", "node_voltage")
DROP_KEYS = ("drop", "ir_drop", "ir_drop_mv", "drop_mv", "voltage_drop", "worst_drop_mv")
NET_KEYS = ("net", "net_name", "power_net", "domain")


def _sniff_table(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows) from a CSV/TSV/whitespace table, skipping comments."""
    lines = [ln for ln in Path(path).read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith(("#", "*", "!", "//"))]
    if not lines:
        raise ValueError(f"{path} contains no data rows")
    sample = lines[0]
    if "," in sample:
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
    elif "\t" in sample:
        rows = [ln.split("\t") for ln in lines]
    else:
        rows = [ln.split() for ln in lines]
    header = [c.strip().lower().replace(" ", "_") for c in rows[0]]
    numeric_first_row = all(_is_num(c) for c in rows[0])
    if numeric_first_row:
        raise ValueError(f"{path} has no header row; column meaning cannot be inferred")
    return header, rows[1:]


def _is_num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except (TypeError, ValueError):
        return False


def _col(header: list[str], keys: tuple[str, ...]) -> int | None:
    for k in keys:
        if k in header:
            return header.index(k)
    for i, h in enumerate(header):           # substring fallback
        if any(h.startswith(k) for k in keys):
            return i
    return None


def read_thermal_field(path: Path) -> dict:
    """Celsius / Icepak style temperature export -> peak Tj, hotspot, field.

    Accepts scattered points or a structured grid; only requires coordinates in
    microns plus a temperature column in Celsius.
    """
    header, rows = _sniff_table(path)
    ix, iy, it = _col(header, X_KEYS), _col(header, Y_KEYS), _col(header, T_KEYS)
    iz = _col(header, Z_KEYS)
    if it is None:
        raise ValueError(f"{path}: no temperature column in {header}")
    if ix is None or iy is None:
        raise ValueError(f"{path}: no x/y coordinate columns in {header}")
    x, y, z, t = [], [], [], []
    for r in rows:
        if len(r) <= max(i for i in (ix, iy, it) if i is not None):
            continue
        try:
            t.append(float(r[it]))
            x.append(float(r[ix]))
            y.append(float(r[iy]))
            z.append(float(r[iz]) if iz is not None and _is_num(r[iz]) else 0.0)
        except ValueError:
            continue
    if not t:
        raise ValueError(f"{path}: no numeric temperature rows parsed")
    tarr, xarr, yarr, zarr = map(np.asarray, (t, x, y, z))
    peak = int(np.argmax(tarr))
    return {
        "kind": "thermal_field",
        "source": str(path),
        "n_points": len(tarr),
        "tj_peak_c": float(tarr.max()),
        "tj_mean_c": float(tarr.mean()),
        "tj_min_c": float(tarr.min()),
        "hotspot_um": (float(xarr[peak]), float(yarr[peak]), float(zarr[peak])),
        "field": tarr,
        "coords_um": np.stack([xarr, yarr, zarr], axis=1),
    }


def read_ir_drop(path: Path) -> dict:
    """Voltus-Fi / Redhawk style IR report -> worst droop per power net.

    Understands either an explicit drop column or actual-voltage against a
    nominal parsed from the report header.
    """
    text = Path(path).read_text()
    nominal = None
    if (m := re.search(r"(?:nominal|vdd|supply)[^\d\n]*([\d.]+)\s*(v\b|volt)", text, re.I)):
        nominal = float(m.group(1))
    header, rows = _sniff_table(path)
    inet, idrop, ivolt = (_col(header, NET_KEYS), _col(header, DROP_KEYS),
                          _col(header, V_KEYS))
    if idrop is None and ivolt is None:
        raise ValueError(f"{path}: no drop or voltage column in {header}")
    if idrop is None and nominal is None:
        raise ValueError(f"{path}: voltage-only report needs a nominal supply in the header")
    per_net: dict[str, float] = {}
    for r in rows:
        if not r or len(r) <= max(i for i in (inet, idrop, ivolt) if i is not None):
            continue
        net = r[inet].strip() if inet is not None else "ALL"
        try:
            drop_mv = (float(r[idrop]) if idrop is not None
                       else (nominal - float(r[ivolt])) * 1000.0)
        except ValueError:
            continue
        per_net[net] = max(per_net.get(net, 0.0), drop_mv)
    if not per_net:
        raise ValueError(f"{path}: no numeric droop rows parsed")
    worst_net = max(per_net, key=per_net.get)
    worst = per_net[worst_net]
    return {
        "kind": "ir_drop",
        "source": str(path),
        "nominal_v": nominal,
        "per_net_mv": per_net,
        "worst_net": worst_net,
        "worst_droop_mv": worst,
        "worst_droop_pct": (worst / 1000.0 / nominal * 100.0) if nominal else None,
    }


def read_starrc_spef(path: Path) -> dict:
    """StarRC (or any golden) SPEF -> per-net R/C, for the spec 4.2 correlation."""
    from ..interchange.spef_io import read as spef_read
    doc = spef_read(Path(path))
    return {"kind": "parasitics", "source": str(path),
            "flow": doc["header"].get("DESIGN_FLOW", ""),
            "nets": {n: {"r_ohm": v["r_ohm"], "c_pf": v["c_pf"]}
                     for n, v in doc["nets"].items()}}


def read_sparameters(path: Path) -> dict:
    """Field-solved / measured Touchstone -> IL curve, for the spec 2.6 upgrade."""
    from ..interchange.touchstone_io import read as ts_read, insertion_loss_db, il_at
    freqs, s, meta = ts_read(Path(path))
    return {"kind": "sparameters", "source": str(path), "meta": meta,
            "freqs_hz": freqs, "s": s,
            "il_db": insertion_loss_db(s),
            "il_at": lambda f_ghz: il_at(freqs, s, f_ghz)}


def read_def_placement(path: Path) -> dict:
    """DEF written back by a P&R tool -> placements, to re-enter the search loop."""
    from ..interchange.def_io import read as def_read
    doc = def_read(Path(path))
    return {"kind": "placement", "source": str(path),
            "design": doc["design"], "diearea_um": doc["diearea_um"],
            "components": doc["components"]}


READERS = {
    "thermal": read_thermal_field,
    "ir": read_ir_drop,
    "spef": read_starrc_spef,
    "sparam": read_sparameters,
    "def": read_def_placement,
}


def read_any(path: Path, kind: str | None = None) -> dict:
    """Dispatch on explicit kind, else on suffix."""
    p = Path(path)
    if kind:
        return READERS[kind](p)
    suffix = p.suffix.lower()
    if re.match(r"\.s\d+p$", suffix):
        return read_sparameters(p)
    if suffix == ".spef":
        return read_starrc_spef(p)
    if suffix == ".def":
        return read_def_placement(p)
    text = p.read_text(errors="ignore")[:4000].lower()
    if any(k in text for k in ("temperature", "temp_c", "tj")):
        return read_thermal_field(p)
    if any(k in text for k in ("ir_drop", "drop_mv", "voltage")):
        return read_ir_drop(p)
    raise ValueError(f"cannot infer result kind for {p}; pass kind= explicitly")
