"""The canonical DesignRecord: one source of truth for every hook.

No hook reads repo JSON directly -- that is how vendor decks drift apart.
Field names carry their units as a suffix (_um, _mm, _w, _ghz) because a silent
um/mm error is the most expensive bug class in this integration (spec 2.8).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .base import (REPO_ROOT, FIDELITY_SURROGATE, FIDELITY_SYNTHETIC)

# Channel properties come from serdes_architect/src/materials.py so the
# interchange layer and the SI analysers cannot drift apart. Loaded by path
# because serdes_architect is not an importable package.
def _load_materials():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_sa_materials", REPO_ROOT / "serdes_architect/src/materials.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _M = _load_materials()
    MATERIAL_LOSS_DB_PER_INCH = {k: v["loss_per_inch"] for k, v in _M.MATERIALS.items()}
    MATERIAL_DK_DF = {k: (v["dk"], v["df"]) for k, v in _M.MATERIALS.items()}
    resolve_material = _M.resolve_or_default
except Exception:                      # keep the layer usable standalone
    _M = None
    MATERIAL_LOSS_DB_PER_INCH = {"FR4": 11.6, "Megtron_7": 3.5, "Twinax": 0.44}
    MATERIAL_DK_DF = {"FR4": (4.3, 0.020), "Megtron_7": (3.4, 0.002),
                      "Twinax": (2.1, 0.0005)}
    def resolve_material(name):
        return (name if name in MATERIAL_LOSS_DB_PER_INCH else "Megtron_7",
                name in MATERIAL_LOSS_DB_PER_INCH)


@dataclass
class Die:
    name: str
    kind: str
    width_um: float
    height_um: float
    thickness_um: float = 50.0
    k_w_mk: float = 130.0
    power_w: float = 0.0
    bspdn: bool = False

    @property
    def area_mm2(self) -> float:
        return (self.width_um / 1000.0) * (self.height_um / 1000.0)


@dataclass
class Interface:
    between: tuple[str, str]
    kind: str                      # hybrid_bond | tsv | c4 | bga
    pitch_um: float
    diameter_um: float | None = None
    aspect_ratio: float | None = None
    liner: str | None = None


@dataclass
class Macro:
    name: str
    cell: str
    die: str
    origin_um: tuple[float, float]
    orient: str = "N"
    size_um: tuple[float, float] = (400.0, 400.0)
    fixed: bool = True


@dataclass
class Stripe:
    layer: str
    width_um: float
    pitch_um: float
    offset_um: float
    net: str = "VDD"


@dataclass
class Net:
    name: str
    kind: str                      # serdes_diff | pdn_trunk | vertical
    r_ohm: float
    c_pf: float
    length_um: float
    pins: tuple[str, ...] = ()


@dataclass
class Link:
    name: str
    rate_gbps: float
    modulation: str
    material: str
    reach_mm: float
    lanes: int = 1
    rj_ps: float = 0.12
    dj_ps: float = 0.45
    z0_ohm: float = 50.0

    @property
    def baud_gbd(self) -> float:
        bits = 2.0 if self.modulation.upper() == "PAM4" else 1.0
        return self.rate_gbps / bits

    @property
    def nyquist_ghz(self) -> float:
        return self.baud_gbd / 2.0

    @property
    def dk_df(self) -> tuple[float, float]:
        return MATERIAL_DK_DF.get(self.material, MATERIAL_DK_DF["FR4"])


@dataclass
class Predictions:
    """What the physics-AI env currently claims. Correlation targets (spec 5)."""
    tj_peak_c: float | None = None
    droop_pct: float | None = None
    droop_mv: float | None = None
    eye_margin_ui: float | None = None
    insertion_loss_db: float | None = None      # total link budget
    channel_loss_db: float | None = None        # channel only -- what a .s4p models
    source: str = "surrogate"


@dataclass
class DesignRecord:
    project: str
    dies: list[Die] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)
    macros: list[Macro] = field(default_factory=list)
    stripes: list[Stripe] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    predictions: Predictions = field(default_factory=Predictions)
    bump_pitch_um: float = 40.0
    bump_count: int = 12400
    tim_thickness_um: float = 25.0
    tim_k_w_mk: float = 5.0
    case_temp_c: float = 45.0
    liquid_flow_lpm: float = 1.5
    interposer_material: str = "Silicon"
    topology: str = "Face_to_Face"
    vdd_v: float = 0.75
    vddq_v: float = 0.85
    ripple_target_mv: float = 15.0
    didt_a_per_ns: float = 450.0
    op_temp_c: float = 98.5
    power_domains: list[str] = field(default_factory=lambda: ["VDD_CORE"])
    sources: dict[str, str] = field(default_factory=dict)

    # -- helpers --------------------------------------------------------------
    def has(self, dotted: str) -> bool:
        cur: Any = self
        for part in dotted.split("."):
            cur = getattr(cur, part, None) if not isinstance(cur, dict) else cur.get(part)
            if cur is None:
                return False
        return not (isinstance(cur, (list, tuple, dict)) and len(cur) == 0)

    def die(self, name: str) -> Die:
        for d in self.dies:
            if d.name == name:
                return d
        raise KeyError(name)

    def macros_on(self, die: str) -> list[Macro]:
        return [m for m in self.macros if m.die == die]

    def total_power_w(self) -> float:
        return sum(d.power_w for d in self.dies)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["interfaces"] = [{**asdict(i), "between": list(i.between)} for i in self.interfaces]
        return d

    def sha256(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()

    def fidelity_of(self, quantity: str) -> str:
        """Channel/SI comes from a dB-per-inch table -> SYNTHETIC. Thermal/PI
        come from the FNO/FDM surrogates -> SURROGATE."""
        return FIDELITY_SYNTHETIC if quantity in ("channel", "si", "eye") else FIDELITY_SURROGATE


# --- Loaders -----------------------------------------------------------------
def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _snap(val: float, grid: float = 10.0) -> float:
    """Same 10um snapping grid as serdes_architect/src/layout/gen_def.py."""
    return round(val / grid) * grid


def derive_macros(die: Die, count: int = 8, pitch_um: float = 1800.0) -> list[Macro]:
    """Placement model extracted from gen_def.py (spec P0-B).

    gen_def.py computes these origins and serializes them straight to OpenROAD
    Tcl; DEF needs the same numbers, so the geometry lives here and both
    serializers consume it.
    """
    macros: list[Macro] = []
    w, h = die.width_um, die.height_um
    for i in range(count):
        nx = _snap(1000 + i * pitch_um)
        macros.append(Macro(f"SERDES_N_{i}", "SERDES_224G_PHY", die.name,
                            (nx, _snap(h - 1500)), "N", (600.0, 900.0)))
        macros.append(Macro(f"SERDES_S_{i}", "SERDES_224G_PHY", die.name,
                            (nx, _snap(500)), "N", (600.0, 900.0)))
    for i in range(count):
        wy = _snap(1000 + i * pitch_um)
        macros.append(Macro(f"UCIE_W_{i}", "UCIE2_PHY", die.name,
                            (_snap(500), wy), "E", (900.0, 600.0)))
        macros.append(Macro(f"UCIE_E_{i}", "UCIE2_PHY", die.name,
                            (_snap(w - 1500), wy), "W", (900.0, 600.0)))
    return macros


def load_design(golden: Path | str | None = None,
                vector_deck: Path | str | None = None) -> DesignRecord:
    """Assemble the DesignRecord from the physics-AI environment's own outputs."""
    golden_p = Path(golden) if golden else REPO_ROOT / "physics_accelerated/results/golden_config.json"
    deck_p = Path(vector_deck) if vector_deck else REPO_ROOT / "configs/3dic_x_vector_deck.json"
    g, deck = _load(golden_p), _load(deck_p)

    pkg = g.get("packaging", {})
    hier = g.get("die_hierarchy", {})
    phys = deck.get("physical_vectors", {})
    thick = phys.get("die_thickness_vectors", {})
    k_map = g.get("voxel_stack_params", {}).get("k_map", {})
    bc = deck.get("thermal_boundary_conditions", {})
    noise = deck.get("electrical_noise_deck", {})
    jitter = noise.get("serdes_jitter_decomposition_ps", {})
    pdn_noise = noise.get("pdn_noise_mv", {})

    total_power = float(g.get("max_power_budget_w", 60.0))
    thickness_by_role = {
        "CXL_Switch_Logic": thick.get("logic_core_um", 50.0),
        "SRAM_Search_Die": thick.get("kv_search_die_um", 50.0),
        "Power_Delivery_Die": thick.get("power_base_die_um", 775.0),
        "DRAM_Stack": thick.get("dram_module_um", 30.0),
    }
    # Power split: logic dominates, SRAM moderate, power die is loss only.
    power_split = {"CXL_Switch_Logic": 0.65, "SRAM_Search_Die": 0.25, "Power_Delivery_Die": 0.10}

    dies: list[Die] = []
    for key in sorted(hier):
        spec = hier[key]
        name = spec.get("name", key)
        size = spec.get("size_mm", [15, 15])
        dies.append(Die(
            name=name,
            kind=spec.get("type", "unknown"),
            width_um=float(size[0]) * 1000.0,
            height_um=float(size[1]) * 1000.0,
            thickness_um=float(thickness_by_role.get(name, 50.0)),
            k_w_mk=float(k_map.get("Die", 140.0)),
            power_w=round(total_power * power_split.get(name, 0.0), 3),
            bspdn="BSPDN" in str(pkg.get("cooling", "")) and name == "CXL_Switch_Logic",
        ))
    if not dies:  # keep the record usable even with no golden_config on disk
        dies = [Die("CXL_Switch_Logic", "3nm_GAA", 18000.0, 18000.0, 50.0, 140.0, total_power, True)]

    tsv = phys.get("tsv_structure", {})
    bump = phys.get("bump_grid", {})
    interfaces: list[Interface] = []
    if len(dies) >= 2:
        interfaces.append(Interface((dies[0].name, dies[1].name), "hybrid_bond",
                                    pitch_um=float(pkg.get("pitch_um", 5.0))))
    if len(dies) >= 3:
        interfaces.append(Interface((dies[2].name, dies[0].name), "tsv",
                                    pitch_um=float(tsv.get("diameter_um", 2.0)) * 3,
                                    diameter_um=float(tsv.get("diameter_um", 2.0)),
                                    aspect_ratio=float(str(tsv.get("aspect_ratio", "10:1")).split(":")[0]),
                                    liner=tsv.get("liner_material", "TaN/Ta")))
    interfaces.append(Interface((dies[-1].name, "package"), "c4",
                                pitch_um=float(bump.get("pitch_um", 40.0))))

    top = dies[0]
    macros = derive_macros(top)
    stripes = [Stripe("Metal4", 0.5, 10.0, 2.0), Stripe("Metal10", 2.0, 50.0, 5.0)]

    rc = g.get("rc_extraction", {})
    reach_mm = float(g.get("reach_mm", 300.0))
    nets = build_nets(rc, reach_mm, n_links=8)

    rate = float(g.get("target_bandwidth_gbps", 224.0))
    cons = g.get("constraints", {})
    links = [Link(name=f"LINK_{i}", rate_gbps=rate,
                  modulation=cons.get("modulation", "PAM4"),
                  material=resolve_material(pkg.get("material_name"))[0],
                  reach_mm=reach_mm, lanes=1,
                  rj_ps=float(jitter.get("random_jitter", 0.12)),
                  dj_ps=float(jitter.get("deterministic_jitter", 0.45)))
             for i in range(4)]

    ir = g.get("ir_drop_signoff", g.get("ir_drop_verification", {}))
    audit = _load(REPO_ROOT / "reports/final_design_audit.json")
    sota = audit.get("results", {}).get("skydiscover_sota", {})
    si = g.get("si_analysis_v3", {})
    vdd = float(pkg.get("vddq_v", 0.85))
    preds = Predictions(
        tj_peak_c=float(sota.get("temp_c")) if sota.get("temp_c") is not None else None,
        droop_pct=float(ir["droop_percentage"]) if "droop_percentage" in ir else None,
        droop_mv=(vdd - float(ir["min_voltage"])) * 1000.0 if "min_voltage" in ir else None,
        eye_margin_ui=float(si["eye_width_ui"]) if "eye_width_ui" in si else None,
        insertion_loss_db=float(si["loss"]) if "loss" in si else None,
        channel_loss_db=(float(si["loss_breakdown_db"]["channel"])
                         if isinstance(si.get("loss_breakdown_db"), dict)
                         and "channel" in si["loss_breakdown_db"] else None),
        source="FNO/3D-FDM surrogate + analytic SI",
    )

    return DesignRecord(
        project=g.get("project_name", deck.get("design_id", "3DIC-X")),
        dies=dies, interfaces=interfaces, macros=macros, stripes=stripes,
        nets=nets, links=links, predictions=preds,
        bump_pitch_um=float(bump.get("pitch_um", 40.0)),
        bump_count=int(bump.get("total_count", 12400)),
        tim_thickness_um=float(bc.get("tim_thickness_um", 25.0)),
        case_temp_c=float(bc.get("heatsink_case_temp_c", 45.0)),
        liquid_flow_lpm=float(bc.get("liquid_flow_rate_lpm", 1.5)),
        interposer_material=pkg.get("interconnect", "Silicon"),
        topology=pkg.get("topology", "3D_Stacked_SoP"),
        vdd_v=float(pkg.get("vddq_range", [0.75, 0.85])[0]),
        vddq_v=vdd,
        ripple_target_mv=float(pdn_noise.get("ripple_target", 15.0)),
        didt_a_per_ns=float(pdn_noise.get("di_dt_event_max_amps_per_ns", 450.0)),
        op_temp_c=float(sota.get("temp_c", 98.5)),
        power_domains=deck.get("logical_structure", {}).get(
            "power_domains", ["VDD_CORE", "VDD_SRAM", "VDDQ_SERDES"]),
        sources={"golden_config": str(golden_p), "vector_deck": str(deck_p)},
    )


def build_nets(rc: dict, reach_mm: float, n_links: int = 8) -> list[Net]:
    """Per-net parasitics for the nets 3DIC-X actually models (spec 2.4).

    rc_extractor.py yields one lumped R/C per net *class*; SPEF needs per-net
    values, so the class value is distributed across the instances of that class.
    Deliberately NOT a full-chip extraction: a fabricated 4.2B-cell SPEF would
    be worse than no SPEF at all.
    """
    # Prefer the two-scale extraction: the channel conductor, plus the on-die
    # escape in series. Falls back to the legacy single key.
    r_chan = rc.get("channel_r_ohm")
    if r_chan is not None:
        r_sig = float(r_chan) + float(rc.get("escape_r_ohm_diff", 0.0))
        c_sig = float(rc.get("channel_c_pf", 0.0)) + float(rc.get("escape_c_pf", 0.0))
    else:
        r_sig = float(rc.get("m7_signal_r_ohm", 112500.0))
        c_sig = float(rc.get("m7_signal_c_pf", 20.718))
    r_pdn = float(rc.get("m10_pdn_r_ohm", 4500.0))
    length_um = reach_mm * 1000.0
    nets: list[Net] = []
    for i in range(n_links):
        for pol in ("P", "N"):
            nets.append(Net(f"LINK_{i}_TX_{pol}", "serdes_diff",
                            r_ohm=r_sig / n_links, c_pf=c_sig / n_links,
                            length_um=length_um,
                            pins=(f"SERDES_N_{i % 8}/TX{pol}", f"PAD_{i}_{pol}")))
    for i, dom in enumerate(("VDD_CORE", "VDD_SRAM", "VDDQ_SERDES")):
        nets.append(Net(dom, "pdn_trunk", r_ohm=r_pdn / 3.0, c_pf=c_sig * 2.0,
                        length_um=length_um, pins=(f"PDN_TAP_{i}",)))
    nets.append(Net("VDD_VERTICAL_TSV", "vertical", r_ohm=0.045, c_pf=0.012,
                    length_um=775.0, pins=("PWR_DIE/VOUT", "LOGIC/VDD_IN")))
    return nets
