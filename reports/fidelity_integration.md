# 🪜 Fidelity Integration: Where This Sits Next to Sign-off Tooling

**Written**: 2026-09-22 · **Status**: design record, not an implementation
**Companion to**: [`critical_review.md`](critical_review.md) §5 (the authoritative to-do list)

This document records an architecture discussion rather than a measurement: how
this explorer should couple to accurate simulation — Ansys/Cadence/Siemens field
solvers, sign-off extraction, SPICE-level electrical analysis — and what that
coupling can and cannot buy. Everything measured is cited to the report that
measured it; everything projected is labelled as such.

It exists because the question "how does this compare to a real flow?" has a
short wrong answer ("it's 10⁴× faster") and a longer right one.

---

## 1. What already exists, and where it is written down

| Capability | Report |
| :--- | :--- |
| Reference solver, verified analytically and by grid convergence | [`rom_pinn_validation.md`](rom_pinn_validation.md) §1 |
| PINO surrogate, POD ROM | same, §3–§4 |
| NSGA-II search | [`multiobjective_search.md`](multiobjective_search.md) §1–§4 |
| Trust guard: re-solve what the search selects, flag extrapolation | same, §6 |
| Rank churn: what a vendor correction could change | same, §6.7 · [`rank_churn.json`](rank_churn.json) |
| Surrogate retrained on the search distribution | [`surrogate_retraining.md`](surrogate_retraining.md) |
| Memory Tj as a decision variable, attach study | [`memory_attach.md`](memory_attach.md) |
| EDA interchange + return path, T0–T3 ladder | [`eda_vendor_integration_spec.md`](eda_vendor_integration_spec.md) §10 |

## 2. Exploration and sign-off answer different questions

| | This repo | Meshed vendor + extraction |
| :--- | :--- | :--- |
| Geometry | 5 layers, uniform k per layer plus rectangular regions | TSVs, µbumps, BEOL stack, lid, TIM, fluid volume |
| Finest cell | **562 µm** (32×32), 1.125 mm at the training mesh | 10–50 µm, locally refined |
| Cooling | lumped `h` (8000 / 50 W/m²K) | CFD-resolved flow; `h` is an *output* |
| Electro-thermal | none — power map is an input | leakage ↔ temperature iterated |
| Parasitics | two-scale analytic R, synthesised Touchstone | StarRC/QRC extraction; HFSS/SIwave EM |
| Timing | one Liberty `nom_temperature` | per-corner characterisation, SI-aware STA |

Measured costs here, and typical costs there (the second column is industry
experience, not measured in this repo):

| Step | This repo | Vendor equivalent |
| :--- | ---: | :--- |
| Surrogate evaluation | 0.1 ms | — |
| Reference solve, 32×32×10 | 2 ms | — |
| Refined solve, 64×64×20 | 65–130 ms | — |
| 3,888-candidate search + re-solve + confirm | **~3 min** | not attemptable |
| One steady-state thermal solve | 2 ms | minutes to an hour |
| Transient / electro-thermal | seconds | hours to overnight |
| Post-layout SPICE with SPEF | n/a | minutes–hours per block |

**The ratio on the loop is 10⁴–10⁶, and it is only meaningful because the two
are computing different things.** Every error figure this project publishes is
*numerical* — how well we solve the equations we wrote. Model-form error, how
well those equations describe the stack, is unmeasured: no licensed tool has
ever opened an artifact from this repo (T1/T2 gap, spec §10). My expectation is
tens of °C, driven by in-plane power resolution, BEOL/TSV lateral spreading, the
lumped convection coefficient, and the absent leakage loop. The sign is not
obvious — coarse power maps under-predict local peaks while ignoring lateral
spreading over-predicts them.

## 3. The fidelity ladder

| Level | What | Cost | Serves |
| :--- | :--- | :--- | :--- |
| 0 | Compact/analytic (Foster–Cauer RC, link budget) | µs | Pruning; the interface into SPICE |
| 1 | FNO/PINO surrogate | 0.1 ms | Inner loop, 10³–10⁵ evaluations |
| 2 | FV reference, prefactorised | 2 ms | Re-solve everything published; label L1 |
| 3 | Fine mesh / transient / coupled fixed point | 0.1–10 s | The final few; truth for L2's knobs |
| 4 | Meshed vendor + extraction | min–hours, licensed | Calibrate L2/L3 *parameters*; T1/T2 |

Rule that makes it a ladder rather than a list: **each level trains or calibrates
the one below, and nothing is published until the level above has seen that
specific artifact.** True today for L1↔L2 via the trust guard; the work is
extending it upward.

### What the L4 tools actually are

Two families are usually lumped together, and the difference decides how they
couple.

**Field solvers — they compute the field.**
*Icepak* (Ansys; Cadence Celsius, Siemens Flotherm equivalent) meshes the
assembly *and the fluid volume*, solving Navier–Stokes for the coolant coupled
to conduction in solids — typically 10⁵–10⁷ cells. It captures what we
structurally cannot: `h` as an output that varies 3–5× across a plate, TSV
arrays and µbumps below our cell size, radiation and flow maldistribution.
*HFSS* (Ansys; Cadence Clarity, Siemens HyperLynx Full-Wave) is a 3D full-wave
FEM solver, per frequency point with adaptive refinement, emitting Touchstone.
It captures via stubs and their resonances, return-path discontinuities,
connector launches, mode conversion and inter-channel crosstalk.

**Extraction — it reduces geometry to a circuit.**
*StarRC* (Synopsys; Cadence Quantus QRC) is model-order reduction from layout:
post-layout geometry plus a tech file → R and C per net, capacitance from
pattern-matched tables originally built by a field solver, plus neighbour
coupling. Output: SPEF. It captures routing topology, via stacks,
density-dependent thickness, conformal dielectrics — the class of thing whose
absence produced this repo's 47 Ω/mm defect.

All three end in a **compact model**: an effective `h` or a temperature field, an
RC network, a set of S-parameters. None belongs in an optimisation loop; they
are how the coefficients a fast model runs on get manufactured.

**Their real cost is inputs, not licences.** Icepak needs a 3D assembly and a
fluid domain; StarRC needs post-layout GDS and a foundry tech file; HFSS needs
via and connector geometry. An explorer has a stackup, a power map and a
floorplan sketch. That is why the loop cannot contain them and the calibration
path has to.

## 4. How to couple, in order of payoff

1. **Calibrate parameters, not outputs.** Fit `h_eff`, `k_lateral`, interface
   resistances by least squares — few physically bounded degrees of freedom that
   generalise to new floorplans. A black-box residual over five vendor points
   fits noise. `rank_churn.py` says *which* parameter is worth measuring before
   the run is bought; `correlate.py` measures it; the search re-runs in minutes.
2. **Let accurate simulation define the training distribution, not the
   corrections.** Proven at L2→L1: 14.21 K → 1.33 K came from labelling the
   region the optimiser searches, not from post-correcting
   ([`surrogate_retraining.md`](surrogate_retraining.md)). Extended upward, L3/L4
   labels a few hundred designs chosen by the guard's Mahalanobis distance —
   which is an active-learning acquisition function in disguise.
3. **Spatial submodeling.** Solve globally coarse, re-solve a hotspot ROI at
   ~20 µm with boundary conditions interpolated from the coarse field. Cost
   scales with the ROI, not the die, and it addresses our largest known limit —
   562 µm cells smearing real hotspots — with no licence. Verify two ways: refine
   until the ROI peak stops moving, and check flux balance across the interface.
   *Note*: `transient_roi_solver.py` was deleted from this repo for reporting a
   fabricated peak alongside a "100,000×" speedup. The concept was never the
   problem; the missing interface check was.
4. **Cross-domain coupling by compact model.** Thermal → electrical: emit the
   reduced state-space as a Foster/Cauer subcircuit so SPICE carries temperature
   as a node voltage with self-heating feedback. Electrical → thermal:
   activity-weighted power averaged over ≥1.5 µs — justified because the thermal
   modes start there, and that justification is itself measurable.
5. **Multi-fidelity regression, last and with discipline.** With ~10 expensive
   points, co-kriging with the cheap model as the mean function is defensible; a
   residual network on the design vector is not. Leave-one-out or nothing.

### Calibrate or substitute?

| Domain | Our model's form | Verdict |
| :--- | :--- | :--- |
| Thermal | right form, wrong coefficients | **Calibrate** (`h_eff`, `k_lateral`) |
| Parasitics | right form, wrong coefficients | **Calibrate** (Ω/mm, cap per layer) |
| Channel EM | **wrong form** — no reflections, no mode conversion | **Substitute** |

This follows from the rank-churn result rather than from taste: calibration only
helps where the correction acts *differentially* across candidates. No scaling of
a smooth loss curve creates a via-stub resonance, so for the channel there is
nothing to fit — extracted S-parameters replace `synth_channel` for the final
candidates and the inner loop stays approximate.

## 5. Two timescales: sub-ns margin and thermal transients

Measured in this repo:

| Phenomenon | Timescale | Source |
| :--- | :--- | :--- |
| PAM4 symbol (112 GBd) | **8.9 ps** | `clocking_jitter_spec.md` |
| Total jitter budget @1e-12 BER | 1650 fs | same |
| CDR loop bandwidth | 10–20 MHz | same |
| Thermal fastest mode | **1.5 µs** | `transient_solver.py` |
| Thermal slowest mode | **259 ms** | same |

Five to eight orders of magnitude, which yields two facts before any code:

1. **On the electrical timescale, temperature is frozen** — the fast engine takes
   T as a parameter, never a state.
2. **Thermal drift sits inside the CDR's tracking bandwidth** (≤660 kHz against a
   10 MHz loop), so for CDR links thermal wander costs essentially no jitter
   budget. What it costs is steady-state loss and **spatial ΔT**, which no loop
   tracks.

**Highest-value first step, no new solver:** the reference solver already returns
the full field and we have only ever published `max()`. A clock H-tree across an
18 mm die sees different temperatures per branch; on-die delay tempco is roughly
0.1–0.3 %/°C. Order of magnitude: 500 ps insertion delay × 0.15 %/°C × 8 °C ≈
**6 ps of skew**, against a 1.65 ps total jitter budget and a ±2 ps matching
requirement. If that estimate survives real numbers, thermal gradient dominates
the timing budget and is currently unmodelled.

**Sub-ns without brute force.** 1e-12 BER needs ~10¹² symbols, so: pulse response
→ statistical eye (PDA), ~1–10 ms per operating point, with temperature entering
through parameters (ρ(T) → skin-effect loss, Df drift, CTLE pole). Verifiable
licence-free against ngspice on a short PRBS, which is already wired in.

**Slow side.** `transient_solver.py` integrates `C dT/dt = ΣgΔT + P` with a
computed 1.61 µs stability limit. Two additions make it workload-capable: modal
reduction of the (C, A) pair, and emitting that reduced model as a compact
thermal network SPICE can consume.

**Coupling**: staggered, not monolithic. Average power over Δt ∈ [1 µs, 1 ms],
iterate the leakage (or refresh) fixed point 2–3 passes, step the thermal ROM,
evaluate margin at frozen T. Two claims in there must be *measured*, not assumed:
the averaging error (should be sub-mK) and the fixed point's contraction
condition (violating it *is* thermal runaway).

## 6. The return path: what exists, what is missing

`integrations/correlate.py` already defines four channels with published bands
and a guard rail (`is_self_generated`) that downgrades a self-generated input to
T0 rather than scoring it as vendor truth:

| Channel | Compares | Band | Source |
| :--- | :--- | :--- | :--- |
| `thermal` | peak Tj | 5.0 °C | Celsius / Icepak |
| `ir_drop` | worst droop | 2.0 mV | Voltus-FI |
| `parasitics` | R/C per net | 20% | StarRC / QRC |
| `channel` | insertion loss | 2.0 dB | HFSS / HyperLynx |

Missing, in increasing order of effort:

* **No timing/eye return channel** — `setup_slack_ps` from PrimeTime/Tempus and
  `eye_height_mv` / `eye_width_ui` from ADS/HSPICE/AMI would follow the same
  shape as the four above, roughly a day each plus an importer.
* **The PI model cannot express sub-ns droop.** `ir_drop_solver.py` is static and
  resistive; first droop is an L·di/dt event at 100 ps–1 ns set by package
  inductance against on-die decap, which needs a PDN impedance model Z(f).
* **Nothing turns a correlation into a changed decision.** `correlate` publishes a
  band; what is missing is re-running the ranking with the corrected model and
  reporting **rank churn** — the only output that justifies the licence hour.

## 7. How to know whether fidelity bought anything

Not RMSE. Two metrics that connect spend to outcome:

* **Realised design improvement per fidelity hour.** One data point exists:
  retraining cost ~30 minutes of compute and moved the search's chosen design
  from **77.61 °C to 72.07 °C** on the reference solver. Accuracy became
  performance through the optimiser, not through the report — the optimiser
  follows the model, so model error is design loss.
* **Decision margin ÷ model uncertainty.** Above ~3 the decision is made; below
  ~1 no amount of searching helps and you need the level above. `rank_churn.py`
  computes this directly, which is why the attach study could conclude without a
  licence while a ±1 mm keep-out question cannot.

## 8. Worked example: an LPDDR6-class memory subsystem

DRAM has a thermal **knee** rather than a slope — retention roughly halves per
10 °C and refresh doubles in extended range — so decisions are often 20–40 °C
apart, well outside our error bar. (85 °C / 105 °C are used as general DRAM
thresholds throughout, not as quotations from any JEDEC document; treat any
LPDDR6-specific rate or channel-structure figure as needing a spec check.)

| Decision | Margin | Decidable here? |
| :--- | :--- | :--- |
| Stacked vs PoP vs adjacent | 20–40 °C | **Yes** — [`memory_attach.md`](memory_attach.md) |
| Does an SoC power budget keep DRAM under the knee at all | 10–30 °C | **Yes**, as a feasibility gate |
| Dispersed vs compact logic with memory Tj as its own objective | 10–30 °C | **Yes** — one config change |
| Vertical path design (bond vs TIM vs mold) | 5–20 °C | Mostly |
| Keep-out distance to ±1 mm | 1–3 °C | **No** — inside our uncertainty |
| Signal integrity of a short single-ended route | — | **No** — wrong model form |

Needing small additions: refresh-power feedback (`P_refresh(T)` with the knee
step, giving the maximum bandwidth for which the thermal loop closes and the
margin to runaway); burst transients against the 1.5 µs–259 ms modes, which is a
throttling-policy input; reach-vs-Tj as a two-objective search.

## 9. Failure modes to avoid

* Co-simulating two domains at one rate — impossible across 10⁶.
* Fitting residuals on a handful of expensive points.
* Correcting **outputs** rather than parameters: order-preserving, therefore
  decision-neutral (§6.7 of the search report proves it for the additive case).
* Refining a mesh while the input stays coarse. Our GCI of 0.081% is convergence
  on a power map already smeared into 1.125 mm blocks — a converged answer to a
  question nobody asked.

## 10. What this implies for the to-do list

Licence-free items first, because the measured evidence says the binding error is
ours rather than the vendor's. These are carried in
[`critical_review.md`](critical_review.md) §5 as items 11–15.
