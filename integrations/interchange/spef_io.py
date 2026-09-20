"""SPEF writer + reader (spec 2.4, prerequisite P0-D).

Scope is deliberate: SPEF is emitted only for the nets 3DIC-X actually models
(SerDes differential pairs, PDN trunks, vertical TSV/bond nets).  A fabricated
full-chip SPEF for 4.2e9 cells would be worse than no SPEF, so *DESIGN_FLOW
declares ANALYTIC_SURROGATE and the header names the model.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN, provenance_header
from ..canonical import DesignRecord, Net

SEGMENTS = 4          # distributed pi-segments per modeled net
RES_TOL = 1e-6
CAP_TOL = 1e-6


def _split(total: float, parts: int) -> list[float]:
    """Split `total` into `parts` values that sum to it exactly at 6 decimals.

    Writing total/parts rounded independently leaves a residual (4 x 0.727931 =
    2.911724 against a 2.911725 header). The residual goes into the last term so
    sum(*RES) and sum(*CAP) match the header bit for bit.
    """
    each = round(total / parts, 6)
    vals = [each] * parts
    vals[-1] = round(total - each * (parts - 1), 6)
    return vals


def _net_lines(net: Net) -> list[str]:
    c_ff = round(net.c_pf * 1000.0, 6)
    seg_r = _split(net.r_ohm, SEGMENTS)
    node_c = _split(c_ff, SEGMENTS + 1)
    L = [f"*D_NET {net.name} {c_ff:.6f}", "*CONN"]
    for idx, pin in enumerate(net.pins):
        if ":" in pin or "/" in pin:
            inst, _, port = pin.replace("/", ":").partition(":")
            L.append(f"*I {inst}:{port} {'I' if idx else 'O'}")
        else:
            L.append(f"*P {pin} {'I' if idx else 'O'}")
    L.append("*CAP")
    for i, c in enumerate(node_c):
        L.append(f"{i + 1} {net.name}:{i + 1} {c:.6f}")
    L.append("*RES")
    for i, r in enumerate(seg_r):
        L.append(f"{i + 1} {net.name}:{i + 1} {net.name}:{i + 2} {r:.6f}")
    L.append("*END")
    return L


def write(design: DesignRecord, path: Path, prov: dict) -> Path:
    L = [provenance_header(prov, "//").rstrip("\n"),
         '*SPEF "IEEE 1481-1998"',
         f'*DESIGN "{design.project}"',
         '*DATE "2026-09-19"',
         '*VENDOR "3DIC-X Architectural Explorer"',
         '*PROGRAM "integrations.interchange.spef_io"',
         '*VERSION "1.0"',
         '*DESIGN_FLOW "ANALYTIC_SURROGATE" "PIN_CAP NONE" "NAME_SCOPE LOCAL"',
         "*DIVIDER /", "*DELIMITER :", "*BUS_DELIMITER [ ]",
         "*T_UNIT 1 PS", "*C_UNIT 1 FF", "*R_UNIT 1 OHM", "*L_UNIT 1 HENRY", ""]
    for net in design.nets:
        L += _net_lines(net) + [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def read(path: Path) -> dict:
    """Independent parser: returns per-net totals for correlation."""
    text = Path(path).read_text()
    header = dict(re.findall(r'^\*(\w+)\s+"?([^"\n]+)"?', text, re.M))
    nets: dict[str, dict] = {}
    for block in re.finditer(r"^\*D_NET\s+(\S+)\s+([\d.eE+-]+)(.*?)^\*END\s*$",
                             text, re.S | re.M):
        name, total_c, body = block.group(1), float(block.group(2)), block.group(3)
        cap_sec = body.split("*CAP", 1)[-1].split("*RES", 1)[0]
        res_sec = body.split("*RES", 1)[-1] if "*RES" in body else ""
        caps = [float(m.group(1)) for m in
                re.finditer(r"^\d+\s+\S+\s+([\d.eE+-]+)\s*$", cap_sec, re.M)]
        ress = [float(m.group(1)) for m in
                re.finditer(r"^\d+\s+\S+\s+\S+\s+([\d.eE+-]+)\s*$", res_sec, re.M)]
        conns = re.findall(r"^\*([IP])\s+(\S+)\s+([IOB])\s*$", body, re.M)
        nets[name] = {"total_c_ff": total_c, "sum_c_ff": sum(caps),
                      "sum_r_ohm": sum(ress), "n_cap": len(caps), "n_res": len(ress),
                      "conns": conns,
                      "r_ohm": sum(ress), "c_pf": total_c / 1000.0}
    return {"header": header, "nets": nets,
            "units": {"c": header.get("C_UNIT"), "r": header.get("R_UNIT")}}


def validate(doc: dict, design: DesignRecord) -> list[Finding]:
    out: list[Finding] = []
    if "ANALYTIC_SURROGATE" not in doc["header"].get("DESIGN_FLOW", ""):
        out.append(Finding(SEV_ERROR, "spef_flow",
                           "*DESIGN_FLOW must declare ANALYTIC_SURROGATE so no downstream "
                           "tool mistakes these parasitics for a real extraction"))
    if doc["units"]["c"] != "1 FF" or doc["units"]["r"] != "1 OHM":
        out.append(Finding(SEV_ERROR, "spef_units", f"unexpected units {doc['units']}"))
    for net in design.nets:
        got = doc["nets"].get(net.name)
        if got is None:
            out.append(Finding(SEV_ERROR, "spef_net", f"{net.name} missing from SPEF"))
            continue
        if abs(got["sum_r_ohm"] - round(net.r_ohm, 6)) > RES_TOL:
            out.append(Finding(SEV_ERROR, "spef_res",
                               f"{net.name} sum(R)={got['sum_r_ohm']} != {net.r_ohm}"))
        if abs(got["sum_c_ff"] - round(net.c_pf * 1000.0, 6)) > CAP_TOL:
            out.append(Finding(SEV_ERROR, "spef_cap",
                               f"{net.name} sum(C)={got['sum_c_ff']}fF != header "
                               f"{net.c_pf * 1000.0}fF"))
        if got["n_res"] != SEGMENTS or got["n_cap"] != SEGMENTS + 1:
            out.append(Finding(SEV_WARN, "spef_topology",
                               f"{net.name} is not a {SEGMENTS}-segment distributed net"))
        if not got["conns"]:
            out.append(Finding(SEV_WARN, "spef_conn", f"{net.name} has no *CONN entries"))
    return out
