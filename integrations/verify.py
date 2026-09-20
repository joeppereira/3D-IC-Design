"""Cross-consistency verification: emitted artifacts vs the silicon flow itself.

The T0 format tests prove each artifact is well-formed.  They cannot tell you
whether the artifact agrees with what the silicon workflow actually concluded.
This module checks that, and it is deliberately loud: a handoff deck that
contradicts its own source data is worse than no deck, because a downstream
engineer has no way to see the contradiction.

    python -m integrations.cli verify

Exit status is non-zero when any ERROR-level inconsistency is present.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from .base import REPO_ROOT, Finding, SEV_ERROR, SEV_WARN, SEV_INFO
from .canonical import DesignRecord, MATERIAL_LOSS_DB_PER_INCH
from .interchange import touchstone_io as ts

STALE_DAYS = 30
IL_DISAGREEMENT_DB = 3.0
SIGNAL_R_PLAUSIBLE_OHM = 1000.0
DAY = 86400.0


def _mtime(path: Path) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def check_input_freshness(design: DesignRecord) -> list[Finding]:
    """The handoff is only as current as the silicon-flow output it reads."""
    out: list[Finding] = []
    golden = Path(design.sources.get("golden_config", ""))
    deck = Path(design.sources.get("vector_deck", ""))
    g_t = _mtime(golden)
    if not g_t:
        out.append(Finding(SEV_ERROR, "golden_missing",
                           f"{golden} does not exist; the design record is a default"))
        return out
    newer = {p: _mtime(REPO_ROOT / p) for p in
             ("configs/3dic_x_vector_deck.json", "reports/final_design_audit.json",
              "reports/power_reduction_proof.json", "reports/technical_audit_v5.md")}
    latest_name, latest_t = max(newer.items(), key=lambda kv: kv[1])
    age_days = (latest_t - g_t) / DAY
    if age_days > STALE_DAYS:
        out.append(Finding(SEV_ERROR, "stale_golden_config",
                           f"{golden.name} is {age_days:.0f} days older than "
                           f"{latest_name}. Every emitted artifact describes the "
                           "older design; re-run the silicon flow before handoff"))
    else:
        out.append(Finding(SEV_INFO, "input_freshness",
                           f"golden_config is within {STALE_DAYS} days of the reports"))
    return out


def check_project_identity(design: DesignRecord) -> list[Finding]:
    """The record's project name must match the design the repo documents."""
    deck_path = Path(design.sources.get("vector_deck", ""))
    try:
        deck_id = json.loads(deck_path.read_text()).get("design_id", "")
    except Exception:
        return []
    name = design.project
    if not deck_id:
        return []
    family = re.split(r"[_\s-]", deck_id)[0].lower()
    if family and family not in name.lower():
        return [Finding(SEV_ERROR, "project_identity",
                        f"golden_config names '{name}' but the vector deck is "
                        f"'{deck_id}'. The handoff is describing a different design "
                        "than the one the reports discuss")]
    return [Finding(SEV_INFO, "project_identity", f"'{name}' consistent with '{deck_id}'")]


def check_surrogate_verdict(design: DesignRecord) -> list[Finding]:
    """If the flow's own SI verdict is a failure, say so before emitting."""
    out: list[Finding] = []
    p = design.predictions
    if p.eye_margin_ui is not None and p.eye_margin_ui <= 0.0:
        out.append(Finding(SEV_ERROR, "surrogate_verdict",
                           f"the silicon flow reports eye_width_ui = {p.eye_margin_ui} "
                           "(closed eye). Artifacts emitted from this record describe a "
                           "link the flow itself says does not work"))
    if p.tj_peak_c is not None and p.tj_peak_c > 125.0:
        out.append(Finding(SEV_ERROR, "thermal_verdict",
                           f"peak Tj {p.tj_peak_c} C exceeds a 125 C junction limit"))
    return out


def check_channel_agreement(design: DesignRecord) -> list[Finding]:
    """The emitted Touchstone must agree with the IL the surrogate reports.

    This is the check that catches a repo carrying two incompatible loss models.
    """
    out: list[Finding] = []
    claimed = design.predictions.insertion_loss_db
    if claimed is None or not design.links:
        return out
    link = design.links[0]
    freqs, s, _ = ts.synth_channel(link)
    emitted = ts.il_at(freqs, s, link.nyquist_ghz)
    delta = claimed - emitted
    if abs(delta) > IL_DISAGREEMENT_DB:
        out.append(Finding(SEV_ERROR, "il_model_disagreement",
                           f"the silicon flow reports {claimed:.2f} dB insertion loss "
                           f"but the emitted channel for {link.name} is {emitted:.2f} dB "
                           f"at Nyquist ({link.nyquist_ghz:g} GHz) -- a {abs(delta):.1f} dB "
                           "disagreement between two models in the same repo"))
    else:
        out.append(Finding(SEV_INFO, "il_model_agreement",
                           f"surrogate {claimed:.2f} dB vs emitted {emitted:.2f} dB "
                           f"(delta {delta:+.2f} dB)"))
    return out


def check_rc_plausibility(design: DesignRecord) -> list[Finding]:
    """A channel-length net with on-die metal resistance is a modeling error."""
    out: list[Finding] = []
    for net in design.nets:
        if net.kind != "serdes_diff" or net.length_um <= 0:
            continue
        if net.r_ohm > SIGNAL_R_PLAUSIBLE_OHM:
            ohm_per_mm = net.r_ohm / (net.length_um / 1000.0)
            out.append(Finding(SEV_ERROR, "rc_implausible",
                               f"{net.name}: {net.r_ohm:.0f} ohm over "
                               f"{net.length_um / 1000.0:.0f} mm = {ohm_per_mm:.0f} ohm/mm. "
                               "That is on-die metal geometry applied to a channel-length "
                               "trace; a real controlled-impedance link is ~0.1-1 ohm/mm"))
            break            # one finding is enough; the whole class shares the cause
    else:
        out.append(Finding(SEV_INFO, "rc_plausibility",
                           "modeled signal-net resistances are channel-plausible"))
    return out


def check_material_keys(design: DesignRecord) -> list[Finding]:
    """The same dielectric must be spelled the same way in every table."""
    out: list[Finding] = []
    tables = {
        "integrations/canonical.py": set(MATERIAL_LOSS_DB_PER_INCH),
        "serdes_architect/src/si_analyzer.py": _grep_material_keys(
            REPO_ROOT / "serdes_architect/src/si_analyzer.py"),
        "serdes_architect/src/si_analyzer_v3.py": _grep_material_keys(
            REPO_ROOT / "serdes_architect/src/si_analyzer_v3.py"),
    }
    used = {l.material for l in design.links}
    for material in sorted(used):
        missing = [name for name, keys in tables.items() if keys and material not in keys]
        if missing:
            out.append(Finding(SEV_WARN, "material_key_drift",
                               f"'{material}' is not a key in {', '.join(missing)}; "
                               "those modules will silently fall back to a default "
                               "dielectric"))
    spellings = {k for keys in tables.values() for k in keys if k.lower().startswith("megtron")}
    if len(spellings) > 1:
        out.append(Finding(SEV_WARN, "material_spelling",
                           f"the same laminate is spelled {sorted(spellings)} across "
                           "modules"))
    return out


def _grep_material_keys(path: Path) -> set[str]:
    try:
        text = path.read_text()
    except OSError:
        return set()
    return set(re.findall(r'"(\w+)"\s*:\s*\{\s*"loss_per_inch"', text))


def check_stack_coverage(design: DesignRecord) -> list[Finding]:
    """The emitted stackup must cover every layer the packaging spec describes."""
    spec = REPO_ROOT / "reports/assembly_packaging_spec.md"
    try:
        rows = re.findall(r"^\|\s+\*\*([^*]+)\*\*\s+\|\s+\*\*([\d.]+)\s*µm", 
                          spec.read_text(), re.M)
    except OSError:
        return []
    if not rows:
        return []
    documented = {name.strip().lower().replace(" ", "_"): float(t) for name, t in rows}
    emitted = {d.name.lower(): d.thickness_um for d in design.dies}

    # The spec and the golden config use different names for the same die.
    ALIASES = {"kv-search_die": "sram_search_die", "logic_core": "cxl_switch_logic",
               "power_die": "power_delivery_die"}

    out: list[Finding] = []
    missing, renamed = [], []
    for doc_name, thickness in documented.items():
        target = ALIASES.get(doc_name, doc_name)
        if target in emitted:
            if abs(emitted[target] - thickness) > 1e-6:
                out.append(Finding(SEV_ERROR, "stack_thickness",
                                   f"'{doc_name}' is {thickness} um in the packaging spec "
                                   f"but {emitted[target]} um in the emitted stackup"))
            if target != doc_name:
                renamed.append(f"{doc_name} -> {target}")
        else:
            missing.append(doc_name)
    if missing:
        out.append(Finding(SEV_ERROR, "stack_coverage",
                           f"assembly_packaging_spec.md documents {len(documented)} layers "
                           f"but {missing} have no die in the emitted stackup ("
                           f"{len(design.dies)} dies). A thermal solver will see a "
                           "different stack than the spec describes"))
    if renamed:
        out.append(Finding(SEV_WARN, "stack_naming",
                           f"the same die is named differently in the spec and the golden "
                           f"config: {renamed}"))
    if not missing:
        out.append(Finding(SEV_INFO, "stack_coverage",
                           f"all {len(documented)} documented layers are present"))
    return out


def check_power_budget(design: DesignRecord) -> list[Finding]:
    total = design.total_power_w()
    try:
        budget = float(json.loads(
            Path(design.sources["golden_config"]).read_text()).get("max_power_budget_w", 0))
    except Exception:
        return []
    if budget and abs(total - budget) > max(0.01, budget * 0.001):
        return [Finding(SEV_ERROR, "power_budget",
                        f"die powers sum to {total:.3f} W but the budget is {budget:.3f} W")]
    return [Finding(SEV_INFO, "power_budget",
                    f"die powers sum to the {budget:.1f} W budget")]


def check_temperature_consistency(design: DesignRecord, handoff: Path | None) -> list[Finding]:
    """One operating point, spelled identically in every emitted deck."""
    if handoff is None or not handoff.exists():
        return []
    want = f"{design.op_temp_c}"
    seen: dict[str, str] = {}
    for path in sorted(handoff.rglob("*")):
        if path.suffix not in (".sp", ".lib", ".tcl", ".cmd"):
            continue
        for m in re.finditer(r"(?:temp\s*=\s*|\.temp\s+|nom_temperature\s*:\s*|"
                             r"OPERATING_TEMPERATURE:\s*)([\d.]+)", path.read_text()):
            seen[str(path.relative_to(handoff))] = m.group(1)
            break
    bad = {k: v for k, v in seen.items() if v.rstrip("0").rstrip(".") != want.rstrip("0").rstrip(".")}
    if bad:
        return [Finding(SEV_ERROR, "temperature_drift",
                        f"operating point is {want} C but these decks say {bad}")]
    return [Finding(SEV_INFO, "temperature_consistency",
                    f"{len(seen)} deck(s) all use the {want} C operating point")]


def check_def_area(design: DesignRecord, handoff: Path | None) -> list[Finding]:
    if handoff is None:
        return []
    from .interchange.def_io import read as def_read
    out: list[Finding] = []
    for path in sorted(handoff.rglob("*.def")):
        doc = def_read(path)
        die = next((d for d in design.dies if d.name == doc["design"]), None)
        if die is None:
            out.append(Finding(SEV_ERROR, "def_unknown_die",
                               f"{path.name} names design '{doc['design']}' which is not "
                               "in the design record"))
            continue
        if doc["diearea_um"] != (die.width_um, die.height_um):
            out.append(Finding(SEV_ERROR, "def_area_mismatch",
                               f"{path.name} DIEAREA {doc['diearea_um']} != golden "
                               f"{(die.width_um, die.height_um)}"))
    if not out:
        out.append(Finding(SEV_INFO, "def_area", "every DEF matches the golden die sizes"))
    return out


CHECKS = (check_input_freshness, check_project_identity, check_surrogate_verdict,
          check_channel_agreement, check_rc_plausibility, check_material_keys,
          check_stack_coverage, check_power_budget)
HANDOFF_CHECKS = (check_temperature_consistency, check_def_area)


def verify(design: DesignRecord, handoff: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(design))
    for check in HANDOFF_CHECKS:
        findings.extend(check(design, handoff))
    return findings


def summary(findings: list[Finding]) -> dict:
    return {
        "errors": sum(1 for f in findings if f.severity == SEV_ERROR),
        "warnings": sum(1 for f in findings if f.severity == SEV_WARN),
        "info": sum(1 for f in findings if f.severity == SEV_INFO),
        "ok": not any(f.severity == SEV_ERROR for f in findings),
    }
