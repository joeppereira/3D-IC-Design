"""IBIS writer + structural reader (spec 2.7, buffer half only).

Full IBIS-AMI needs a compiled AMI_Init/AMI_GetWave shared library, which is C
work budgeted separately in the spec.  This module emits the .ibs buffer model
and the .ami parameter declaration; the DLL is not faked.

ibischk7 is not installed on this machine, so validate() performs a structural
check and flags that golden-parser validation is still outstanding.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN, provenance_header
from ..canonical import DesignRecord, Link

REQUIRED_KEYWORDS = ("[IBIS Ver]", "[File Name]", "[File Rev]", "[Component]",
                     "[Manufacturer]", "[Package]", "[Pin]", "[Model]",
                     "[Voltage Range]", "[Pulldown]", "[Pullup]", "[Ramp]", "[End]")


def _iv_table(vdd: float, rising: bool) -> list[tuple[float, float, float, float]]:
    """Monotonic I-V table; currents in A, typ/min/max columns."""
    rows = []
    for i in range(11):
        v = -vdd + i * (3.0 * vdd / 10.0)
        # Simple saturating characteristic; monotonic by construction.
        g = 0.020 if rising else -0.020
        i_typ = g * v / (1.0 + abs(v) / vdd)
        rows.append((v, i_typ, i_typ * 0.85, i_typ * 1.15))
    return rows


def write_ibs(design: DesignRecord, link: Link, path: Path, prov: dict) -> Path:
    vdd = design.vddq_v
    pkg_r, pkg_l, pkg_c = 0.08, 0.35e-9, 0.25e-12     # from the 40um bump grid
    ui_ps = 1000.0 / link.baud_gbd
    L = [provenance_header(prov, "|").rstrip("\n"),
         "[IBIS Ver]       7.0",
         f"[File Name]      {path.name}",
         "[File Rev]       1.0",
         "[Date]           2026-09-19",
         "[Source]         3DIC-X architectural explorer (SYNTHETIC buffer model)",
         f"[Notes]          {link.rate_gbps:g}G {link.modulation}, UI {ui_ps:.2f} ps.",
         "|                Buffer characteristics are analytic, not silicon data.",
         "[Disclaimer]     Not for sign-off. Architectural exploration only.",
         "",
         f"[Component]      {link.name}_PHY",
         "[Manufacturer]   3DIC-X",
         "[Package]",
         "| variable       typ         min         max",
         f"R_pkg           {pkg_r:.4f}      {pkg_r * 0.8:.4f}      {pkg_r * 1.2:.4f}",
         f"L_pkg           {pkg_l:.3e}   {pkg_l * 0.8:.3e}   {pkg_l * 1.2:.3e}",
         f"C_pkg           {pkg_c:.3e}   {pkg_c * 0.8:.3e}   {pkg_c * 1.2:.3e}",
         "",
         "[Pin]  signal_name          model_name           R_pin     L_pin     C_pin",
         f"1      TXP                  {link.name}_TX        {pkg_r:.4f}    {pkg_l:.3e} {pkg_c:.3e}",
         f"2      TXN                  {link.name}_TX        {pkg_r:.4f}    {pkg_l:.3e} {pkg_c:.3e}",
         f"3      VDDQ                 POWER                 {pkg_r:.4f}    {pkg_l:.3e} {pkg_c:.3e}",
         "4      VSS                  GND                   NA        NA        NA",
         "",
         f"[Model]          {link.name}_TX",
         "Model_type       Output",
         "Polarity         Non-Inverting",
         "Enable           Active-High",
         "Vinl = 0.2",
         "Vinh = 0.8",
         "C_comp           0.30pF      0.25pF      0.35pF",
         "",
         "[Voltage Range]  "
         f"{vdd:.3f}V     {vdd * 0.95:.3f}V     {vdd * 1.05:.3f}V",
         "[Temperature Range] "
         f"{design.op_temp_c:.1f}       25.0        110.0",
         ""]
    for label, rising in (("[Pulldown]", False), ("[Pullup]", True)):
        L.append(label)
        L.append("| voltage      I(typ)        I(min)        I(max)")
        for v, it, imn, imx in _iv_table(vdd, rising):
            L.append(f"{v:+.4f}      {it:+.6e}  {imn:+.6e}  {imx:+.6e}")
        L.append("")
    dv = 0.6 * vdd
    dt_ns = ui_ps / 3.0 / 1000.0
    L += ["[Ramp]",
          f"dV/dt_r          {dv:.4f}/{dt_ns:.6f}n  {dv * 0.9:.4f}/{dt_ns * 1.1:.6f}n  "
          f"{dv * 1.1:.4f}/{dt_ns * 0.9:.6f}n",
          f"dV/dt_f          {dv:.4f}/{dt_ns:.6f}n  {dv * 0.9:.4f}/{dt_ns * 1.1:.6f}n  "
          f"{dv * 1.1:.4f}/{dt_ns * 0.9:.6f}n",
          "",
          "[End]"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def write_ami(design: DesignRecord, link: Link, path: Path, prov: dict) -> Path:
    """AMI parameter declaration for the equalization 3DIC-X searches over.

    Declares Init-only (statistical) support: GetWave is False because no DLL is
    shipped, and claiming otherwise would break every simulator that tried.
    """
    L = [provenance_header(prov, "|").rstrip("\n"),
         f"(* {link.name}_TX AMI parameters -- 3DIC-X *)",
         f"({link.name}_TX",
         "  (Reserved_Parameters",
         "    (AMI_Version (Usage Info) (Type String) (Value \"7.0\"))",
         "    (Init_Returns_Impulse (Usage Info) (Type Boolean) (Value True))",
         "    (GetWave_Exists (Usage Info) (Type Boolean) (Value False))",
         "    (Use_Init_Output (Usage Info) (Type Boolean) (Value True))",
         f"    (Ignore_Bits (Usage Info) (Type Integer) (Value 100))",
         "  )",
         "  (Model_Specific",
         "    (FFE_Taps (Usage In) (Type Float) (List -0.05 0.0 0.10)",
         "      (Description \"Feed-forward equalizer tap weights searched by GEPA\"))",
         "    (CTLE_Peaking_dB (Usage In) (Type Float) (Range 0.0 0.0 12.0)",
         "      (Description \"Continuous-time linear equalizer peaking\"))",
         "    (DFE_Taps (Usage In) (Type Integer) (Range 4 0 8)",
         "      (Description \"Decision feedback equalizer tap count\"))",
         f"    (Ideal_Baud_Rate (Usage Info) (Type Float) (Value {link.baud_gbd * 1e9:.6e}))",
         "  )",
         ")"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def read_ibs(path: Path) -> dict:
    text = Path(path).read_text()
    def _tbl(name: str) -> list[tuple[float, ...]]:
        m = re.search(rf"\[{name}\](.*?)(?=\n\[|\Z)", text, re.S)
        if not m:
            return []
        rows = []
        for ln in m.group(1).splitlines():
            ln = ln.split("|", 1)[0].strip()
            toks = ln.split()
            if len(toks) >= 2 and all(_num(t) for t in toks[:2]):
                rows.append(tuple(float(t) for t in toks if _num(t)))
        return rows
    return {
        "keywords": re.findall(r"^\[([^\]]+)\]", text, re.M),
        "ibis_ver": (re.search(r"\[IBIS Ver\]\s+([\d.]+)", text) or [None, None])[1],
        "component": (re.search(r"\[Component\]\s+(\S+)", text) or [None, None])[1],
        "models": re.findall(r"^\[Model\]\s+(\S+)", text, re.M),
        "pins": len(re.findall(r"^\d+\s+\S+\s+\S+", text, re.M)),
        "pulldown": _tbl("Pulldown"),
        "pullup": _tbl("Pullup"),
        "has_ramp": "[Ramp]" in text,
        "ends": text.rstrip().endswith("[End]"),
    }


def _num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def validate(doc: dict) -> list[Finding]:
    out: list[Finding] = []
    for kw in REQUIRED_KEYWORDS:
        if kw.strip("[]") not in doc["keywords"]:
            out.append(Finding(SEV_ERROR, "ibis_keyword", f"{kw} missing"))
    if not doc["ends"]:
        out.append(Finding(SEV_ERROR, "ibis_end", "file does not end with [End]"))
    for name in ("pulldown", "pullup"):
        rows = doc[name]
        if len(rows) < 2:
            out.append(Finding(SEV_ERROR, f"ibis_{name}", "I-V table is missing or too short"))
            continue
        vs = [r[0] for r in rows]
        if any(b <= a for a, b in zip(vs, vs[1:])):
            out.append(Finding(SEV_ERROR, f"ibis_{name}", "voltage column is not monotonic"))
        cur = [r[1] for r in rows]
        if any(b < a for a, b in zip(cur, cur[1:])) and any(b > a for a, b in zip(cur, cur[1:])):
            out.append(Finding(SEV_WARN, f"ibis_{name}", "I-V characteristic is non-monotonic"))
    out.append(Finding(SEV_WARN, "ibis_golden_parser",
                       "ibischk7 is not installed here; golden-parser validation "
                       "(spec 2.7 T0 criterion) is still outstanding"))
    return out
