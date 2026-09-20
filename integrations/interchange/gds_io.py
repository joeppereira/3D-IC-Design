"""Minimal GDSII stream writer + reader (spec 2.3, prerequisite P0-E).

Replaces serdes_architect/scripts/gds_export.tcl, in which every functional
command is commented out.  Pure stdlib: the repo has neither gdstk nor KLayout
installed, and a real binary writer is what makes the artifact checkable.
"""
from __future__ import annotations

import struct
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN
from ..canonical import Die, DesignRecord

# Record types
HEADER, BGNLIB, LIBNAME, UNITS = 0x0002, 0x0102, 0x0206, 0x0305
ENDLIB, BGNSTR, STRNAME, ENDSTR = 0x0400, 0x0502, 0x0606, 0x0700
BOUNDARY, SREF, ENDEL = 0x0800, 0x0A00, 0x1100
LAYER, DATATYPE, XY, SNAME = 0x0D02, 0x0E02, 0x1003, 0x1206
STRANS, ANGLE = 0x1A01, 0x1C05

DBU_M = 1e-9          # 1 nm database unit
USER_UNIT = 1e-3      # user unit = 1 um expressed in db units
LAYER_DIE, LAYER_MACRO, LAYER_PDN, LAYER_TSV, LAYER_BOND, LAYER_KEEPOUT = 1, 10, 20, 30, 31, 90
ORIENT_ANGLE = {"N": 0.0, "W": 90.0, "S": 180.0, "E": 270.0}


def _real8(value: float) -> bytes:
    """GDSII 8-byte excess-64 base-16 float."""
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0x00
    value = abs(value)
    exponent = 64
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    mantissa = int(round(value * (1 << 56)))
    if mantissa >= (1 << 56):          # rounding pushed it to the next exponent
        mantissa >>= 4
        exponent += 1
    return bytes([sign | exponent]) + mantissa.to_bytes(7, "big")


def _parse_real8(raw: bytes) -> float:
    sign = -1.0 if raw[0] & 0x80 else 1.0
    exponent = (raw[0] & 0x7F) - 64
    mantissa = int.from_bytes(raw[1:8], "big") / float(1 << 56)
    return sign * mantissa * (16.0 ** exponent)


def _rec(rtype: int, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HH", len(payload) + 4, rtype) + payload


def _ascii(rtype: int, text: str) -> bytes:
    return _rec(rtype, text.encode("ascii"))


def _i2(rtype: int, *vals: int) -> bytes:
    return _rec(rtype, b"".join(struct.pack(">h", v) for v in vals))


def _xy(points: list[tuple[float, float]]) -> bytes:
    nm = [(int(round(x * 1000)), int(round(y * 1000))) for x, y in points]  # um -> nm
    return _rec(XY, b"".join(struct.pack(">ii", x, y) for x, y in nm))


def _stamp() -> bytes:
    return _rec(BGNLIB, struct.pack(">12h", 2026, 9, 19, 0, 0, 0, 2026, 9, 19, 0, 0, 0))


def _rect(layer: int, x0: float, y0: float, x1: float, y1: float) -> bytes:
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return (_rec(BOUNDARY) + _i2(LAYER, layer) + _i2(DATATYPE, 0) + _xy(pts) + _rec(ENDEL))


def write(design: DesignRecord, die: Die, path: Path, prov: dict) -> Path:
    """Stream out one die: die outline, macro cells as SREFs, PDN, 3D interfaces."""
    from ..base import write_sidecar
    top = die.name.upper()[:31]
    cells: dict[str, bytes] = {}

    # Leaf cells, one per distinct macro footprint.
    for cell, size in sorted({m.cell: m.size_um for m in design.macros_on(die.name)}.items()):
        cells[cell[:31]] = _rect(LAYER_MACRO, 0, 0, size[0], size[1])
    # 3D interface cells.
    for i in design.interfaces:
        if i.kind == "tsv" and i.diameter_um:
            cells["TSV_CU_2UM"] = _rect(LAYER_TSV, 0, 0, i.diameter_um, i.diameter_um)
        if i.kind == "hybrid_bond":
            s = i.pitch_um / 2.0
            cells["HYBRID_BOND_PAD"] = _rect(LAYER_BOND, 0, 0, s, s)

    body = b"".join([_rec(HEADER, struct.pack(">h", 600)), _stamp(),
                     _ascii(LIBNAME, f"{top}.DB"),
                     _rec(UNITS, _real8(USER_UNIT) + _real8(DBU_M))])

    for name, geom in cells.items():
        body += _rec(BGNSTR, struct.pack(">12h", 2026, 9, 19, 0, 0, 0, 2026, 9, 19, 0, 0, 0))
        body += _ascii(STRNAME, name) + geom + _rec(ENDSTR)

    # Top cell.
    body += _rec(BGNSTR, struct.pack(">12h", 2026, 9, 19, 0, 0, 0, 2026, 9, 19, 0, 0, 0))
    body += _ascii(STRNAME, top)
    body += _rect(LAYER_DIE, 0, 0, die.width_um, die.height_um)
    for m in design.macros_on(die.name):
        body += (_rec(SREF) + _ascii(SNAME, m.cell[:31])
                 + _rec(STRANS, struct.pack(">H", 0))
                 + _rec(ANGLE, _real8(ORIENT_ANGLE.get(m.orient, 0.0)))
                 + _xy([tuple(m.origin_um)]) + _rec(ENDEL))
    for s in design.stripes:
        y = s.offset_um
        while y < die.height_um:
            body += _rect(LAYER_PDN, 0, y, die.width_um, y + s.width_um)
            y += s.pitch_um * 20     # decimated for stream size; pitch kept in DEF
    cx, cy = die.width_um / 2, die.height_um / 2
    body += _rect(LAYER_KEEPOUT, cx - 250, cy - 250, cx + 250, cy + 250)
    body += _rec(ENDSTR) + _rec(ENDLIB)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    write_sidecar(path, prov)      # binary format cannot carry a comment header
    return path


def read(path: Path) -> dict:
    """Independent stream parser: structures, layers, SREF references."""
    raw = Path(path).read_bytes()
    pos, structs, cur = 0, {}, None
    units = None
    while pos < len(raw):
        (length, rtype) = struct.unpack(">HH", raw[pos:pos + 4])
        payload = raw[pos + 4: pos + length]
        pos += length
        if rtype == UNITS:
            units = (_parse_real8(payload[0:8]), _parse_real8(payload[8:16]))
        elif rtype == STRNAME:
            cur = payload.rstrip(b"\x00").decode("ascii")
            structs[cur] = {"layers": set(), "srefs": [], "boundaries": 0, "bbox": None}
        elif rtype == LAYER and cur:
            structs[cur]["layers"].add(struct.unpack(">h", payload[:2])[0])
        elif rtype == BOUNDARY and cur:
            structs[cur]["boundaries"] += 1
        elif rtype == SNAME and cur:
            structs[cur]["srefs"].append(payload.rstrip(b"\x00").decode("ascii"))
        elif rtype == XY and cur:
            pts = [struct.unpack(">ii", payload[i:i + 8]) for i in range(0, len(payload), 8)]
            pts_um = [(x / 1000.0, y / 1000.0) for x, y in pts]
            bb = structs[cur]["bbox"]
            xs = [p[0] for p in pts_um] + ([bb[0], bb[2]] if bb else [])
            ys = [p[1] for p in pts_um] + ([bb[1], bb[3]] if bb else [])
            structs[cur]["bbox"] = (min(xs), min(ys), max(xs), max(ys))
        elif rtype == ENDLIB:
            break
    return {"units": units, "structures": structs,
            "top": max(structs, key=lambda k: structs[k]["boundaries"] + len(structs[k]["srefs"]))
            if structs else None}


def validate(doc: dict, design: DesignRecord, die: Die) -> list[Finding]:
    out: list[Finding] = []
    if not doc["units"] or abs(doc["units"][1] - DBU_M) > 1e-15:
        out.append(Finding(SEV_ERROR, "gds_units", f"db unit {doc['units']} != 1 nm"))
    top = die.name.upper()[:31]
    if top not in doc["structures"]:
        out.append(Finding(SEV_ERROR, "gds_top", f"top cell {top} missing"))
        return out
    st = doc["structures"][top]
    bb = st["bbox"]
    if not bb or abs(bb[2] - die.width_um) > 0.001 or abs(bb[3] - die.height_um) > 0.001:
        out.append(Finding(SEV_ERROR, "gds_bbox",
                           f"top bbox {bb} does not match die "
                           f"{(die.width_um, die.height_um)}"))
    placed = design.macros_on(die.name)
    if len(st["srefs"]) != len(placed):
        out.append(Finding(SEV_ERROR, "gds_srefs",
                           f"{len(st['srefs'])} SREFs != {len(placed)} placed macros"))
    for cell in {m.cell[:31] for m in placed}:
        if cell not in doc["structures"]:
            out.append(Finding(SEV_ERROR, "gds_cell", f"referenced cell {cell} has no structure"))
    if LAYER_KEEPOUT not in st["layers"]:
        out.append(Finding(SEV_WARN, "gds_keepout", "RoT keep-out layer absent"))
    if LAYER_TSV not in {l for s in doc["structures"].values() for l in s["layers"]}:
        out.append(Finding(SEV_WARN, "gds_tsv", "no TSV geometry in stream"))
    return out
