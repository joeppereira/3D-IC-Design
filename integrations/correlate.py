"""Vendor result vs surrogate prediction -> published error band + calibration.

This is the half of the loop that makes the surrogates defensible: emit a deck,
let a licensed tool compute the truth, measure the delta, and feed a calibration
back into the physics-AI environment (spec 5, tier T2).

Guard rail: if the "vendor" file was produced by this repo's own emitters, the
comparison is a plumbing test and is reported as T0.  Correlating against our own
synthetic output and calling it T2 would be self-validation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

from .base import (REPO_ROOT, TIER_EMITTED, TIER_CORRELATED, Finding,
                   SEV_ERROR, SEV_WARN, SEV_INFO, git_sha, run_id)
from .canonical import DesignRecord, Link

# Published tolerance bands. Exceeding one is not a crash -- it is the finding.
BAND_TJ_C = 5.0
BAND_DROOP_MV = 2.0
BAND_RC_PCT = 20.0
BAND_IL_DB = 2.0

SELF_MARKER = "3DIC-X handoff artifact"
FIXTURE_MARKER = "3DIC-X TEST FIXTURE"


@dataclass
class Correlation:
    quantity: str
    tool: str
    surrogate: float | None
    vendor: float | None
    delta: float | None
    unit: str
    band: float
    verdict: str                      # PASS | REVIEW | NO_PREDICTION
    tier: str
    detail: dict = field(default_factory=dict)
    calibration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["detail"] = {k: v for k, v in self.detail.items()
                       if not isinstance(v, np.ndarray)}
        return d

    def finding(self) -> Finding:
        if self.verdict == "NO_PREDICTION":
            return Finding(SEV_WARN, f"correlate:{self.quantity}",
                           "no surrogate prediction to compare against")
        sev = SEV_INFO if self.verdict == "PASS" else SEV_WARN
        return Finding(sev, f"correlate:{self.quantity}",
                       f"{self.tool}: surrogate {self.surrogate:.4g} vs vendor "
                       f"{self.vendor:.4g} {self.unit} (delta {self.delta:+.4g}, "
                       f"band +/-{self.band:g}) -> {self.verdict} [{self.tier}]")


def is_self_generated(path: Path) -> bool:
    """True when the 'vendor' file came from this repo or from a test fixture.

    Either way the comparison validates plumbing, not physics, so the run is
    reported as T0.
    """
    try:
        head = Path(path).read_bytes()[:4096].decode("utf-8", errors="ignore")
    except OSError:
        return False
    if SELF_MARKER in head or FIXTURE_MARKER in head:
        return True
    side = Path(str(path) + ".provenance.json")
    return side.exists()


def _tier(path: Path) -> str:
    return TIER_EMITTED if is_self_generated(path) else TIER_CORRELATED


def _verdict(delta: float | None, band: float) -> str:
    if delta is None:
        return "NO_PREDICTION"
    return "PASS" if abs(delta) <= band else "REVIEW"


# --- per-quantity correlations ----------------------------------------------
def thermal(design: DesignRecord, vendor: dict, tool: str = "cadence:celsius",
            surrogate_field: np.ndarray | None = None) -> Correlation:
    pred = design.predictions.tj_peak_c
    got = vendor["tj_peak_c"]
    delta = (pred - got) if pred is not None else None
    detail = {"vendor_hotspot_um": vendor["hotspot_um"],
              "vendor_tj_mean_c": vendor["tj_mean_c"],
              "vendor_points": vendor["n_points"]}
    if surrogate_field is not None and surrogate_field.shape == vendor["field"].shape:
        err = surrogate_field - vendor["field"]
        detail["field_rms_c"] = float(np.sqrt(np.mean(err ** 2)))
        detail["field_max_abs_c"] = float(np.max(np.abs(err)))
    cal = {"thermal_bias_c": round(-delta, 4)} if delta is not None else {}
    return Correlation("tj_peak", tool, pred, got, delta, "C", BAND_TJ_C,
                       _verdict(delta, BAND_TJ_C), _tier(Path(vendor["source"])),
                       detail, cal)


def ir_drop(design: DesignRecord, vendor: dict, tool: str = "cadence:voltus_fi") -> Correlation:
    pred = design.predictions.droop_mv
    got = vendor["worst_droop_mv"]
    delta = (pred - got) if pred is not None else None
    detail = {"worst_net": vendor["worst_net"], "per_net_mv": vendor["per_net_mv"],
              "ripple_target_mv": design.ripple_target_mv,
              "vendor_within_target": got <= design.ripple_target_mv}
    cal = {"droop_scale": round(got / pred, 6)} if pred not in (None, 0) else {}
    return Correlation("worst_droop", tool, pred, got, delta, "mV", BAND_DROOP_MV,
                       _verdict(delta, BAND_DROOP_MV), _tier(Path(vendor["source"])),
                       detail, cal)


def parasitics(design: DesignRecord, vendor: dict,
               tool: str = "synopsys:starrc") -> Correlation:
    """Per-net R/C error distribution; the spec 4.2 loop that retrains the
    surrogate on golden parasitics instead of on rc_extractor.py heuristics."""
    rows = []
    for net in design.nets:
        v = vendor["nets"].get(net.name)
        if not v:
            continue
        for quantity, mine, theirs in (("r", net.r_ohm, v["r_ohm"]),
                                       ("c", net.c_pf, v["c_pf"])):
            if theirs:
                rows.append({"net": net.name, "kind": net.kind, "quantity": quantity,
                             "surrogate": mine, "vendor": theirs,
                             "err_pct": (mine - theirs) / theirs * 100.0})
    if not rows:
        return Correlation("parasitics", tool, None, None, None, "%", BAND_RC_PCT,
                           "NO_PREDICTION", _tier(Path(vendor["source"])),
                           {"matched_nets": 0})
    errs = np.array([r["err_pct"] for r in rows])
    worst = float(np.max(np.abs(errs)))
    by_class: dict[str, list[float]] = {}
    for r in rows:
        by_class.setdefault(f"{r['kind']}_{r['quantity']}", []).append(
            r["vendor"] / r["surrogate"] if r["surrogate"] else 1.0)
    detail = {"matched_entries": len(rows),
              "mean_err_pct": float(errs.mean()),
              "median_err_pct": float(np.median(errs)),
              "p95_abs_err_pct": float(np.percentile(np.abs(errs), 95)),
              "max_abs_err_pct": worst,
              "worst_net": max(rows, key=lambda r: abs(r["err_pct"]))["net"],
              "vendor_flow": vendor.get("flow", "")}
    cal = {"rc_scale_by_class": {k: round(float(np.mean(v)), 6) for k, v in by_class.items()}}
    return Correlation("parasitics", tool, float(errs.mean()), 0.0,
                       float(errs.mean()), "% error", BAND_RC_PCT,
                       "PASS" if worst <= BAND_RC_PCT else "REVIEW",
                       _tier(Path(vendor["source"])), detail, cal)


def channel(design: DesignRecord, link: Link, vendor: dict,
            tool: str = "siemens:hyperlynx") -> Correlation:
    """Insertion loss at Nyquist plus an in-band RMS, against the surrogate's
    own (synthetic) channel."""
    from .interchange.touchstone_io import synth_channel, insertion_loss_db, il_at
    f_mine, s_mine, _ = synth_channel(link, vendor["freqs_hz"])
    il_mine, il_theirs = insertion_loss_db(s_mine), vendor["il_db"]
    nyq = link.nyquist_ghz
    mine_nyq = il_at(f_mine, s_mine, nyq)
    theirs_nyq = float(np.interp(nyq * 1e9, vendor["freqs_hz"], il_theirs))
    band = vendor["freqs_hz"] <= nyq * 1e9
    rms = float(np.sqrt(np.mean((il_mine[band] - il_theirs[band]) ** 2)))
    delta = mine_nyq - theirs_nyq
    detail = {"rms_in_band_db": rms, "nyquist_ghz": nyq,
              "fmax_ghz": float(vendor["freqs_hz"][-1] / 1e9),
              "vendor_ports": vendor["meta"]["n_ports"]}
    cal = {"il_scale_at_nyquist": round(theirs_nyq / mine_nyq, 6)} if mine_nyq else {}
    return Correlation("insertion_loss", tool, mine_nyq, theirs_nyq, delta, "dB",
                       BAND_IL_DB, _verdict(delta, BAND_IL_DB),
                       _tier(Path(vendor["source"])), detail, cal)


# --- reporting + feedback ----------------------------------------------------
def write_report(correlations: list[Correlation], outdir: Path | None = None,
                 rid: str | None = None) -> Path:
    outdir = outdir or (REPO_ROOT / "reports/correlation")
    outdir.mkdir(parents=True, exist_ok=True)
    rid = rid or run_id()
    tiers = {c.tier for c in correlations}
    doc = {
        "run_id": rid,
        "git_sha": git_sha(),
        "claim_tier": TIER_EMITTED if TIER_EMITTED in tiers else TIER_CORRELATED,
        "bands": {"tj_c": BAND_TJ_C, "droop_mv": BAND_DROOP_MV,
                  "rc_pct": BAND_RC_PCT, "il_db": BAND_IL_DB},
        "correlations": [c.to_dict() for c in correlations],
        "note": ("claim_tier T0 means at least one input was generated by this repo, "
                 "so the comparison validates plumbing only -- not physics."),
    }
    path = outdir / "correlation_summary.json"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def write_calibration(correlations: list[Correlation],
                      path: Path | None = None) -> Path:
    """The file the physics-AI side consumes: vendor truth -> surrogate offsets."""
    path = path or (REPO_ROOT / "configs/surrogate_calibration.json")
    merged: dict = {}
    for c in correlations:
        for k, v in c.calibration.items():
            merged[k] = v
    doc = {
        "schema_version": "1.0",
        "run_id": run_id(),
        "git_sha": git_sha(),
        "derived_from": [{"quantity": c.quantity, "tool": c.tool, "tier": c.tier,
                          "verdict": c.verdict} for c in correlations],
        "calibration": merged,
        "usage": ("Apply as post-hoc correction to surrogate outputs, or as the "
                  "training target when retraining (spec 4.2). Only calibration "
                  "derived from tier T2 correlations is physically meaningful."),
        "trustworthy": all(c.tier == TIER_CORRELATED for c in correlations) and bool(correlations),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def load_calibration(path: Path | None = None) -> dict:
    path = path or (REPO_ROOT / "configs/surrogate_calibration.json")
    if not Path(path).exists():
        return {}
    doc = json.loads(Path(path).read_text())
    return doc.get("calibration", {}) if doc.get("trustworthy") else {}


def apply_calibration(design: DesignRecord, cal: dict | None = None) -> dict:
    """What the surrogate's numbers become once vendor truth is folded in."""
    cal = cal if cal is not None else load_calibration()
    p = design.predictions
    out = {"tj_peak_c": p.tj_peak_c, "droop_mv": p.droop_mv,
           "insertion_loss_db": p.insertion_loss_db, "applied": sorted(cal)}
    if p.tj_peak_c is not None and "thermal_bias_c" in cal:
        out["tj_peak_c"] = round(p.tj_peak_c + cal["thermal_bias_c"], 4)
    if p.droop_mv is not None and "droop_scale" in cal:
        out["droop_mv"] = round(p.droop_mv * cal["droop_scale"], 4)
    if p.insertion_loss_db is not None and "il_scale_at_nyquist" in cal:
        out["insertion_loss_db"] = round(p.insertion_loss_db * cal["il_scale_at_nyquist"], 4)
    return out
