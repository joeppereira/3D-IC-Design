# 🔌 EDA Vendor Integration & Hook Specification
**Project**: 3DIC-X Architectural Explorer
**Spec Version**: 1.0 (2026-09-19)
**Status**: Proposed — Phase 0 not yet implemented
**Scope**: Turn 3DIC-X outputs into artifacts that real production EDA flows consume, without claiming sign-off authority.

---

## 0. Why This Spec Exists

3DIC-X currently ends at its own surrogates. The physics is real, the search is real, but the **exit path is not**: a surrogate result that cannot be handed to a licensed tool is an internal number, not an engineering claim.

Current honest state of the exit path:

| Artifact | File | Actual state |
| :--- | :--- | :--- |
| SPICE deck | `serdes_architect/src/layout/netlist_exporter.py` | Hardcoded string template. No topology from the solved design; `.include` points at a non-existent PDK path. |
| GDSII stream-out | `serdes_architect/scripts/gds_export.tcl` | Every functional command is commented out. `puts` statements only. |
| DEF / floorplan | `serdes_architect/src/layout/gen_def.py` | Emits OpenROAD **Tcl**, not DEF. Real placements, real PDN stripes — but no DEF/LEF handoff file. |
| Parasitics | `serdes_architect/src/layout/rc_extractor.py` | Lumped R/C per net *class*, analytic. Not per-net, not SPEF. |
| Channel / SI | `serdes_architect/src/si_analyzer.py` | dB-per-inch loss waterfall heuristic. No S-parameters. |
| PDK | `serdes_architect/pdk/*.lef` | LEF abstracts exist (`generic_3nm.lef`, `macros.lef`) — the one real interchange asset in the repo. |

The integration work below is therefore ordered **vendor-neutral first**. One interchange layer makes the integration claim true for Cadence, Synopsys, and Siemens simultaneously; going vendor-first would triple the work and still leave the core gap (no standard artifacts) unfixed.

### 0.1 The Claim Ladder (non-negotiable)

Every integration claim in `README.md`, `GEMINI.md`, or any external document must name its tier.

| Tier | Meaning | Requires |
| :--- | :--- | :--- |
| **T0 — Emitted** | We write a syntactically valid standard file; an open-source parser reads it back losslessly. | No vendor license. Runs in CI. |
| **T1 — Ingested** | A licensed vendor tool opens the artifact and completes its own load/elaborate step with zero errors. | Vendor license. Logged transcript. |
| **T2 — Correlated** | The vendor tool's high-fidelity result is compared to the 3DIC-X surrogate prediction; error band published. | Vendor license + documented deltas. |
| **T3 — Signed off** | Foundry-certified flow, tape-out authority. | **Out of scope for 3DIC-X, permanently.** See `README.md` disclaimer. |

Phase 0 buys T0 for all three vendors. Phases 1–3 buy T1, and T2 only where a correlation target is explicitly defined in §5. **Never write "integrated with Voltus" when the truth is "emits a Voltus-readable deck."**

---

## 1. Hook Architecture

### 1.1 Directory Layout

```
integrations/
  __init__.py
  base.py                   # VendorHook ABC, HookResult, HOOK_REGISTRY
  cli.py                    # python -m integrations.cli emit --target <id>
  canonical.py              # DesignRecord: the single source of truth
  interchange/              # Phase 0 — vendor-neutral
    def_writer.py
    lef_writer.py
    gds_writer.py
    spef_writer.py
    liberty_writer.py
    touchstone_writer.py
    ibis_ami_writer.py
    stackup.py              # canonical stackup -> vendor dialects
  cadence/
    virtuoso_maestro.py     sigrity_edb.py     celsius.py
    voltus_fi.py            allegro_integrion.py
  synopsys/
    primewave.py            primesim.py        starrc.py
    icc3dic.py              continuum.py
  siemens/
    calibre_3dstack.py      hyperlynx.py       innovator3d.py
tests/integrations/         # T0 round-trip tests, no licenses needed
results/handoff/<run_id>/   # all emitted artifacts, never committed
```

### 1.2 The Hook Contract

Every hook is a **pure emitter**. It reads a `DesignRecord`, writes files, and returns a manifest. It never shells out to a vendor binary, never requires a license to run, and never mutates repo state outside `results/handoff/`.

```python
# integrations/base.py
class VendorHook(ABC):
    vendor:  str          # "cadence" | "synopsys" | "siemens" | "neutral"
    tool:    str          # "celsius", "primesim_hspice", "calibre_3dstack", ...
    tier:    str          # highest tier this hook has actually achieved
    requires: list[str]   # canonical fields that must be present

    @abstractmethod
    def emit(self, design: DesignRecord, outdir: Path) -> HookResult: ...

    def validate(self, result: HookResult) -> list[Finding]:
        """T0 self-check with open tooling. Default: schema + parser round-trip."""
```

`HookResult` carries: emitted file paths, SHA-256 per file, the driver script a licensed user runs, the provenance block (§1.4), and any `Finding` list from `validate()`.

This shape is what makes the integration testable: **T0 is fully verifiable in CI with zero vendor licenses.** A hook that cannot pass its own `validate()` does not ship.

### 1.3 Canonical Data Model

One `DesignRecord`, assembled once, consumed by every hook. No hook reads repo JSON directly — that is how vendor decks drift apart.

Sources, all of which already exist:

| `DesignRecord` section | Source |
| :--- | :--- |
| `logical` (cell count, toggle rate, power domains, UPF intent) | `configs/3dic_x_vector_deck.json → logical_structure` |
| `physical` (bump grid, TSV geometry, per-die thickness) | `configs/3dic_x_vector_deck.json → physical_vectors` |
| `stackup` (die order, bond interfaces, TIM, interposer) | `reports/assembly_packaging_spec.md` + `physical_vectors` — **must be promoted to machine-readable JSON; a Markdown table cannot drive Sigrity.** |
| `placement` (macro origins, orientations, keep-outs) | `serdes_architect/src/layout/gen_def.py` |
| `pdn` (stripe layers/width/pitch, BSPDN) | `gen_def.py` PDN section |
| `parasitics` (per-net R/C) | `rc_extractor.py` — **needs per-net extension, see §2.4** |
| `links` (rate, modulation, material, reach, jitter budget) | `configs/proto_*.json`, `sweep_*.json`, `electrical_noise_deck` |
| `thermal_bc` (case temp, flow rate, TIM) | `configs/3dic_x_vector_deck.json → thermal_boundary_conditions` |
| `chosen_point` (the Pareto winner) | `physics_accelerated/results/golden_config.json` + the matching row of `reports/pareto_data.csv` |
| `predictions` (surrogate Tj, droop, eye margin) | `reports/*.json` outputs of Phase 4 |

**Action item P0-A**: the stackup is currently prose. Add `configs/stackup_3dic_x.json` as the authored source and regenerate `assembly_packaging_spec.md` from it, not the reverse.

### 1.4 Provenance Is Mandatory

Every emitted file carries a provenance header (comment syntax per format; a sidecar `.provenance.json` where the format has no comments).

```
* 3DIC-X handoff artifact -- NOT A SIGN-OFF DECK
* run_id:        2026-09-19T14:22:07Z-a3f91c2
* git_sha:       0c18ef90
* design_record: sha256:8b1a...
* generator:     integrations.cadence.celsius v1.0
* fidelity:      SURROGATE  (FNO droop / 3D-FDM thermal / heuristic channel)
* validation:    T0 (klayout 0.29 round-trip OK)
* claim_limit:   Architectural exploration. Re-verify in certified flow before tape-out.
```

`fidelity: SURROGATE` is the line that keeps this honest. A Touchstone file generated from a dB-per-inch heuristic is **synthetic** and must say so — a downstream engineer must never mistake it for measured or field-solved data. Any hook whose upstream data is heuristic sets `fidelity: SYNTHETIC` and `validate()` emits a warning-level `Finding`.

### 1.5 Invocation

```bash
# Emit everything vendor-neutral for the current golden config
python -m integrations.cli emit --target neutral:all \
    --golden physics_accelerated/results/golden_config.json

# One vendor target
python -m integrations.cli emit --target cadence:celsius

# List hooks and their honest tier
python -m integrations.cli status
```

Wire `neutral:all` into `run_full_cycle.sh` as **Phase 5: Handoff**, after the graph gate. Add `regression_suite/run_interchange_qualification.sh` running the T0 suite; it must be green before any vendor phase starts.

---

## 2. Phase 0 — Vendor-Neutral Interchange (do this first)

**Effort: ~5 engineer-days. Credibility: highest per unit effort in this document.** Every flow in §3–§5 consumes these. Ship nothing vendor-specific until Phase 0 is T0-green.

| Format | Writer | Consumed by | T0 validator (open source) |
| :--- | :--- | :--- | :--- |
| **LEF** | `lef_writer.py` | all P&R, all LVS | OpenROAD `read_lef` |
| **DEF** | `def_writer.py` | Innovus, IC Compiler II, Calibre, OpenROAD | OpenROAD `read_def` after `read_lef` |
| **GDSII / OASIS** | `gds_writer.py` | Calibre, Pegasus, PVS, foundry | KLayout / `gdstk` read-back, cell + layer diff |
| **SPEF** | `spef_writer.py` | PrimeTime, Tempus, PrimeSim | OpenROAD `read_spef` |
| **Liberty** | `liberty_writer.py` | all STA | `libertyparse` / OpenROAD `read_liberty` |
| **Touchstone (.sNp)** | `touchstone_writer.py` | Sigrity, HyperLynx, PrimeSim, ADS | `scikit-rf`: passivity, causality, reciprocity |
| **IBIS / IBIS-AMI** | `ibis_ami_writer.py` | Sigrity, HyperLynx, PrimeWave | `ibischk7` golden parser |
| **Stackup JSON** | `stackup.py` | Sigrity/EDB, Celsius, HyperLynx, 3DIC Compiler | schema validation + unit audit |

### 2.1 LEF

Mostly done. `pdk/generic_3nm.lef` and `pdk/macros.lef` exist. Required work:
- Verify every macro instantiated by `gen_def.py` (`SERDES_N_*`, `SERDES_S_*`, `UCIE_W_*`, `UCIE_E_*`) has a matching LEF `MACRO` with `SIZE`, `PIN`, `OBS`.
- Add TSV and hybrid-bond pad cells as LEF macros with real `SIZE` from `physical_vectors.tsv_structure` (2.0 µm) and the 5 µm bond pitch. Without these the 3D interface is invisible to every downstream tool.
- Emit `SITE unithd` definition consistent with the `initialize_floorplan -site unithd` call in `gen_def.py`.

### 2.2 DEF

`gen_def.py` already computes real placements and snaps to a 10 µm grid. Refactor: split the geometry computation from the Tcl serialization, then emit **both** Tcl (OpenROAD) and DEF (vendor) from the same in-memory placement list.

Minimum DEF content: `VERSION`, `UNITS DISTANCE MICRONS 1000`, `DIEAREA` from `die_hierarchy.die_0.size_mm`, `COMPONENTS` with `+ FIXED ( x y ) N|E|W` matching the Tcl `-status FIRM`, `BLOCKAGES` for the 250 µm Caliptra RoT EM keep-out, and `SPECIALNETS` for the M4/M10 PDN stripes.

**One DEF per die.** A 3D stack is N DEFs plus a stack description; do not flatten. The per-die DEF set plus `stackup_3dic_x.json` is exactly what 3DIC Compiler and Calibre 3DSTACK need.

### 2.3 GDSII / OASIS

`gds_export.tcl` is aspirational Tcl. Replace with a real Python writer using `gdstk` (or KLayout's Python API): DEF + LEF + PDK GDS → merged stream. Keep a thin Tcl wrapper only if an OpenROAD-driven path is wanted.

T0 test: stream out, read back, assert cell hierarchy and layer set match the DEF/LEF inputs, and that the top cell bounding box equals `DIEAREA`.

### 2.4 SPEF

Real gap. `rc_extractor.py` returns analytic lumped R/C for two net *classes* (M7 signal pair, M10 PDN trunk). SPEF needs per-net `*D_NET` with distributed `*RES`/`*CAP` sections and `*CONN` to pins.

Scope honestly: emit SPEF for the **nets 3DIC-X actually models** — SerDes differential pairs, PDN trunks, TSV/hybrid-bond vertical nets — each tagged `fidelity: SURROGATE` with the analytic model named in the header. Do not emit a full-chip SPEF; a fabricated 4.2B-cell parasitic file is worse than no file. Header must declare `*DESIGN_FLOW "ANALYTIC_SURROGATE"`.

### 2.5 Liberty

Same discipline. Emit `.lib` for hard macros only (SerDes PHY, UCIe PHY, SRAM stack, shattered logic macros), containing pin direction, `capacitance`, `max_transition`, and power-domain related pins. **Do not emit timing arcs** unless they come from a characterized source — declaring uncharacterized `cell_rise` tables is fabrication. Where an arc is needed structurally, emit it with a `/* provenance: SURROGATE, uncharacterized */` annotation and set the hook's `fidelity` to `SYNTHETIC`.

### 2.6 Touchstone

The credibility centerpiece for the 224G link work, and the place where the current code is weakest: `si_analyzer.py` computes total insertion loss from a dB-per-inch table (`FR4` 11.6, `Megtron_7` 3.5, `Twinax` 0.44). That is a budget calculator, not a channel model.

Two-step plan:
1. **Now (T0, synthetic)**: synthesize a causal, passive, reciprocal 4-port from the existing loss waterfall via a wideband-Debye (Djordjević-Sarkar) dielectric model plus the CILD impedance already described in `GEMINI.md`. Frequency grid: DC → **≥2× Nyquist**. 224 Gbps PAM4 is ~112 GBd, so Nyquist is ~56 GHz and the grid runs DC → 112 GHz at 0.25 GHz spacing; the DC point is computed from the conductor's DC resistance, not extrapolated. Tag `fidelity: SYNTHETIC`. Enforce passivity, causality, reciprocity, and a real, positive DC transmission.
2. **Later (T2)**: replace with output from `physics_accelerated/src/maxwell_em_solver.py` once that solver is validated against a reference structure, or with vendor field-solver data. Only then may the file be described as a field-solved channel.

Two constraints are easy to get wrong and are both enforced in code: for a symmetric 2-port the passivity bound is `|ρ + t| ≤ 1` (its eigenvalues are `ρ ± t`), **not** `|ρ|² + |t|² ≤ 1`; and a scalar-scaled `√f` loss term is not Kramers-Kronig consistent, so the phase must come from a minimum-phase construction plus the physical delay rather than from an ad-hoc `β`.

Emit one `.s4p` per differential link and one `.s8p` per coupled victim/aggressor pair — crosstalk is a first-class output, not a scalar penalty. Port ordering must be declared in the header comment (`1,2 = TX P/N; 3,4 = RX P/N`); mismatched port order is the single most common cause of a downstream engineer getting garbage.

### 2.7 IBIS-AMI

Full AMI is a compiled DLL/`.so` exposing `AMI_Init`/`AMI_GetWave` — that is C/C++ work, not a Python emit. Realistic scope:
- `ibis_ami_writer.py` emits the `.ibs` (buffer I/V, ramp, package RLC from `bump_grid`) and the `.ami` parameter files declaring the FFE/CTLE/DFE topology 3DIC-X already searches over.
- Reference `AMI_Init`/`AMI_GetWave` C sources implementing the equalization model, plus a CMake build. Statistical (`Init`-only) mode first; `GetWave` second.
- T0: `ibischk7` clean on the `.ibs`; `.ami` parses; DLL builds and returns a non-degenerate impulse response for a known channel.

Budget this as its own ~3 days on top of Phase 0's five. It is the artifact that makes the link claim portable across all three vendors, so it is worth the extra time — but do not let it block §2.1–§2.6.

### 2.8 Stackup JSON

Schema (authored in `configs/stackup_3dic_x.json`, consumed by every 3D hook):

```json
{
  "units": {"length": "um", "temperature": "C"},
  "dies": [
    {"name": "dram_stack",   "thickness_um": 30.0,  "material": "Si",
     "k_w_mk": 130.0, "power_w": 15.0, "role": "memory"},
    {"name": "kv_search_die","thickness_um": 50.0,  "material": "Si", "k_w_mk": 130.0},
    {"name": "logic_core",   "thickness_um": 50.0,  "bspdn": true},
    {"name": "power_base",   "thickness_um": 775.0, "role": "mechanical_support"}
  ],
  "interfaces": [
    {"between": ["logic_core","kv_search_die"], "type": "hybrid_bond",
     "pitch_um": 5.0, "count": null},
    {"between": ["power_base","logic_core"], "type": "tsv",
     "diameter_um": 2.0, "aspect_ratio": 10.0, "liner": "TaN/Ta"}
  ],
  "tim": {"thickness_um": 25.0, "k_w_mk": 5.0},
  "boundary": {"case_temp_c": 45.0, "liquid_flow_lpm": 1.5},
  "interposer": {"material": "Silicon", "topology": "Face_to_Face"}
}
```

Units are declared explicitly and validated. A silent µm/mm error is the most expensive class of bug in this entire integration.

---

## 3. Phase 1 — Cadence

Ranked by effort-to-credibility within the vendor.

### 3.1 Celsius Thermal Solver — *highest value, do first*
- **Insertion point**: the high-fidelity check on 3D-FDM / FNO thermal predictions.
- **Emit**: `stackup_3dic_x.json` → Celsius stack definition; per-die power maps as CSV/image grids on the same mesh the solver uses (`physics_accelerated/src/hierarchical_grid_manager.py` already manages the 1 µm / 50 nm ROI mesh); boundary conditions from `thermal_boundary_conditions`; a driver Tcl.
- **Correlation target (T2)**: peak Tj. The repo claims **98.5 °C**. Publish `|ΔTj|` against Celsius and a hotspot-location agreement metric. This single number converts "98 % accurate on validated ROI" from an assertion into a measurement.
- **Effort**: 3 days emit + 1 day correlation write-up (license-gated).

### 3.2 Voltus-Fi — droop
- **Insertion point**: golden check on the FNO's IR-drop/droop predictions.
- **Emit**: per-die DEF `SPECIALNETS` PDN, the switching current profile behind `pdn_noise_mv.di_dt_event_max_amps_per_ns` (450 A/ns) as a time-domain current source set, and the TSV/bond vertical resistance network from §2.8.
- **Correlation target (T2)**: worst-case dynamic droop vs. the 15 mV ripple target from `electrical_noise_deck`. Compare against `serdes_architect/src/thermal/ir_drop_solver.py`.
- **Effort**: 3 days.

### 3.3 Sigrity / EDB stackups — 3D SI
- **Insertion point**: EDB-readable stackup + geometry for the 3D SI models; the field-solved source that eventually replaces §2.6's synthetic Touchstone.
- **Emit**: EDB-compatible stackup (layers, thicknesses, Dk/Df with the frequency-dependent model named explicitly), trace/via geometry for the flyover twinax and package escape, port definitions matching the §2.6 port ordering.
- **Effort**: 4 days. Higher because EDB is a database, not a text format — expect to script against the Sigrity/PyEDB API rather than emit a file.

### 3.4 Virtuoso maestro / ADE Assembler — corner run plan
- **Insertion point**: the Pareto winner's chosen corners become a real ADE Assembler run plan, so the surrogate's corner selection is executed rather than asserted.
- **Emit**: a maestro cellview (`maestro.sdb` via OCEAN/SKILL, or the documented XML/JSON interchange) whose corners/global variables come from the selected `pareto_data.csv` row plus `.temp` (98.5 °C) and `.param VDD` (0.75 V) currently hardcoded in `netlist_exporter.py`. Sweep points come from `configs/sweep_*.json`.
- **Prerequisite**: fix `netlist_exporter.py` first (§6). A maestro run plan pointing at a hardcoded netlist automates nothing.
- **Effort**: 4 days (SKILL/OCEAN learning curve).

### 3.5 Integrity / Allegro X (package)
- **Insertion point**: package side of the 800 mm host-XPU link — the `TWINAX_800MM_MODEL` in `netlist_exporter.py`, currently a name with no model behind it.
- **Emit**: package/board stackup, escape routing constraints, connector and via models for the flyover path.
- **Effort**: 3 days. Lower credibility gain than §3.1–§3.3 for a 3D-IC-focused repo; schedule last in this phase.

---

## 4. Phase 2 — Synopsys

### 4.1 PrimeSim HSPICE / PrimeSim XA — 224G link testbench
- **Insertion point**: replace the fictional deck in `netlist_exporter.py` with a real, runnable netlist.
- **Emit**: a PrimeSim-compatible hierarchical netlist — TX/RX subcircuits, `W`-element or Touchstone-referenced channel (`.model ... s-parameter` from §2.6), per-ROI `.temp` and local supply injection (the "physics injection" already described in `GEMINI.md`), correct analysis statements for the measurement being made.
- **T0**: the deck parses under `ngspice`/`Xyce` with stub models; hierarchy and node connectivity round-trip.
- **Effort**: 4 days. Highest credibility item in the Synopsys phase — it is the "physical → SPICE" leg of the flow claim.

### 4.2 StarRC decks
- **Insertion point**: the parasitics the surrogate is trained on. Today the surrogate trains on `rc_extractor.py`'s analytic values; StarRC is what makes that training data defensible.
- **Emit**: StarRC run scripts (`TCAD_GRD_FILE`, `MAPPING_FILE`, netlist/layout inputs) + a SPEF comparison harness that diffs StarRC SPEF against the §2.4 analytic SPEF per net.
- **Correlation target (T2)**: per-net R and C error distribution. Publish it; then retrain the surrogate on StarRC output. This closes the loop that currently trains physics on heuristics.
- **Effort**: 3 days emit, correlation license-gated.

### 4.3 PrimeWave Design Environment — sweep driver
- **Insertion point**: PrimeWave becomes the sweep driver, replacing the bash-loop sweeps over `configs/sweep_*.json`.
- **Emit**: PrimeWave setup describing the corner/parameter cross-product already enumerated in `configs/sweep_*.json` (rate × modulation × clocking × equalization) and the `run_pareto_matrix.sh` matrix.
- **Effort**: 3 days. Depends on §4.1.

### 4.4 3DIC Compiler
- **Insertion point**: the natural home for the hybrid-bonding floorplan `gen_def.py` already generates.
- **Emit**: per-die DEF set (§2.2), stack definition from §2.8, hybrid-bond interface with 5 µm pitch, TSV arrays, plus inter-die connectivity as a stack-level netlist.
- **Effort**: 5 days. Highest effort in this phase, and the strongest single claim in the repo if it lands — a 3D floorplan a production 3D-IC tool will open.

### 4.5 PrimeSim Continuum — mixed-signal path
- **Insertion point**: mixed-signal co-simulation of `modules/fabric/rtl/cxl_pbr_manager.sv` and `verification/tb/tb_top.sv` against the analog link.
- **Emit**: Continuum configuration binding the SV testbench to the §4.1 analog netlist, with the digital/analog boundary and connect modules declared.
- **Effort**: 4 days. Schedule after §4.1 and §4.4.

---

## 5. Phase 3 — Siemens EDA

**Tooling decision, recorded deliberately.** Resume/CV positioning keeps Mentor at legacy DRC/LVS — that stands and this spec does not change it. The repo is a separate question: a project that targets 3D-IC seriously and omits Siemens has a real technical gap, because Calibre 3DSTACK is the industry-standard multi-die assembly verification point. These two decisions are independent and both are intentional.

### 5.1 Calibre 3DSTACK — *the gap-closer*
- **Insertion point**: multi-die assembly verification and stack-level LVS — the check that the 3D stack is actually connected the way the architecture claims.
- **Emit**: per-die GDS/OASIS (§2.3) + per-die source netlists, a 3DSTACK assembly description (die placement, rotation, z-order, bond interface), and the connectivity expectations for hybrid bonds and TSVs.
- **Why it matters**: 3DIC-X asserts 4.2 TB/s vertical bandwidth over a 5 µm hybrid-bond interface. 3DSTACK is where "the bonds land where we said" becomes checkable. Currently `gds_export.tcl` has `check_lvs` commented out — there is no LVS in this repo at all.
- **Effort**: 4 days. **Ranked above the entire Allegro/Integrity item and above PrimeWave** on effort-to-credibility.

### 5.2 HyperLynx — SI / PI
- **Insertion point**: independent SI/PI check on the §2.6 channel and the §3.2 droop numbers; consumes Touchstone and IBIS-AMI directly, so Phase 0 nearly finishes this one.
- **Emit**: stackup + `.s4p`/`.s8p` + `.ibs`/`.ami`, plus a HyperLynx board/package geometry description.
- **Correlation target (T2)**: eye height/width vs. the `link_eye_margin_ui` column in `reports/pareto_data.csv` and the eye in `reports/3dic_x_final_eye.png`.
- **Effort**: 2 days — cheapest T1 in the document *if* Phase 0 is done, which is the argument for Phase 0 in one line.

### 5.3 Innovator3D IC — package co-design
- **Insertion point**: package/substrate co-design alongside the die stack.
- **Emit**: stack + substrate definition, die-to-package pin mapping from `reports/connectivity_pinout.md`.
- **Effort**: 3 days. Lowest priority of the three.

---

## 6. Blocking Prerequisites

These are fixes to existing code, not new hooks. Nothing in §3–§5 is credible until they are done.

| ID | Item | Status | Why it blocks |
| :--- | :--- | :--- | :--- |
| **P0-A** | Promote stackup from Markdown to machine-readable JSON. | **Partial** — `integrations/interchange/stackup.py` emits validated stackup JSON (units declared, unit-sanity checked) from the `DesignRecord`, but the *authored* source is still `configs/3dic_x_vector_deck.json` plus prose in `assembly_packaging_spec.md`. | Celsius, Sigrity, 3DSTACK, HyperLynx, 3DIC Compiler all need it machine-readable. |
| **P0-B** | Split geometry from serialization in `gen_def.py`. | **Partial** — the placement model now lives in `integrations/canonical.derive_macros` and DEF/GDS/Tcl-equivalent numbers come from it (tested against the 10 µm snap grid and the `SERDES_N_0` origin). `gen_def.py` has not yet been switched over to consume it, so two copies of the geometry still exist. | DEF and Tcl must come from one placement list or they will diverge. |
| **P0-C** | Rewrite `netlist_exporter.py` to build topology from `DesignRecord`. | **Superseded** — `integrations/interchange/spice_io.py` builds the deck from the record, drops the nonexistent `/pdk/3nm_GAA/models.sp` include, and is verified by running ngspice. `netlist_exporter.py` still exists unchanged and should be retired. | Blocks §3.4, §4.1, §4.3, §4.5. |
| **P0-D** | Extend `rc_extractor.py` to per-net extraction. | **Partial** — `canonical.build_nets` distributes the class-level R/C across the nets 3DIC-X models, which is enough for a conserving SPEF, but it is a distribution of an analytic class value, not a real per-net extraction. `*DESIGN_FLOW "ANALYTIC_SURROGATE"` says so in every file. | Blocks a defensible SPEF (§2.4) and the StarRC correlation (§4.2). |
| **P0-E** | Replace `gds_export.tcl` with a real writer. | **Done** — `integrations/interchange/gds_io.py` writes real GDSII records (1 nm DBU, BOUNDARY/SREF/STRANS, excess-64 reals) and reads them back; `gds_export.tcl` is now dead code. | Blocked GDS (§2.3) and Calibre 3DSTACK (§5.1). |
| **P0-F** | Add `fidelity` provenance to every existing report generator. | **Partial** — every artifact emitted by `integrations/` carries the full provenance block (enforced by test), including a sidecar for GDSII. The pre-existing generators in `serdes_architect/scripts/` are untouched. | Required by §1.4 before anything leaves the repo. |

---

## 7. Execution Order

```
Week 1   Phase 0 §2.1–2.6, §2.8  + P0-A,B,D,E        -> T0 green, CI gate live
Week 2   §2.7 IBIS-AMI  + P0-C,F                     -> portable link model
Week 3   §3.1 Celsius, §3.2 Voltus-Fi                -> thermal + droop correlation
Week 4   §5.1 Calibre 3DSTACK, §5.2 HyperLynx        -> stack LVS + independent SI
Week 5   §4.1 PrimeSim, §4.2 StarRC                  -> the SPICE leg, retrain surrogate
Week 6   §4.4 3DIC Compiler, §3.3 Sigrity/EDB        -> 3D floorplan in a production tool
Later    §3.4, §3.5, §4.3, §4.5, §5.3
```

Rationale for the ordering: Phase 0 is the multiplier. Then take the cheapest T1/T2 wins that touch the repo's headline claims (thermal 98.5 °C, droop, vertical bandwidth, 224G eye) before the higher-effort platform integrations.

---

## 8. Definition of Done

**Phase 0 (no licenses required — must be fully achievable in CI):**
- [x] `python -m integrations.cli emit --target neutral:all` produces a complete `results/handoff/<run_id>/` tree with a manifest and SHA-256 per file.
- [x] `regression_suite/run_interchange_qualification.sh` is green: every format round-trips through an independent parser.
- [x] Every emitted file carries a §1.4 provenance header with an accurate `fidelity` field (enforced by `test_every_text_artifact_carries_provenance`).
- [x] Touchstone files pass passivity, causality, and reciprocity checks; port ordering is documented in-file.
- [x] No Liberty timing arc is emitted without a characterized source (enforced by `test_rejects_injected_timing`).
- [x] Units declared and validated in every geometry artifact; a mm/µm slip is rejected.
- [x] The emitted SPICE deck executes in a real simulator (ngspice) and cannot show passive gain.
- [ ] `.ibs` passes `ibischk7` with zero errors — **outstanding**: `ibischk7` is not installed here, so IBIS is structurally validated only.
- [ ] GDSII verified by KLayout or gdstk — **outstanding**: neither is installed; the stream is checked by this repo's own independent reader.
- [ ] IBIS-AMI `AMI_Init`/`AMI_GetWave` DLL built and returning a non-degenerate impulse response — **not started** (C work, budgeted separately in §2.7).

**Per vendor hook:**
- [ ] `emit()` runs with no vendor tool installed; `validate()` passes.
- [ ] A driver script is emitted that a licensed user runs unmodified.
- [ ] `tier` field reflects reality, and `README.md` uses the same word.
- [ ] Where §3–§5 names a correlation target, the error band is published in `reports/` — or the hook stays at T1 and says so.

---

## 9. What This Does Not Do

This spec adds **handoff**, not authority. Even at full implementation with all three vendor suites licensed and correlated:

- 3DIC-X does not perform foundry sign-off, and no artifact it emits is a sign-off deck.
- Surrogate predictions remain surrogate predictions. Correlation narrows the error band; it does not transfer sign-off authority.
- No 3DIC-X output may be used for tape-out or fabrication without independent validation in a certified flow.

The `README.md` disclaimer stands unchanged. Vendor hooks make the transition to certified flows *real and automated* — that is the whole claim, and it is a sufficient one.

---

## 10. Implementation Status (as built)

Phase 0 and the hook scaffolding for all three vendors are implemented and tested. Every claim below is T0: artifacts are emitted and independently parsed, with no vendor license involved.

```
integrations/
  base.py           VendorHook / HookResult / Finding, registry, provenance, manifests
  canonical.py      DesignRecord + loaders (golden_config.json, vector deck, reports)
  correlate.py      vendor-vs-surrogate error bands + calibration feedback
  cli.py            status | emit | ingest | correlate | roundtrip
  interchange/      stackup, def_io, lef_io, gds_io, spef_io, liberty_io,
                    touchstone_io, ibis_io, spice_io      (writer + reader each)
  vendors/          neutral (9 hooks), cadence (3), synopsys (3), siemens (2)
  importers/        vendor_results.py (thermal, IR, SPEF, Touchstone, DEF)
tests/integrations/ 79 tests, unittest, no external deps beyond numpy
```

**17 registered targets, all emitting clean:** `neutral:{stackup,lef,def,gds,spef,liberty,touchstone,ibis,spice}`, `cadence:{celsius,voltus_fi,sigrity_edb}`, `synopsys:{primesim,starrc,primewave}`, `siemens:{calibre_3dstack,hyperlynx}`.

### What the tests actually prove

| Claim | How it is verified |
| :--- | :--- |
| DEF round-trips exactly | 32 placements compared origin-by-origin; moved macro and changed DBU are both detected |
| GDSII is real GDSII | record walk reaches `ENDLIB` with even-length records; excess-64 real codec round-trips; bbox equals `DIEAREA`; SREF count equals placed macros |
| SPEF conserves | `sum(*RES)` and `sum(*CAP)` equal the net totals; a tampered segment is caught |
| Liberty fabricates nothing | zero timing groups; an injected `cell_rise` table fails the validator |
| Touchstone is physical | passivity (max singular value ≤ 1), reciprocity (‖S−Sᵀ‖ = 0), real positive DC, pre-cursor energy < 0.03% across 5 link configurations |
| Touchstone agrees with the surrogate | IL at Nyquist matches the `si_analyzer.py` budget for every material |
| The SPICE deck runs | ngspice completes; RX swing is positive and never exceeds TX; Twinax > Megtron-7 > FR4 in surviving swing |
| Power maps conserve power | every die's tiles sum to its declared wattage exactly |
| The di/dt profile is legal | max slope ≤ the declared 450 A/ns |
| The 3D stack is contiguous | z-extents chain from 0 to 875 µm with no gap; every interface references a real die |
| Correlation math is right | a 1.4 dB injected channel offset and a 1.15× parasitic offset are recovered exactly |
| Self-validation is impossible | our own artifacts and all fixtures are detected and downgraded to T0; calibration from them is refused |

### The return path

`python -m integrations.cli correlate --thermal <celsius.csv> --ir <voltus.csv> --spef <starrc.spef> --sparam <field_solved.s4p>` reads vendor exports, publishes the error band against the surrogate in `reports/correlation/`, and writes `configs/surrogate_calibration.json` for the physics side to consume.

The calibration file carries a `trustworthy` flag. It is false whenever any input was produced by this repo or by a test fixture, and `load_calibration()` returns nothing in that case — so a surrogate can never be "corrected" by its own output. Only a genuine third-party vendor file earns T2 and moves a prediction.

### Still outstanding

* **Licensed tiers (T1/T2).** Every vendor hook emits and self-checks, but none has been loaded by its tool. The driver scripts are written to be run unmodified by a licensee.
* **External parsers.** `ibischk7`, KLayout/gdstk and OpenROAD are not installed here; IBIS and GDSII are validated structurally by this repo's own readers. Installing them is cheap and would harden the T0 claim.
* **IBIS-AMI DLL.** `.ibs` and `.ami` are emitted with `GetWave_Exists = False`, which is the honest declaration while no shared library ships.
* **Sigrity/EDB.** EDB is a database, so `build_edb.py` scripts against PyEDB rather than emitting a file; it needs a Cadence install to do anything.
* **Legacy exporters.** `netlist_exporter.py`, `gds_export.tcl` and `gen_def.py` still hold duplicate or dead logic (see P0-B/C/E). Retiring them is follow-up work, not new capability.

