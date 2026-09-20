"""SPICE deck writer + ngspice validation (spec 2.1/4.1, prerequisite P0-C).

serdes_architect/src/layout/netlist_exporter.py builds its deck from hardcoded
strings and includes a PDK path that does not exist, so nothing downstream can
run it.  Here the topology is built from the DesignRecord and the neutral deck is
validated by actually running ngspice.

Two variants, because they are not interchangeable:
  * neutral  -- LTRA lossy line, runs in ngspice/Xyce today (frequency-independent
                R, so it is an approximation of the channel)
  * primesim -- references the Touchstone file directly; needs PrimeSim/HSPICE
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

from ..base import Finding, SEV_ERROR, SEV_WARN, SEV_INFO, provenance_header
from ..canonical import DesignRecord, Link
from .touchstone_io import (C0, NP_PER_DB, MATERIAL_LOSS_DB_PER_INCH, _group_delay_s)


def _rlgc(link: Link) -> dict:
    """Per-unit-length RLGC for the LTRA model, matched to Z0, velocity and the
    mid-band loss of the same budget the Touchstone model uses."""
    dk, df = link.dk_df
    v = C0 / math.sqrt(dk)
    l_h_m = link.z0_ohm / v
    c_f_m = 1.0 / (link.z0_ohm * v)
    # LTRA R is frequency-independent: match loss at Nyquist/2 rather than at
    # Nyquist so the deck is not pessimistic across the whole band.
    f_match_ghz = max(link.nyquist_ghz / 2.0, 0.1)
    db_per_inch = MATERIAL_LOSS_DB_PER_INCH.get(link.material, 11.6) * math.sqrt(
        f_match_ghz / max(link.nyquist_ghz, 1e-9))
    alpha_np_m = db_per_inch * NP_PER_DB / 0.0254
    return {"r": 2.0 * alpha_np_m * link.z0_ohm, "l": l_h_m, "g": 0.0, "c": c_f_m,
            "len": link.reach_mm / 1000.0, "v": v, "f_match_ghz": f_match_ghz}


def write_ngspice(design: DesignRecord, link: Link, path: Path, prov: dict) -> Path:
    p = _rlgc(link)
    ui_ps = 1000.0 / link.baud_gbd
    delay_ps = _group_delay_s(link, link.dk_df[0]) * 1e12
    tstop_ps = delay_ps + 40 * ui_ps
    meas_from = delay_ps + 10 * ui_ps
    vdd = design.vddq_v
    droop = (design.predictions.droop_mv or 0.0) / 1000.0

    L = [f"* 3DIC-X {design.project} -- {link.name} {link.rate_gbps:g}G "
         f"{link.modulation} channel (ngspice-runnable)",
         provenance_header(prov, "*").rstrip("\n"),
         f"* channel: {link.material} {link.reach_mm}mm, Z0={link.z0_ohm:g}ohm, "
         f"delay={delay_ps:.1f}ps, UI={ui_ps:.2f}ps",
         f"* LTRA R matched at {p['f_match_ghz']:.1f} GHz -- frequency-independent;"
         " the .s4p is the accurate channel",
         "",
         f".options temp={design.op_temp_c} reltol=1e-3 method=gear",
         f".param vdd={vdd:.4f} vdroop={droop:.6f}",
         "",
         "* --- supply with the droop the FNO surrogate predicts ---",
         "Vsup vdd 0 DC 'vdd - vdroop'",
         "",
         "* --- TX: PAM4 half-rate pattern into a source-terminated driver ---",
         f"Vtx txin 0 PULSE(0 'vdd - vdroop' 0 {ui_ps / 3:.4f}p {ui_ps / 3:.4f}p "
         f"{ui_ps:.4f}p {2 * ui_ps:.4f}p)",
         f"Rsrc txin tx {link.z0_ohm:g}",
         "",
         "* --- channel ---",
         f".model chan_{link.name} ltra rel=1 r={p['r']:.6g} l={p['l']:.6g} "
         f"g={p['g']:.6g} c={p['c']:.6g} len={p['len']:.6g}",
         f"O_{link.name} tx 0 rx 0 chan_{link.name}",
         "",
         "* --- RX termination + pad capacitance ---",
         f"Rterm rx 0 {link.z0_ohm:g}",
         "Cpad rx 0 30f",
         "",
         f".tran {ui_ps / 20:.4f}p {tstop_ps:.3f}p",
         f".measure tran vrx_max MAX v(rx) from={meas_from:.3f}p to={tstop_ps:.3f}p",
         f".measure tran vrx_min MIN v(rx) from={meas_from:.3f}p to={tstop_ps:.3f}p",
         f".measure tran vrx_pp PARAM='vrx_max-vrx_min'",
         f".measure tran vtx_pp MAX v(tx) from={meas_from:.3f}p to={tstop_ps:.3f}p",
         ".end"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


def write_primesim(design: DesignRecord, link: Link, path: Path, prov: dict,
                   s4p_rel: str) -> Path:
    """PrimeSim HSPICE/XA deck: real hierarchy, Touchstone channel, per-ROI
    temperature injection (the 'physics injection' GEMINI.md describes)."""
    ui_ps = 1000.0 / link.baud_gbd
    L = [f"* 3DIC-X {design.project} -- {link.name} PrimeSim HSPICE/XA testbench",
         provenance_header(prov, "*").rstrip("\n"),
         "* Requires PrimeSim; the S-parameter channel is not ngspice-compatible.",
         "",
         f".temp {design.op_temp_c}",
         f".param vddq={design.vddq_v:.4f} vdd_core={design.vdd_v:.4f}",
         f".param ui={ui_ps:.4f}p",
         "",
         "* --- ROI temperature injection from the 3D-FDM/FNO solution ---"]
    for d in design.dies:
        L.append(f"* .temp_region {d.name} {design.op_temp_c:.1f} "
                 f"(thickness {d.thickness_um}um, {d.power_w}W)")
    L += ["",
          "* --- vertical PDN: power die -> logic through TSV/hybrid bond ---"]
    for net in design.nets:
        if net.kind == "vertical":
            L.append(f"R_{net.name} vddq_in vddq_core {net.r_ohm:.6g}")
            L.append(f"C_{net.name} vddq_core 0 {net.c_pf:.6g}p")
    L += ["",
          f"* --- {link.name}: Touchstone channel, ports 1,2=TX P/N 3,4=RX P/N ---",
          f".model chan_{link.name} S tstonefile='{s4p_rel}' "
          "interpolation=linear extrapolation=step",
          f"S_{link.name} txp txn rxp rxn 0 mname=chan_{link.name}",
          "",
          "Vtxp txp 0 DC 0 PULSE(0 vddq 0 'ui/3' 'ui/3' 'ui' '2*ui')",
          "Vtxn txn 0 DC 0 PULSE(vddq 0 0 'ui/3' 'ui/3' 'ui' '2*ui')",
          f"Rrxp rxp 0 {link.z0_ohm / 2:g}",
          f"Rrxn rxn 0 {link.z0_ohm / 2:g}",
          "",
          ".tran 'ui/50' '200*ui'",
          ".meas tran eye_height PP v(rxp,rxn) from='100*ui' to='200*ui'",
          ".probe tran v(rxp) v(rxn) v(rxp,rxn)",
          ".end"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    return path


# --- ngspice execution (the one external validator this machine has) ---------
def ngspice_available() -> bool:
    return shutil.which("ngspice") is not None


_MEAS = re.compile(r"^(\w+)\s*=\s*([-\d.eE+]+)", re.M)


def run_ngspice(path: Path, timeout: int = 240) -> dict:
    if not ngspice_available():
        return {"ok": False, "skipped": True, "reason": "ngspice not installed"}
    proc = subprocess.run(["ngspice", "-b", str(path)], capture_output=True,
                          text=True, timeout=timeout, cwd=str(path.parent))
    log = proc.stdout + proc.stderr
    measures = {k: float(v) for k, v in _MEAS.findall(log)
                if k.startswith("vrx") or k.startswith("vtx") or k.startswith("eye")}
    fatal = [ln for ln in log.splitlines()
             if re.search(r"\berror\b|fatal|aborted|singular matrix", ln, re.I)
             and "0 errors" not in ln.lower()]
    return {"ok": proc.returncode == 0 and not fatal, "skipped": False,
            "returncode": proc.returncode, "measures": measures,
            "errors": fatal[:5], "log_tail": log.splitlines()[-15:]}


def validate(result: dict, link: Link, design: DesignRecord) -> list[Finding]:
    out: list[Finding] = []
    if result.get("skipped"):
        out.append(Finding(SEV_WARN, "ngspice", f"deck not executed: {result['reason']}"))
        return out
    if not result["ok"]:
        out.append(Finding(SEV_ERROR, "ngspice_run",
                           f"deck failed in ngspice (rc={result['returncode']}): "
                           f"{result['errors'] or result['log_tail'][-3:]}"))
        return out
    m = result["measures"]
    out.append(Finding(SEV_INFO, "ngspice_run",
                       "deck simulated cleanly in ngspice: " +
                       ", ".join(f"{k}={v:.4g}" for k, v in sorted(m.items()))))
    if "vrx_pp" in m:
        if m["vrx_pp"] <= 0:
            out.append(Finding(SEV_ERROR, "rx_swing", "receiver swing is zero -- "
                               "channel or termination is wrong"))
        elif "vtx_pp" in m and m["vrx_pp"] > m["vtx_pp"] * 1.05:
            out.append(Finding(SEV_ERROR, "passive_gain",
                               f"RX swing {m['vrx_pp']:.4g}V exceeds TX {m['vtx_pp']:.4g}V "
                               "-- a passive channel cannot amplify"))
        else:
            loss_db = 20 * math.log10(m["vtx_pp"] / m["vrx_pp"]) if m.get("vtx_pp") else 0.0
            out.append(Finding(SEV_INFO, "channel_loss",
                               f"time-domain swing loss {loss_db:.2f} dB at "
                               f"{link.rate_gbps:g}G over {link.reach_mm}mm {link.material}"))
    return out
