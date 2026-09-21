# 📈 Multi-Objective Floorplan Search (NSGA-II)
**Status**: ✅ **Implemented and verified** (2026-09-20)
**Code**: `physics_accelerated/src/pareto.py`, `pareto_search.py`
**Reproduce**: `cd physics_accelerated && python src/pareto_search.py --generations 80`

> **History.** `gepa.py` described itself as *"GEPA Multi-Objective Optimization"*
> and the README advertised *"Multi-objective GEPA search for Area vs. Power vs.
> Thermal"*. What it did: draw 50 random placements per generation and keep
> whichever minimised predicted peak temperature. One objective, no dominance, no
> selection, no crossover — ten independent random batches rather than ten
> generations. This document covers the replacement.

---

## 1. The algorithm, verified against a known answer

`pareto.py` implements NSGA-II: fast non-dominated sorting, crowding distance,
rank-then-crowding tournament selection, SBX crossover, polynomial mutation, and
elitist environmental selection over the combined parent+offspring pool.

Verified on **ZDT1**, whose Pareto front is analytically `f₂ = 1 − √f₁`:

| Generations | Hypervolume | Mean distance to analytic front | Max |
| :--- | :--- | :--- | :--- |
| 25 | 0.477 | 0.796 | 1.489 |
| 100 | 0.710 | **0.0037** | 0.045 |
| 250 | 0.710 | 0.0025 | 0.039 |
| 500 | 0.706 | 0.0044 | 0.033 |

Converging to the true front is the check that matters. "Beats random" alone
would not distinguish a correct implementation from a lucky one.

**A bug this surfaced.** The first hypervolume implementation derived its
integration box from the front being measured. A search that pushes its front
toward lower objectives therefore *enlarged its own box* and scored lower — which
made NSGA-II appear to regress (HV 0.835 → 0.748) and lose to random sampling.
Hypervolume is now computed over a **fixed** `[ideal, reference]` box shared by
every comparison, and is exact by sweep in two objectives. A regression test
guards it.

## 2. The design problem

Placement of **4 logic sub-macros plus the memory block** — the "shattered macro"
topology the project claims recovers thermal headroom — as a 10-variable problem.

Two objectives, deliberately:

| Objective | Direction | Why |
| :--- | :--- | :--- |
| logic peak Tj | minimise | spreading the sub-macros cools the logic |
| interconnect span | minimise | but spreading costs latency and energy |

An earlier attempt used three objectives including *thermal spread* (max − mean)
and *memory peak Tj*. Both turned out to be nearly redundant: spread tracks peak
because the mean barely moves, and memory peak tracks logic peak to within ~0.5 K
because a 5 µm Cu-Cu bond at k = 300 W/mK couples the dies tightly. Redundant
objectives inflate the apparent front without adding information, so they were
removed; memory ΔT is reported as a diagnostic instead.

## 3. Result

At an identical evaluation budget of 3,888 surrogate evaluations:

| Search | Hypervolume | Front size |
| :--- | :--- | :--- |
| **NSGA-II** | **0.951** | 48 |
| Random sampling (what `gepa.py` did) | 0.881 | 20 |

Hypervolume rises **0.720 → 0.951** across generations. The +7.9% margin is
modest because the problem is small; the front-size difference (48 vs 20) is the
more telling number — random sampling finds far fewer non-dominated trade-offs.

## 4. Does shattering actually recover headroom?

Both topologies optimised with NSGA-II at the same budget and the same total
power, then the winners re-solved on the **grid-converged reference solver**
rather than trusted from the surrogate:

| | Surrogate | Reference solver |
| :--- | :--- | :--- |
| Monolithic logic (1 × 4×4 block) | 131.25 °C | 119.07 °C |
| Shattered logic (4 × 2×2 blocks) | 86.06 °C | 77.61 °C |
| **Headroom recovered** | **+45.19 °C** | **+41.45 °C** |

The claim survives high-fidelity checking: **+41.45 °C**, direction and
magnitude both confirmed within ~9% of the surrogate's estimate. The mechanism is
straightforward — dispersed heat sources do not superpose the way a compact block
does, at identical power density per cell.

An earlier version of this comparison gave +52 °C by pitting an NSGA-II-optimised
shattered layout against a coarse grid scan of monolithic layouts with the memory
block pinned. That is not a fair comparison and the number was discarded.

## 5. Surrogate error at the optimum

Training RMSE measures a surrogate on data drawn like its training set. An
optimiser deliberately pushes into the extremes, which is exactly where a
surrogate is least reliable. Measured against the reference solver at the
designs the search actually selected (`reports/thermal_validation.json`):

| Front member | Surrogate | Reference | Error |
| :--- | :--- | :--- | :--- |
| coolest | 86.06 °C | 77.61 °C | **+8.45 K** |
| median | 119.43 °C | 107.97 °C | **+11.45 K** |
| hottest | 235.61 °C | 195.44 °C | **+40.17 K** |

Against a training-distribution RMSE of 2.03 K. Every error is positive: the
surrogate systematically **over**-predicts temperature where the optimiser
pushes.

That used to be the end of this section, with the advice to re-solve selected
candidates by hand before quoting a number. §6 is that advice, automated, and
the diagnosis of why the error is there.

## 6. The trust guard

`physics_accelerated/src/trust_guard.py` runs at the end of every search. It
re-solves what the optimiser selected on the reference solver, and it says when
the surrogate is being asked to extrapolate. Nothing the search predicts is
published as a temperature.

### 6.1 The cascade

The operator `A` depends only on geometry and boundary conditions, not on where
the power goes, so each mesh is assembled and factorised **once** and every
design after that is a back-substitution. That is what makes it affordable to
re-solve an entire front rather than a sampled three.

| Tier | What | Cost | Used for |
| :--- | :--- | :--- | :--- |
| 0 | FNO surrogate | ~0.1 ms | the search's 3,888 inner-loop evaluations |
| 1 | reference solve, 32×32×10 | **2.0 ms**/design after a 0.14 s factorisation | all 48 front members |
| 2 | reference solve, 64×64×20 | **65 ms**/design after a 13.3 s factorisation | the 3 designs worth quoting |

Tier 2 exists to show tier 1 is enough: refining 32×32×10 → 64×64×20 moves the
coolest design by **+0.20 °C**, against the 2.76 °C the *training* mesh
(16×16×5) is out. The quotable number for the best design on the front is
**77.42 °C**.

### 6.2 Every design the optimiser can express is out of distribution

The guard fits a Mahalanobis model on eight shape features of the training power
maps — total power, logic/memory split, and per-die peak-to-mean, active
fraction and radius of gyration. Position is deliberately excluded: the training
set covers the die, so an unusual *location* is not extrapolation while an
unusual *shape* is. The threshold is conformal-style — the 99th percentile of
the training distances — so at most 1% of the training set is flagged by
construction, and a test asserts it.

| | Mahalanobis distance |
| :--- | :--- |
| training set (240 maps) | mean 2.7, p99 **4.7**, max 8.1 |
| in-distribution control (32 held-out training maps) | 1.2 – 4.8 |
| **every design on the Pareto front** | **36.4 – 71.8** |

**100% of the front is flagged**, at 8–15× the threshold. The reason is
mechanical: `data_gen.py` trained the network on random r=3 discs on the logic
die and **single hot cells** on the memory die; the search places four 2×2
sub-macro blocks and a solid 4×4 memory macro. The features that are furthest
out name exactly that:

| Feature | Distance from training mean |
| :--- | :--- |
| `memory_active_fraction` | **+24.6 σ** (a 4×4 block where training had one cell) |
| `logic_peak_to_mean` | **+16.5 σ** (compact blocks where training had broad discs) |
| `logic_active_fraction` | **−5.9 σ** (6% of the die lit, against 42%) |

So the +8…+40 K error band is not bad luck at the extremes of a well-sampled
space. The search space and the training space barely overlap.

### 6.3 Where the error actually comes from

The guard splits the error three ways, and the three sum to the total exactly
(closure measured at **0.0 K**):

| Term | Mean | Max | Fixed by |
| :--- | :--- | :--- | :--- |
| network extrapolation (surrogate vs the solver that made its labels, same mesh) | **+14.21 K** | +38.18 K | retraining on the search distribution |
| solver agreement (that solver vs the reference, same mesh) | 0.00003 K | 0.00004 K | nothing — it is what makes the split valid |
| training-mesh discretisation (16×16×5 vs 32×32×10) | **+2.76 K** | +10.02 K | re-solving, which is what the guard does |
| **total** | **+16.98 K** | +46.84 K | |

The comparable in-distribution number is the first row measured on training
maps: **2.10 K**. The network is **6.8× worse where the optimiser looks** than
where it was fitted. Most of the error band is extrapolation, not mesh — which
is the finding that says *retrain on block layouts*, not *refine the mesh*.

### 6.4 The ranking survives, and now it is measured on the whole front

| | |
| :--- | :--- |
| Kendall τ, surrogate vs reference, across all 48 front members | **0.986** |
| selection regret (the surrogate's own pick vs the coolest design the reference finds) | **+0.00 °C** |

The earlier "sound for ranking, not for absolute temperatures" was inferred from
three designs. It holds across the front: the optimiser picks the design the
reference solver also considers coolest, while being 8.45 K optimistic about
what that design's temperature is.

### 6.5 Why the middle tier is an exact solve and not the ROM

The plan for this work was to re-rank on the POD-Galerkin ROM from
`thermal_rom.py` and reserve full solves for the final few. Measured
(`trust_guard.py --calibrate-screen`, over the block layouts the optimiser
actually searches, not the hotspot family the published ROM is parameterised on):

| POD rank | Max held-out field error | Max held-out peak error | ms/design |
| :--- | :--- | :--- | :--- |
| 32 | 7.4e-2 | 22.29 °C | 0.19 |
| 128 | 1.9e-2 | 5.76 °C | 0.39 |
| 200 | 4.6e-3 | 1.50 °C | 0.76 |
| 300 | 7.4e-4 | **0.11 °C** | 1.45 |
| *exact solve* | — | 0 | **1.89** |

To rank to better than 1 °C the basis needs ~300 snapshots — 300 exact solves of
offline cost — and then runs at 1.45 ms against the exact solve's 1.89 ms. The
break-even is above the size of any front this search produces, so the guard
uses the exact solve and the ROM screen stays off. **The reason is the
prefactorisation, not the ROM**: where factorisation is unaffordable the
conclusion flips, and the same 300-mode basis would beat a 65 ms tier-2 solve by
40×. The measurement is in `reports/surrogate_trust_report.json` so the
threshold can be re-checked rather than re-argued.

### 6.6 What the search publishes now

`reports/pareto_front_nsga2.json` and `.csv` carry, per front member:

```json
{ "logic_peak_tj_c": 86.06,          // surrogate, what the search optimised
  "interconnect_span_cells": 26.28,
  "reference_peak_tj_c": 77.61,      // reference solver -- quote this one
  "surrogate_error_k": 8.45,
  "in_training_distribution": false }
```

A test re-derives `reference_peak_tj_c` from the published genome and fails if it
is not a reference solve, so the front cannot quietly drift back to surrogate
predictions. `--no-trust-guard` exists and says in its own help text what it
costs you.

## 7. Related

* `reports/rom_pinn_validation.md` — the reference solver's own verification, the PINO results, and the POD ROM.
* `reports/surrogate_trust_report.json` — the guard's full output: per-design errors, distances, error budget, ROM calibration.
* `reports/thermal_validation.json` — the surrogate-vs-reference table for the coolest, median and hottest designs.
* `reports/pareto_front_nsga2.json` / `.csv` — the front, its genomes, and the hypervolume baseline.
