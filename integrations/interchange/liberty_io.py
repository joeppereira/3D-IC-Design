"""Liberty writer + reader (spec 2.5).

Pins, capacitance and power-domain intent only.  Timing arcs are NOT emitted:
declaring uncharacterized cell_rise tables would be fabricating characterization
data.  The reader enforces that rule so a future change cannot quietly break it.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..base import Finding, SEV_ERROR, provenance_header
from ..canonical import DesignRecord
from .lef_io import PIN_SETS, _cells

PIN_CAP_PF = {"OUTPUT": 0.050, "INPUT": 0.012, "INOUT": 0.030}
MAX_TRANSITION_NS = 0.020


def write(design: DesignRecord, path: Path, prov: dict) -> Path:
    cells = _cells(design)
    L = [provenance_header(prov, "//").rstrip("\n"),
         "library (3dic_x_macros) {",
         "  technology (cmos);",
         "  delay_model : table_lookup;",
         '  time_unit : "1ns";',
         '  voltage_unit : "1V";',
         '  current_unit : "1mA";',
         "  capacitive_load_unit (1, pf);",
         '  pulling_resistance_unit : "1kohm";',
         "  nom_process : 1.0;",
         f"  nom_temperature : {design.op_temp_c};",
         f"  nom_voltage : {design.vdd_v};",
         "  /* No timing arcs: these macros are not characterized. Emitting",
         "     cell_rise/cell_fall tables here would fabricate characterization",
         "     data (see reports/eda_vendor_integration_spec.md section 2.5). */"]
    for cell, (w, h) in sorted(cells.items()):
        L += [f"  cell ({cell}) {{",
              f"    area : {w * h:.3f};",
              "    is_macro_cell : true;",
              "    dont_touch : true;",
              "    dont_use : true;"]
        for pin, direction in PIN_SETS.get(cell, [("VDD", "INOUT"), ("VSS", "INOUT")]):
            if direction == "INOUT" and ("VDD" in pin or "VSS" in pin):
                pg = "primary_power" if "VDD" in pin else "primary_ground"
                L += [f"    pg_pin ({pin}) {{",
                      f"      pg_type : {pg};",
                      f'      voltage_name : "{pin}";',
                      "    }"]
            else:
                L += [f"    pin ({pin}) {{",
                      f"      direction : {direction.lower()};",
                      f"      capacitance : {PIN_CAP_PF[direction]:.3f};",
                      f"      max_transition : {MAX_TRANSITION_NS:.3f};",
                      '      /* provenance: SURROGATE, uncharacterized */',
                      "    }"]
        L.append("  }")
    L.append("}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def read(path: Path) -> dict:
    text = Path(path).read_text()
    cells: dict[str, dict] = {}
    for m in re.finditer(r"^\s*cell\s*\((\S+?)\)\s*\{", text, re.M):
        name = m.group(1)
        body = _block(text, m.end() - 1)
        cells[name] = {
            "area": float(a.group(1)) if (a := re.search(r"area\s*:\s*([\d.]+)", body)) else None,
            "pins": {p.group(1): _pin(body, p.end() - 1)
                     for p in re.finditer(r"pin\s*\((\S+?)\)\s*\{", body)
                     if not body[:p.start()].rstrip().endswith("pg_")},
            "pg_pins": re.findall(r"pg_pin\s*\((\S+?)\)", body),
            "timing_groups": len(re.findall(r"\btiming\s*\(", body)),
        }
    return {
        "library": (re.search(r"library\s*\((\S+?)\)", text) or [None, None])[1],
        "nom_temperature": float(t.group(1)) if (t := re.search(r"nom_temperature\s*:\s*([\d.]+)", text)) else None,
        "nom_voltage": float(v.group(1)) if (v := re.search(r"nom_voltage\s*:\s*([\d.]+)", text)) else None,
        "cells": cells,
        "total_timing_groups": len(re.findall(r"\btiming\s*\(", text)),
    }


def _block(text: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i]
    return text[open_idx:]


def _pin(body: str, open_idx: int) -> dict:
    blk = _block(body, open_idx)
    return {
        "direction": (re.search(r"direction\s*:\s*(\w+)", blk) or [None, None])[1],
        "capacitance": float(c.group(1)) if (c := re.search(r"capacitance\s*:\s*([\d.]+)", blk)) else None,
    }


def validate(doc: dict, design: DesignRecord) -> list[Finding]:
    out: list[Finding] = []
    if doc["total_timing_groups"]:
        out.append(Finding(SEV_ERROR, "lib_no_fabricated_timing",
                           f"{doc['total_timing_groups']} timing group(s) present; timing arcs "
                           "must not be emitted without a characterized source"))
    if doc["nom_temperature"] != design.op_temp_c:
        out.append(Finding(SEV_ERROR, "lib_temp",
                           f"nom_temperature {doc['nom_temperature']} != surrogate operating "
                           f"point {design.op_temp_c}C"))
    for cell in _cells(design):
        got = doc["cells"].get(cell)
        if got is None:
            out.append(Finding(SEV_ERROR, "lib_cell", f"{cell} missing from .lib"))
        elif not got["pins"] and not got["pg_pins"]:
            out.append(Finding(SEV_ERROR, "lib_pins", f"{cell} declares no pins"))
    return out
