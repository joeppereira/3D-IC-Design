"""DEF writer + independent reader (spec 2.2).

One DEF per die: a 3D stack is N DEFs plus a stack description, never a
flattened single view.  Geometry comes from canonical.derive_macros so DEF and
the OpenROAD Tcl in gen_def.py cannot diverge.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN
from ..canonical import Die, DesignRecord, Macro

DBU_PER_UM = 1000
ROT_KEEPOUT_UM = 250.0   # Caliptra RoT EM guard-band from gen_def.py


def _dbu(um: float) -> int:
    return int(round(um * DBU_PER_UM))


def write(design: DesignRecord, die: Die, path: Path, prov: dict) -> Path:
    from ..base import provenance_header
    macros = design.macros_on(die.name)
    L = [provenance_header(prov, "#").rstrip("\n"),
         "VERSION 5.8 ;",
         'DIVIDERCHAR "/" ;',
         'BUSBITCHARS "[]" ;',
         f"DESIGN {_ident(die.name)} ;",
         f"UNITS DISTANCE MICRONS {DBU_PER_UM} ;",
         f"DIEAREA ( 0 0 ) ( {_dbu(die.width_um)} {_dbu(die.height_um)} ) ;",
         ""]

    L.append(f"COMPONENTS {len(macros)} ;")
    for m in macros:
        status = "FIXED" if m.fixed else "PLACED"
        L.append(f"    - {m.name} {m.cell} + {status} "
                 f"( {_dbu(m.origin_um[0])} {_dbu(m.origin_um[1])} ) {m.orient} ;")
    L.append("END COMPONENTS")
    L.append("")

    # Security keep-out: gen_def.py declares a 250um EM shield around the RoT.
    cx, cy = die.width_um / 2.0, die.height_um / 2.0
    L.append("BLOCKAGES 1 ;")
    L.append(f"    - PLACEMENT RECT ( {_dbu(cx - ROT_KEEPOUT_UM)} {_dbu(cy - ROT_KEEPOUT_UM)} ) "
             f"( {_dbu(cx + ROT_KEEPOUT_UM)} {_dbu(cy + ROT_KEEPOUT_UM)} ) ;")
    L.append("END BLOCKAGES")
    L.append("")

    L.append(f"SPECIALNETS {len(design.stripes)} ;")
    for s in design.stripes:
        L.append(f"    - {s.net}_{s.layer}")
        L.append(f"      + ROUTED {s.layer} {_dbu(s.width_um)} + SHAPE STRIPE "
                 f"( 0 {_dbu(s.offset_um)} ) ( {_dbu(die.width_um)} {_dbu(s.offset_um)} )")
        L.append(f"      + PROPERTY PITCH {s.pitch_um} ;")
    L.append("END SPECIALNETS")
    L.append("")
    L.append("END DESIGN")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def _ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


_COMP = re.compile(
    r"-\s+(\S+)\s+(\S+)\s+\+\s+(FIXED|PLACED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)\s*;")
_DIE = re.compile(r"DIEAREA\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;")
_UNITS = re.compile(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
_DESIGN = re.compile(r"DESIGN\s+(\S+)\s*;")


def read(path: Path) -> dict:
    """Independent parser -- deliberately not sharing code with write()."""
    text = Path(path).read_text()
    units = int(m.group(1)) if (m := _UNITS.search(text)) else DBU_PER_UM
    scale = float(units)
    die = _DIE.search(text)
    comps = []
    body = text.split("COMPONENTS", 1)[-1].split("END COMPONENTS", 1)[0]
    for m in _COMP.finditer(body):
        comps.append({"name": m.group(1), "cell": m.group(2),
                      "fixed": m.group(3) == "FIXED",
                      "origin_um": (int(m.group(4)) / scale, int(m.group(5)) / scale),
                      "orient": m.group(6)})
    stripes = []
    if "SPECIALNETS" in text:
        sn = text.split("SPECIALNETS", 1)[-1].split("END SPECIALNETS", 1)[0]
        for m in re.finditer(r"\+\s+ROUTED\s+(\S+)\s+(\d+)", sn):
            stripes.append({"layer": m.group(1), "width_um": int(m.group(2)) / scale})
    return {
        "design": _DESIGN.search(text).group(1) if _DESIGN.search(text) else None,
        "units_per_um": units,
        "diearea_um": (int(die.group(3)) / scale, int(die.group(4)) / scale) if die else None,
        "components": comps,
        "stripes": stripes,
        "blockages": len(re.findall(r"-\s+PLACEMENT\s+RECT", text)),
    }


def validate(doc: dict, die: Die, macros: list[Macro]) -> list[Finding]:
    out: list[Finding] = []
    if doc["units_per_um"] != DBU_PER_UM:
        out.append(Finding(SEV_ERROR, "def_units", f"expected {DBU_PER_UM} DBU/um"))
    if doc["diearea_um"] != (die.width_um, die.height_um):
        out.append(Finding(SEV_ERROR, "def_diearea",
                           f"round-trip DIEAREA {doc['diearea_um']} != "
                           f"{(die.width_um, die.height_um)}"))
    if len(doc["components"]) != len(macros):
        out.append(Finding(SEV_ERROR, "def_components",
                           f"round-trip {len(doc['components'])} components != {len(macros)}"))
    by_name = {c["name"]: c for c in doc["components"]}
    for m in macros:
        c = by_name.get(m.name)
        if c is None:
            out.append(Finding(SEV_ERROR, "def_component", f"{m.name} lost in round-trip"))
        elif c["origin_um"] != tuple(m.origin_um) or c["orient"] != m.orient:
            out.append(Finding(SEV_ERROR, "def_placement",
                               f"{m.name} {c['origin_um']}/{c['orient']} != "
                               f"{tuple(m.origin_um)}/{m.orient}"))
    if doc["blockages"] < 1:
        out.append(Finding(SEV_WARN, "def_blockage", "RoT EM keep-out missing"))
    return out
