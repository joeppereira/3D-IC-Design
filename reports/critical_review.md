# 🔍 Critical Review: 3DIC-X, from a New Reader's Perspective
**Audited**: 2026-09-20 · **Commit at audit**: `429fd482`
**Method**: read the reader-facing documents first, then checked whether the code underneath supports them.

This is an adversarial review, written the way a technically literate stranger would
read the repo — someone who will `grep` for the thing a document claims. It records
what was found, what has since been fixed, and what remains open.

---

## 1. Summary

The engineering instincts are sound where the code is real. The problem at the time of
audit was that the prose ran roughly three versions ahead of the implementation, and a
reader who checked would find that out quickly.

| Area | Verdict |
| :--- | :--- |
| Interchange / EDA handoff (`integrations/`) | **Strong.** Externally validated, 121 tests |
| Thermal solver, FNO surrogate, floorplan geometry | **Real but modest.** Sound, small, undersold by comparison to the claims |
| ROM / PINN / FEA-correlation claims | **Not implemented.** Presented as measured results |
| "Multi-objective Pareto search" | **Misnamed.** Single-objective random sampling |
| Repository hygiene | **Was poor.** 98.5% of tracked files were vendored dependencies |
| Internal numerical consistency | **Was broken.** Four values for peak Tj, three for eye margin |

---

## 2. What a new reader hits, in order of severity

### 2.1 The headline claims were not in the code

This is the finding that would end a technical conversation.

**`rom_pinn_validation.md`** presented a validation table against *"Ansys Icepak
(High-Fidelity Baseline)"*: 104.2 °C vs 102.8 °C, 8 hours → 15 ms, **"1.9M × speedup"**.
Searching the repository for what would have to exist:

* No Icepak dataset. `external_references/` is empty.
* No POD, no SVD, no modal decomposition anywhere in `physics_accelerated/` or
  `serdes_architect/`.
* No physics-informed loss. `physics_accelerated/src/train.py` uses plain MSE with an
  optional hotspot weighting map — there is no residual term and no `λ`, so the
  document's `L = L_data + λ·L_physics` does not exist.

The FNO is trained against **this repo's own 16×16×5 Jacobi finite-difference solver**.
Any accuracy or speedup figure from that comparison is internal and says nothing about
agreement with a commercial tool.

**"Multi-objective GEPA search for Area vs. Power vs. Thermal"** (README) is
`physics_accelerated/src/gepa.py`: 50 random macro placements per generation, ranked by
`preds[i].max()` — peak temperature alone. There is no dominance test, no Pareto front,
no crossover, no mutation, no selection. The ten "generations" are ten independent
random batches.

*Status: largely built.* Both gaps have since been closed with measured results
(`reports/rom_pinn_validation.md`, `reports/multiobjective_search.md`):

* A grid-converged **reference solver** now exists, verified to **1.04e-9 °C** against
  analytic 1D conduction and **8.4e-12** on global energy balance, giving the project's
  first defensible peak-Tj number: **83.87 °C** (GCI 0.081%).
* The **physics residual** is implemented, making this a physics-informed neural
  *operator* (PINO). At λ = 0.1 it cuts field RMSE 22% (2.604 → 2.031 K) and the PDE
  residual 59% (0.343 → 0.140 K) against the data-only baseline.
* **NSGA-II** replaces the random search, verified on ZDT1 to 0.0037 mean distance from
  the analytic front, beating random sampling at equal budget (hypervolume 0.951 vs
  0.881, front size 48 vs 20).

POD/ROM and any *vendor* correlation remain not implemented, and are still described
that way.

### 2.2 The same quantity had four different values

At audit, peak junction temperature appeared as **98.5 °C** (README, technical audit),
**102.8 °C** (ROM document), **104.2 °C** (its "Icepak" reference) and **112 °C**
(legacy comparison) — while the flow's own output, `golden_config.json →
floorplan.estimated_max_temp`, said **25.03 °C**, i.e. ambient.

Eye margin appeared as **0.52 UI** (technical audit), **0.934 UI** (`pareto_data.csv`)
and **0.0 UI with status ❌ FAIL** (`golden_config.json → si_analysis_v3`) — behind a
README and a `3dic_x_final_eye.png` presenting the 224G link as proven.

A reader who opens the JSON before the Markdown reaches the opposite conclusion from
the one the documents assert.

*Status: partly fixed.* The SI verdict is now a genuine PASS (§3), and the unsupported
audit figures were corrected. The thermal numbers still need one authoritative source.

### 2.3 The regression suite compared nothing

`regression_suite/run_v1_qualification.sh` read:

```python
res = current.get('si_verification', {})
eye = res.get('eye_width_ui', 0)
```

`si_verification` has never been a key in `golden_config.json` — the key is
`si_analysis_v3`. So `res` was always `{}`, `eye` was always the `0` default, and the
qualification gate had been evaluating a constant rather than the design.

*Status: fixed.* The correct key is used, and a missing key is now a hard error rather
than a silent default, so this class of failure cannot recur quietly.

### 2.4 98.5% of the repository was vendored dependencies

**26,670 of 27,067 tracked files** were `web/node_modules`, including two 82,000-line
three.js builds. `.git` is 222 MB. A reader clones 222 MB to reach roughly 7,000 lines
of actual work, and GitHub's language statistics describe the dependencies rather than
the project.

Contributing to this: `.gitignore` was a single line containing literal `\n` escape
sequences, so it matched nothing. `.venv` was excluded only because the virtualenv tool
writes its own `.gitignore`.

*Status: fixed forward.* `node_modules` is untracked and `.gitignore` repaired.
Shrinking `.git` itself requires a history rewrite, which breaks existing clones and is
therefore left as an explicit decision rather than done unilaterally.

### 2.5 There were no tests

Zero. The only executable checks were shell scripts that ran the flow and printed
results, one of which (§2.3) was comparing a constant.

*Status: fixed.* 121 tests, plus two independent gates — see §4.

---

## 3. The modeling error underneath the failing link

One error had a long blast radius, and it is worth recording in full because it
explains several of the symptoms above.

`serdes_architect/src/layout/rc_extractor.py` applied **on-die Metal-7 geometry**
(0.2 µm × 0.4 µm cross-section) across the full `reach_mm` of **300 mm**:

```
R = ρ·L/A = 3.0e-8 × 0.3 / (0.2e-6 × 0.4e-6) = 112,500 Ω
```

That is **47 Ω/mm**, where a controlled-impedance link is 0.1–1 Ω/mm — two orders of
magnitude out. It is on-die wiring geometry applied to an off-die channel.

`si_analyzer_v3.py` then fed that resistance into a **DC voltage divider** and called
the result insertion loss:

```
20·log10(100 / (100 + 112500)) = 61.03 dB   + 6 dB package tax = 67.03 dB
```

which matches the stored `si_analysis_v3.loss` exactly. With 67 dB of "loss", the SNR
margin went to −28.98 dB and the eye closed to 0.0 UI. **The failing link was an
artifact of the units error, not a physical result.**

Meanwhile the material tables give 0.44 dB/inch for the twinax flyover — 5.20 dB over
300 mm. The repository was carrying two insertion-loss models **61.8 dB apart**.

*Status: fixed.*

* Two-scale extraction: on-die thick-metal escape (22.5 Ω over 1500 µm) separated from
  the off-die channel conductor (0.79 Ω over 300 mm, **0.003 Ω/mm**), with a
  plausibility guard that rejects the original error class outright.
* Insertion loss now comes from the channel material, with the escape entering as the
  series resistance it actually is, and the result carries an auditable
  `loss_breakdown_db`.
* The eye reopens: **FAIL / 0.0 UI → PASS / 0.70 UI**, budget 12.96 dB = 5.20 channel
  + 1.76 escape + 6.0 package/connector.
* The two models now agree to **0.000 dB** (5.197 vs 5.197).
* Related: Nyquist was computed as bitrate/2 — 112 GHz for a 224G PAM4 link. It is half
  the *symbol* rate: 112 GBd → **56 GHz**.
* Related: `Megtron7` and `Megtron_7` were different keys in different modules, and
  `Flyover` — the material the golden config actually names — was in neither table, so
  both analysers silently fell back to a default dielectric. There is now one table
  (`serdes_architect/src/materials.py`), and an unknown material raises.

---

## 4. What "tested" is allowed to mean here

A round-trip test proves our writer and our reader agree. If both share a misreading of
the format specification, they agree and are both wrong. That distinction is now
enforced rather than assumed:

| Format | Independent validator | Status |
| :--- | :--- | :--- |
| GDSII | `gdstk` | ✅ units, hierarchy, bounding box, all 32 SREF origins, TSV/bond/keep-out layers |
| Touchstone | `scikit-rf` | ✅ parses identically (max ΔS < 1e-9); agrees passive and reciprocal |
| SPICE | `ngspice` | ✅ deck simulates; RX swing positive and never exceeding TX |
| DEF, LEF, SPEF, Liberty | OpenROAD / PrimeTime | ❌ **not installed — self-validated only** |
| IBIS | `ibischk7` | ❌ **not installed — structural checks only** |

`tests/integrations/test_external_parsers.py` asserts that coverage list, so removing a
validator fails a test instead of quietly weakening the claim.

**Bringing in a real parser immediately found a real defect.** The passivity check was
`σ_max(S) ≤ 1 + ε`; scikit-rf rejected the network anyway. Clamping reflection to
exactly `1 − |t|` produced `|ρ| + |t| = 1.000000000000` below ~1 GHz — a *lossless*
channel whose dissipation matrix `I − Sᴴ·S` is singular (minimum eigenvalue 4.8e-17).
Mathematically passive, physically wrong, numerically fragile. The check is now the
minimum eigenvalue of the dissipation matrix, which is stricter than both the old test
and scikit-rf's own element-wise one.

Two further bugs surfaced the same way: the SPEF writer's per-segment rounding left a
1e-6 Ω residual against its own header — invisible while resistances were 14 kΩ,
exposed the moment they became realistic — and the cross-consistency verifier was
comparing a full link budget against a channel-only S-parameter.

---

## 5. Open issues

1. **A 1 TB CXL memory module with no memory die.** `assembly_packaging_spec.md`
   documents four layers including a 30 µm DRAM stack; `golden_config.json` has three
   dies, none of them DRAM. Either the spec or the die hierarchy is wrong. This is a
   design decision, not a code fix, so the cross-consistency gate is left failing on it
   rather than having it papered over.
2. **One authoritative thermal number.** Now available — **83.87 °C** grid-converged
   from the reference solver — but the older 98.5 °C literal still appears in
   `final_design_audit.json` and downstream reports, which should quote the measured
   value instead of restating the literal.
3. **`.git` is 222 MB.** Untracking `node_modules` stops the growth but does not shrink
   history. A rewrite would, at the cost of breaking existing clones.
4. **Legacy duplicates.** `netlist_exporter.py`, `gds_export.tcl` and `gen_def.py` hold
   logic now superseded by `integrations/` (spec §6, P0-B/C/E). Retiring them is
   cleanup, not new capability.
5. **No vendor tool has loaded anything.** Every integration claim is T0. T1/T2 need
   licences; the driver scripts are written to be run unmodified by a licensee.

---

## 6. What this project can defensibly claim today

Two further defects were found while building the physics verification, both of the
same family as the original units error:

* `Hybrid_Bond` was missing from `k_map`, so the 5 µm Cu-Cu bond was modelled at the
  fall-through default of **1.0 W/mK** instead of ~300 — a near-insulator in the most
  important path of a 3D stack. Correcting it lowered peak Tj by **6.02 °C**, which is
  the same magnitude as the project's claimed "6.5 °C headroom from shattered macros";
  that claim cannot be separated from modelling error without a controlled comparison.
  The solver now raises rather than defaulting.
* `data_gen.py` capped the label solve at 200 iterations — about 4% of the way to
  convergence on the corrected solver. Labels peaked at **36.28 °C** where the converged
  answer is **57.11 °C**, so the network trained on fields 21 °C too cold.

And one that matters for how the results are used: the surrogate's error at
**optimiser-selected** designs is +8.45 / +11.45 / +40.17 K against a
training-distribution RMSE of 2.03 K, always over-predicting. The Pareto front is
sound for *ranking*; absolute temperatures must be re-solved on the reference.

**Can claim** — each is falsifiable by cloning and running:

* A vendor-neutral EDA interchange layer (DEF/LEF, GDSII, SPEF, Liberty, Touchstone,
  IBIS-AMI, SPICE) with emitters for Cadence, Synopsys and Siemens flows, validated
  against independently-written parsers and a real circuit simulator.
* A cross-consistency gate that compares emitted decks against the design flow's own
  outputs, which found six defects on first run.
* A thermal reference solver verified against analytic conduction and grid convergence,
  a finite-difference solver that agrees with it to 0.0036 °C, a physics-informed neural
  operator that improves both field RMSE and PDE residual over a data-only baseline, and
  NSGA-II verified against a problem with a known analytic front.
* A measured error band for the surrogate at the designs an optimiser selects — which is
  the number that governs whether its output can be quoted.

**Cannot claim yet** — and each has a specific blocker:

| Claim | Blocker |
| :--- | :--- |
| ~~Pareto / multi-objective search~~ | ✅ **Closed** — NSGA-II, verified on ZDT1. |
| ~~Physics-informed training~~ | ✅ **Closed** — heat-equation residual in the loss (PINO). |
| ~~A defensible peak-Tj number~~ | ✅ **Closed** — 83.87 °C, grid-converged, GCI 0.081%. |
| Reduced-order model (POD) | Not implemented. The reference solver makes it possible; the modal projection does not exist. |
| *Vendor*-correlated accuracy ("Ansys-correlated") | No licensed tool has run. The correct phrase is "grid-converged finite-element reference". |
| Any speedup figure | Only internal ratios exist — this mesh, this hardware, this repo's own solver. |
| "Validated in Cadence / Synopsys / Siemens" | No vendor tool has opened an artifact. |

The gap between these two lists is the honest measure of the project's current depth.
Closing any row of the second table is a well-defined piece of work, which is the
useful thing about stating it plainly.

---

## 7. Related

* [`reports/eda_vendor_integration_spec.md`](eda_vendor_integration_spec.md) §10 — implementation status, external-validator coverage, and the fixed/remaining defect tables.
* `python -m integrations.cli verify` — the cross-consistency gate.
* `./regression_suite/run_interchange_qualification.sh` — both gates in one run.
