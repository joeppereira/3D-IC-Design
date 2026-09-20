"""LEF writer + reader (spec 2.1).

The repo already ships pdk/generic_3nm.lef and pdk/macros.lef.  What is missing
is an abstract for every cell the placement actually instantiates, plus the TSV
and hybrid-bond pad cells -- without those the 3D interface is invisible to
every downstream tool.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN, provenance_header
from ..canonical import DesignRecord

DB_MICRONS = 1000
SITE = "unithd"

# Pin sets per macro class, matching the nets built in canonical.build_nets.
PIN_SETS = {
    "SERDES_224G_PHY": [("TXP", "OUTPUT"), ("TXN", "OUTPUT"), ("RXP", "INPUT"),
                        ("RXN", "INPUT"), ("VDDQ_SERDES", "INOUT"), ("VSS", "INOUT")],
    "UCIE2_PHY": [("TX[0]", "OUTPUT"), ("RX[0]", "INPUT"), ("CLK", "INPUT"),
                  ("VDD_CORE", "INOUT"), ("VSS", "INOUT")],
    "TSV_CU_2UM": [("TOP", "INOUT"), ("BOT", "INOUT")],
    "HYBRID_BOND_PAD": [("TOP", "INOUT"), ("BOT", "INOUT")],
}


def _cells(design: DesignRecord) -> dict[str, tuple[float, float]]:
    cells: dict[str, tuple[float, float]] = {}
    for m in design.macros:
        cells[m.cell] = m.size_um
    for i in design.interfaces:
        if i.kind == "tsv" and i.diameter_um:
            cells["TSV_CU_2UM"] = (i.diameter_um, i.diameter_um)
        if i.kind == "hybrid_bond":
            cells["HYBRID_BOND_PAD"] = (i.pitch_um / 2.0, i.pitch_um / 2.0)
    return cells


def write(design: DesignRecord, path: Path, prov: dict) -> Path:
    L = [provenance_header(prov, "#").rstrip("\n"),
         "VERSION 5.8 ;", 'BUSBITCHARS "[]" ;', 'DIVIDERCHAR "/" ;',
         "UNITS", f"  DATABASE MICRONS {DB_MICRONS} ;", "END UNITS",
         "MANUFACTURINGGRID 0.005 ;", "",
         f"SITE {SITE}", "  CLASS CORE ;", "  SYMMETRY Y ;",
         "  SIZE 0.048 BY 0.360 ;", f"END {SITE}", ""]
    for cell, (w, h) in sorted(_cells(design).items()):
        pins = PIN_SETS.get(cell, [("VDD", "INOUT"), ("VSS", "INOUT")])
        L += [f"MACRO {cell}", "  CLASS BLOCK ;", "  ORIGIN 0 0 ;",
              f"  SIZE {w:.3f} BY {h:.3f} ;", "  SYMMETRY X Y ;"]
        for idx, (pin, direction) in enumerate(pins):
            use = "POWER" if direction == "INOUT" and ("VDD" in pin or "VSS" in pin) else "SIGNAL"
            px = min(1.0 + idx * 2.0, max(w - 1.0, 0.5))
            L += [f"  PIN {pin}", f"    DIRECTION {direction} ;", f"    USE {use} ;",
                  "    PORT", "      LAYER Metal7 ;",
                  f"        RECT {px:.3f} 0.000 {px + 0.5:.3f} 0.500 ;",
                  "    END", f"  END {pin}"]
        L += ["  OBS", "    LAYER Metal1 ;",
              f"      RECT 0.000 0.000 {w:.3f} {h:.3f} ;", "  END",
              f"END {cell}", ""]
    L.append("END LIBRARY")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def read(path: Path) -> dict:
    text = Path(path).read_text()
    macros: dict[str, dict] = {}
    for block in re.finditer(r"^MACRO\s+(\S+)(.*?)^END\s+\1\s*$", text,
                             re.S | re.M):
        name, body = block.group(1), block.group(2)
        size = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", body)
        macros[name] = {
            "size_um": (float(size.group(1)), float(size.group(2))) if size else None,
            "pins": re.findall(r"^\s*PIN\s+(\S+)", body, re.M),
            "class": (re.search(r"CLASS\s+(\w+)\s*;", body) or [None, None])[1],
        }
    units = re.search(r"DATABASE\s+MICRONS\s+(\d+)\s*;", text)
    return {"macros": macros,
            "sites": re.findall(r"^SITE\s+(\S+)", text, re.M),
            "db_microns": int(units.group(1)) if units else None}


def validate(doc: dict, design: DesignRecord) -> list[Finding]:
    out: list[Finding] = []
    if doc["db_microns"] != DB_MICRONS:
        out.append(Finding(SEV_ERROR, "lef_units", "DATABASE MICRONS mismatch"))
    if SITE not in doc["sites"]:
        out.append(Finding(SEV_ERROR, "lef_site",
                           f"SITE {SITE} missing; gen_def.py initialises the "
                           f"floorplan with -site {SITE}"))
    want = _cells(design)
    for cell, size in want.items():
        got = doc["macros"].get(cell)
        if got is None:
            out.append(Finding(SEV_ERROR, "lef_macro", f"{cell} has no LEF abstract"))
        elif got["size_um"] != size:
            out.append(Finding(SEV_ERROR, "lef_size",
                               f"{cell} SIZE {got['size_um']} != {size}"))
        elif not got["pins"]:
            out.append(Finding(SEV_WARN, "lef_pins", f"{cell} declares no pins"))
    for placed in {m.cell for m in design.macros}:
        if placed not in doc["macros"]:
            out.append(Finding(SEV_ERROR, "lef_coverage",
                               f"placed cell {placed} is not in the LEF"))
    return out
