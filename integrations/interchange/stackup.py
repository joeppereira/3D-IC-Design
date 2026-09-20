"""Canonical stackup JSON (spec 2.8) -- consumed by Celsius, Sigrity/EDB,
HyperLynx, Calibre 3DSTACK and 3DIC Compiler.

Units are declared explicitly and validated: a silent um/mm error is the most
expensive bug class in this integration.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN, SEV_INFO
from ..canonical import DesignRecord

SCHEMA_VERSION = "1.0"
REQUIRED_UNITS = {"length": "um", "temperature": "C", "power": "W",
                  "conductivity": "W/mK", "flow": "LPM"}


def to_dict(design: DesignRecord, prov: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": prov,
        "design": design.project,
        "units": dict(REQUIRED_UNITS),
        "dies": [
            {"name": d.name, "kind": d.kind,
             "size_um": [d.width_um, d.height_um],
             "thickness_um": d.thickness_um,
             "k_w_mk": d.k_w_mk, "power_w": d.power_w, "bspdn": d.bspdn}
            for d in design.dies
        ],
        "interfaces": [
            {"between": list(i.between), "type": i.kind, "pitch_um": i.pitch_um,
             "diameter_um": i.diameter_um, "aspect_ratio": i.aspect_ratio,
             "liner": i.liner}
            for i in design.interfaces
        ],
        "tim": {"thickness_um": design.tim_thickness_um, "k_w_mk": design.tim_k_w_mk},
        "boundary": {"case_temp_c": design.case_temp_c,
                     "liquid_flow_lpm": design.liquid_flow_lpm},
        "interposer": {"material": design.interposer_material,
                       "topology": design.topology},
        "electrical": {"vdd_v": design.vdd_v, "vddq_v": design.vddq_v,
                       "ripple_target_mv": design.ripple_target_mv,
                       "didt_a_per_ns": design.didt_a_per_ns},
    }


def write(design: DesignRecord, path: Path, prov: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(design, prov), indent=2) + "\n")
    return path


def read(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def validate(doc: dict) -> list[Finding]:
    out: list[Finding] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        out.append(Finding(SEV_WARN, "schema", f"version {doc.get('schema_version')} != {SCHEMA_VERSION}"))
    units = doc.get("units", {})
    for k, v in REQUIRED_UNITS.items():
        if units.get(k) != v:
            out.append(Finding(SEV_ERROR, "units", f"units.{k} must be declared as '{v}'"))
    if not doc.get("dies"):
        out.append(Finding(SEV_ERROR, "dies", "stackup declares no dies"))
    for d in doc.get("dies", []):
        # A die thinner than 5um or thicker than 1mm means a unit slip.
        if not 5.0 <= d.get("thickness_um", 0) <= 1000.0:
            out.append(Finding(SEV_ERROR, "unit_sanity",
                               f"die {d['name']} thickness {d.get('thickness_um')}um is "
                               "outside 5..1000um -- probable mm/um confusion"))
        if not 1000.0 <= d.get("size_um", [0])[0] <= 100000.0:
            out.append(Finding(SEV_ERROR, "unit_sanity",
                               f"die {d['name']} width {d.get('size_um')}um outside 1..100mm"))
    for i in doc.get("interfaces", []):
        if i.get("type") == "hybrid_bond" and i.get("pitch_um", 99) > 20.0:
            out.append(Finding(SEV_WARN, "hybrid_bond",
                               f"bond pitch {i['pitch_um']}um is coarse for hybrid bonding"))
        if i.get("type") == "tsv" and i.get("aspect_ratio") and i["aspect_ratio"] > 20:
            out.append(Finding(SEV_WARN, "tsv", f"aspect ratio {i['aspect_ratio']}:1 exceeds 20:1"))
    total = sum(d.get("power_w", 0) for d in doc.get("dies", []))
    out.append(Finding(SEV_INFO, "power", f"stack dissipates {total:.1f} W"))
    return out
