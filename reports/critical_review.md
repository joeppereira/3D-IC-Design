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
  the analytic front, beating random sampling at equal budget (hypervolume 0.930 vs
  0.908, front size 48 vs 24 — the margin narrowed once the surrogate stopped being
  systematically biased, which is itself informative).

The POD/ROM claim has since been closed too (§5 item 4: a POD-Galerkin ROM with
measured truncation error, replacing a document that quoted a 1.9M× speedup against a
tool nobody had run). Any *vendor* correlation remains not implemented, and is
described that way.

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

## 5. Open issues — the resume point

Ordered by effort-to-credibility. This section is the authoritative to-do list; it
is kept current so no context is carried in anyone's head.

**Last worked: 2026-09-23.** Items 1–5, 10 and 15 are closed; items 11–14 and
16 are open, and item 12 (ROI submodeling) is the one the others most depend on.

### Closed

1. ~~**Externally validate the remaining formats.**~~ ✅ **Closed for DEF, LEF and
   Liberty.** `klayout` reads the DEF/LEF and `liberty-parser` (a lark grammar,
   not regexes) reads the `.lib`; both are asserted in
   `tests/integrations/test_external_parsers.py`. Dependencies are pinned in
   `requirements.txt`.

   Bringing in a third parser found **two real defects**, both invisible to the
   round-trip tests because those compare numbers and these are geometry:

   * **Two macros physically overlapped.** The N/S SERDES rows and the E/W UCIe
     columns both started at a 1000 µm offset, so `SERDES_S_0` (1000–1600 ×
     500–1400 µm) and `UCIE_W_0` (500–1100 × 1000–1900 µm) intersected over
     100 × 400 µm. DEF places the lower-left of the bounding box *after* ORIENT
     is applied, so a 900 × 600 PHY placed `E` occupies 600 × 900 — reasoning
     about the unrotated size is how it was missed. `canonical.derive_macros`
     now clears the corner and raises if a placement cannot fit.
   * **Two RoT guard-bands, 7 mm apart.** `def_io` put the 250 µm EM shield at
     the die centre; `gen_def.py` placed the Caliptra RoT at (w/2, 2000 µm).
     `canonical.rot_origin_um` now owns it and both consume it. `gen_def.py`
     also consumes `derive_macros`, which closes the P0-B duplication.

   *Still open:* **SPEF** (no independent Python reader exists on PyPI; needs
   OpenROAD or PrimeTime) and **IBIS** (`ibischk7` is not a direct download —
   the IBIS Open Forum gates it behind licence acceptance, so it is an owner
   action). See item 9.

2. ~~**`transient_solver.py` still carries the magic constants.**~~ ✅ **Closed.**
   Rewritten as `TransientThermalSolver(ThermalSolver)` on the finite-volume
   energy equation `C dT/dt = Σ g ΔT + P`, sharing the steady-state solver's
   verified conductances. `PHYSICAL_SCALE = 500`, the bare `* 2000.0` source
   multiplier and `diffusivity = 0.01` are gone; the explicit stability limit is
   **computed** (1.61 µs) and sub-stepped automatically. Volumetric heat
   capacity raises on a missing material rather than defaulting, the same rule
   as the `k_map`. Verified three ways: exact matrix exponential of the same ODE
   system (**4.3e-5 °C**), `solver.py`'s converged field as a fixed point
   (**8.5e-6** relative), energy closure (**2.9e-6**). `solver_snippet.py`
   deleted.

   *Worth knowing:* a single lumped exponential is the **wrong** reference for
   this stack — it has modes from 1.5 µs to 259 ms, so the first version of that
   check failed for the wrong reason.

3. ~~**Quote the measured peak temperature.**~~ ✅ **Closed.** **83.87 °C**
   (grid-converged, GCI 0.081%) replaces the 98.5 °C literal in
   `final_design_audit.json`, `final_architectural_solution.md`,
   `design_evolution_story.md`, `README.md`, the spec, the Cadence hook, the web
   dashboard and the legacy exporters. `canonical.py` now **raises** if the
   operating point is not a solver output instead of defaulting — that value
   sets Liberty's `nom_temperature` and the SPICE `.temp` line. The unmeasured
   *"6.5 °C headroom from shattered macros"* is replaced by a measured comparison
   against an exhaustive scan of monolithic placements — **37.02 °C** as it now
   stands, after the scan was widened to move the memory macro too (it had been
   pinned at the die centre while the shattered side optimised it, worth ~4 °C of
   the 41.45 °C first reported here). The
   synthetic Celsius fixture was shifted by −14.6255 °C with the shift recorded
   in its header. `transient_roi_solver.py` was deleted: unreferenced, and it
   returned a fabricated `peak_tj` alongside a "100,000×" speedup.

4. ~~**POD / reduced-order model.**~~ ✅ **Closed.**
   `physics_accelerated/src/thermal_rom.py` — a POD-**Galerkin** ROM, not a
   regression: snapshots from the reference solver, SVD, then the *same
   operator* projected as `(Uᵣᵀ A Uᵣ) a = Uᵣᵀ b`. Measured on 32 held-out
   parameters at 10,240 unknowns: worst held-out peak-Tj error **1.43 °C** at
   rank 240, with the ROM sitting just above the projection floor at every rank
   (so the basis, not the projection, is the limit). Reported as truncation
   error; the timing ratio is labelled as internal. See
   `reports/rom_pinn_validation.md` §4 and `reports/thermal_rom_validation.json`.

   *The finding worth carrying forward:* **retained energy is not accuracy.** At
   rank 32 the basis holds 99.974% of the snapshot energy while the held-out
   peak temperature is still **8.71 °C** wrong. Convergence is slow because a
   *translating* localised source has a slow Kolmogorov n-width — a property of
   the problem, not a defect.

5. ~~**A surrogate trust guard.**~~ ✅ **Closed.**
   `physics_accelerated/src/trust_guard.py`, run automatically at the end of
   every search. The front is no longer published with temperatures the
   surrogate predicted: all 48 members are re-solved on the reference solver
   (**2.0 ms each** — the operator is parameter-independent, so one
   factorisation serves every design), the three worth quoting are re-solved
   again on a 64×64×20 mesh, and each front entry carries
   `reference_peak_tj_c`, `surrogate_error_k` and `in_training_distribution`.
   A test re-derives a published temperature from its own genome, so the
   artifact cannot drift back to predictions.

   *The finding worth carrying forward:* **the whole search space is outside
   the surrogate's training distribution.** Not the extremes of it — all of
   it. `data_gen.py` trained on random r=3 discs and *single hot cells* on the
   memory die; the optimiser places 2×2 blocks and a solid 4×4 memory macro.
   Mahalanobis distance on shape features: training p99 **4.7**, every front
   member **36.4–71.8**, with `memory_active_fraction` at **+24.6 σ**. The
   +8…+40 K error band was never bad luck at the extremes of a well-sampled
   space.

   Splitting the error says which fix applies: **+14.21 K** mean network
   extrapolation, **+2.76 K** training-mesh discretisation, 0.00003 K solver
   disagreement, closing on the +16.98 K total to **0.0 K**. The same network
   error measured in-distribution is **2.10 K** — 6.8× better than where the
   optimiser looks. The ranking survives across the whole front (Kendall
   τ **0.986**, selection regret **0.00 °C**), which is the first time that
   claim rested on more than three sampled designs.

   *And the plan that did not survive measurement:* re-ranking on the POD ROM
   from item 4 does not pay at this mesh. A ROM accurate to 1 °C over block
   layouts needs ~300 snapshots — 300 exact solves of offline cost — and then
   runs at 1.45 ms against a 1.89 ms exact back-substitution. The cause is the
   prefactorisation, not the ROM; at a mesh where factorisation is
   unaffordable the same basis wins by 40×. `--calibrate-screen` keeps the
   measurement reproducible instead of the conclusion asserted.

10. ~~**Retrain the surrogate on the distribution the optimiser searches.**~~
    ✅ **Closed.** `physics_accelerated/src/dataset.py` draws macro layouts as a
    deliberate *superset* of the search's parameterisation (1–8 sub-macros of
    2–4 cells, memory macro 3–5, logic fraction 0.50–0.90, 40–80 W, against the
    search's fixed 4×2×2 / 4 / 0.75 / 60 W), mixed half-and-half with the old
    hotspot distribution so nothing is traded away, and labels every map with
    the reference solver's **direct solve** instead of a relaxation — 3,800
    labelled maps in under a second of solver time, labels satisfying the
    discrete heat equation to **3.6e-6 K**. Measured held out
    (`reports/surrogate_retraining.md`):

    | Held out | Legacy | Retrained |
    | :--- | ---: | ---: |
    | field RMSE, `layouts` | 6.744 K | **0.721 K** |
    | field RMSE, `hotspots` (the old distribution) | 2.231 K | **0.347 K** |
    | network error at optimiser-selected designs | 18.31 K | **1.33 K** |
    | worst single design | 34.67 K | **3.41 K** |
    | designs outside the training distribution | 100% | **0%** |

    (both models asked about the same designs — the published front. At the
    front each model actually led its own optimiser to, the same comparison
    reads 14.21 K → 1.33 K.)

    *Three findings worth carrying forward.* First: **every surrogate RMSE this
    project published before this change was an in-sample number** — `train.py`
    trained on all its data and reported error on the same data. It now takes a
    train/val/test split, takes normalisation statistics from the training split
    only, and reports every split so the gap is visible. Second: the retrained
    model is also **6.4× better on the distribution it replaced**, so this was
    never a trade. Third: the λ sweep that reported "−22% field RMSE" was
    in-sample and single-seed; re-measured held out with three seeds per
    setting, the physics term's accuracy benefit is **3.2%, inside the seed
    spread**, while its residual benefit is **−50% and ten standard deviations
    clear**. It is kept for the latter, and the −22% is labelled as belonging to
    the data-starved regime.

    *What it did not fix:* the +2.76 K training-mesh discretisation term, which
    is not a network property — the trust guard's re-solve still owns it, and
    published temperatures are still solver output.

### Next up

11. **Move the surrogate onto the converged mesh.** With extrapolation down to
    ~1.4 K, the largest remaining term between a surrogate prediction and a
    defensible temperature is the **16×16×5 mesh itself**: +2.76 K mean and
    +10.02 K worst against 32×32×10 at optimiser-selected designs. Labels on the
    finer mesh now cost almost nothing (`dataset.py` labels 3,800 maps in under
    a second; the finer mesh is ~2 ms per solve), so the work is regenerating at
    32×32×10, widening the FNO's input, and re-measuring. The success criterion
    is the trust guard's own error budget: the discretisation row should
    collapse to the 0.18 K that separates 32×32×10 from 64×64×20.

12. **ROI submodeling in the reference solver.** The largest remaining error is
    the mesh, and a globally fine mesh is the wrong way to fix it: solve
    globally coarse, then re-solve a hotspot region at ~20 um with boundary
    conditions interpolated from the coarse field, so cost scales with the ROI
    rather than the die. Two checks make it honest — refine until the ROI peak
    stops moving, and close the flux balance across the coarse/fine interface.
    `transient_roi_solver.py` was deleted from this repo for reporting a
    fabricated peak beside a "100,000x" speedup; the concept was never the
    problem, the missing interface check was. See
    `reports/fidelity_integration.md` §4.

13. **A timing/eye return channel, and rank churn on the result.**
    `integrations/correlate.py` has four channels (thermal, IR drop,
    parasitics, insertion loss) and none for post-layout slack or a statistical
    eye. Adding `setup_slack_ps` and `eye_width_ui` follows the same shape --
    roughly a day each plus an importer. The half that matters more: nothing
    currently turns a correlation into a *changed decision*. Re-running the
    ranking with the corrected model and reporting the churn is the only output
    that justifies a licence hour.

14. **Parameter calibration instead of output bias.** `correlate.thermal` fits
    `thermal_bias_c`, an additive offset, which §5 item 5 and
    `reports/rank_churn.json` show cannot reorder anything. Fitting `h_eff` and
    `k_lateral` -- both already real knobs on `ThermalReference` -- would make a
    vendor run capable of changing a decision rather than only a number.

15. ~~**Thermal-gradient skew.**~~ ✅ **Closed.**
    `physics_accelerated/src/gradient_skew.py`, measured in
    `reports/gradient_skew.md`. On a 64-sink H-tree balanced by construction —
    so every picosecond it reports is thermal, and a flat field gives exactly
    zero — the published front's designs carry **10.9 to 78.3 ps** of skew, and
    **10.9 to 28.1 ps** among the 23 that clear a 105 °C limit. Against the
    ~25 ps a 2 GHz clock tree built to 5% of period has to spend, **the thermal
    gradient alone exhausts the skew budget on the worst feasible design**,
    before routing imbalance.

    *The finding worth carrying forward:* peak Tj and skew are **not the same
    objective**. Kendall τ between them across the front is **+0.722** — the
    coolest design (#0) is not the flattest (#4), and choosing the coolest costs
    +2.54 ps of skew while choosing the flattest costs +2.29 °C. This is the
    first quantity found where the existing Pareto front is *not* optimal, and
    it is free to evaluate: the field is already solved.

    *And a mistake worth recording:* the first version compared die-spanning
    tree skew against the 224G link's 1.65 ps jitter budget and reported
    "4745% of budget". Nobody distributes a 56 GHz clock over 18 mm. On-die skew
    competes for the clock period; the link budget is a different budget, and
    the dramatic-looking number was a category error rather than a finding.

### Next up

16. **Skew as a third search objective.** Item 15 showed the front is not
    optimal for a quantity it already computes, and NSGA-II is indifferent to
    how many objectives it carries. The work is one evaluator change plus a
    decision about whether skew belongs in the objective vector or as a
    constraint (a CTS budget is a limit, not something to minimise without
    bound). Worth pairing with item 12: a sharper field can only raise skew, so
    the trade may move.

### Decisions only the owner can make

6. **A 1 TB CXL memory module whose die hierarchy contains no memory die.**
   `assembly_packaging_spec.md` documents a 30 µm DRAM stack; `golden_config.json`
   has three dies, none of them DRAM. Either the spec or the hierarchy is wrong.
   This is the single remaining cross-consistency error and it is left failing
   deliberately.
7. **`.git` is 222 MB.** Untracking `node_modules` stopped the growth; shrinking
   history needs a rewrite, which breaks existing clones.
8. **Legacy duplicates.** `netlist_exporter.py` and `gds_export.tcl` are
   superseded by `integrations/` (spec P0-C/P0-E). `gen_def.py` no longer
   duplicates the placement geometry — it consumes `canonical.derive_macros`
   (item 1) — but the file is still a second serializer and retiring it is
   cleanup, not new capability.

### Blocked on licences or downloads

9. **T1/T2 vendor validation.** Every hook emits and self-checks; no Cadence,
   Synopsys or Siemens tool has opened an artifact. The driver scripts are
   written to be run unmodified by a licensee. This also covers the two
   remaining external validators from item 1: SPEF needs OpenROAD or PrimeTime,
   and IBIS needs `ibischk7`, whose download requires accepting the IBIS Open
   Forum licence.

### How to resume

```bash
pip install -r requirements.txt                     # validators included
./regression_suite/run_physics_verification.sh      # solver, transient, ROM, PINO, NSGA-II, trust guard
./regression_suite/run_interchange_qualification.sh # formats + cross-consistency
python -m unittest discover -s tests -t .           # 213 tests
```

Read `reports/fidelity_integration.md` first if the question is how this fits
next to a sign-off flow — it is the design record behind items 12–15. Then
`reports/rom_pinn_validation.md` (physics, measured — §4 is the POD ROM),
`reports/multiobjective_search.md` (search, the surrogate error band, and §6 the
trust guard), `reports/surrogate_retraining.md` (the training distribution and
the first held-out numbers), and `reports/eda_vendor_integration_spec.md` §10
(integration status).

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
**optimiser-selected** designs was +8.45 / +11.45 / +40.17 K against an
in-sample RMSE of 2.03 K, always over-predicting — because every design the
optimiser could express was outside its training distribution (item 5). After
retraining on that distribution (item 10) the same three positions on the front
read **−0.96 / +1.58 / +0.10 K**, and the search, no longer misled, finds a
coolest design at **72.07 °C** on the reference against **77.61 °C** before.
Absolute temperatures are still re-solved on the reference by the trust guard
rather than taken from the network.

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
  the number that governs whether its output can be quoted — split into network
  extrapolation, solver disagreement and mesh discretisation, the three closing on the
  total to 0.0 K.
* A surrogate trained on the distribution its optimiser searches, with **held-out**
  numbers: 0.58 K field RMSE, 1.36 K at optimiser-selected designs, and 0.35 K on the
  distribution it replaced — measured by a benchmark that fails if retraining did not
  help, if the old distribution was lost, or if the search space is still uncovered.
* A trust guard that re-solves every published design on the reference solver and flags
  designs outside the surrogate's training distribution, with the flag calibrated
  against an in-distribution control rather than asserted.
* A transient solver verified against the exact matrix exponential of the system it
  integrates, against the steady-state solver's field as a fixed point, and by closing
  its own energy budget.
* A POD-Galerkin reduced-order model with measured truncation error on held-out
  snapshots — including the measurement that its "99.974% retained energy" corresponds
  to an 8.71 °C peak-temperature error, which is why energy fractions are not quoted
  here as accuracy.
* DEF, LEF and Liberty read back by independently-written parsers (KLayout,
  liberty-parser), which found two placement defects that number-comparing round-trip
  tests could not see.

**Cannot claim yet** — and each has a specific blocker:

| Claim | Blocker |
| :--- | :--- |
| ~~Pareto / multi-objective search~~ | ✅ **Closed** — NSGA-II, verified on ZDT1. |
| ~~Physics-informed training~~ | ✅ **Closed** — heat-equation residual in the loss (PINO). |
| ~~A defensible peak-Tj number~~ | ✅ **Closed** — 83.87 °C, grid-converged, GCI 0.081%. |
| ~~Reduced-order model (POD)~~ | ✅ **Closed** — POD-Galerkin, 1.43 °C worst held-out peak error. |
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
