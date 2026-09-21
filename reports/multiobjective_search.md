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
| **NSGA-II** | **0.9304** | 48 |
| Random sampling (what `gepa.py` did) | 0.9081 | 24 |

Hypervolume rises **0.747 → 0.930** across generations. The +2.4% margin is
modest, and it is *smaller* than the +7.9% this table reported before the
surrogate was retrained (§5): on an objective function that is no longer
systematically biased, random sampling does relatively better. The front-size
difference (48 vs 24) remains the more telling number — random sampling finds
half as many non-dominated trade-offs at the same budget.

## 4. Does shattering actually recover headroom?

Both topologies optimised with NSGA-II at the same budget and the same total
power, then the winners re-solved on the **grid-converged reference solver**
rather than trusted from the surrogate:

| | Surrogate | Reference solver |
| :--- | :--- | :--- |
| Monolithic logic (1 × 4×4 block) | 108.34 °C | 109.09 °C |
| Shattered logic (4 × 2×2 blocks) | 71.12 °C | 72.07 °C |
| **Headroom recovered** | **+37.22 °C** | **+37.02 °C** |

The claim survives high-fidelity checking: **+37.02 °C**, with prediction and
reference now agreeing to **0.20 °C**. The mechanism is straightforward —
dispersed heat sources do not superpose the way a compact block does, at
identical power density per cell.

**This number has moved twice, both times because the comparison was made
fairer.** An early version gave +52 °C by pitting an NSGA-II-optimised shattered
layout against a coarse grid scan of monolithic layouts. A later one gave
+41.45 °C, still scanning monolithic *logic* placements while pinning the memory
macro at the die centre — the shattered side was optimising memory placement and
the monolithic side was not. The reference scan now varies all four coordinates
(~600 prefactorised solves, about a second), which lets the monolithic layout
move its memory macro into a corner and drops its best from 119.07 °C to
**109.09 °C**. The headroom is real; it was being overstated by roughly 4 °C.

## 5. Surrogate error at the optimum, and what fixed it

Training RMSE measures a surrogate on data drawn like its training set. An
optimiser deliberately pushes into the extremes, which is exactly where a
surrogate is least reliable. The trust guard (§6) measures it where it is used:

| Front member | Surrogate | Reference | Error |
| :--- | :--- | :--- | :--- |
| coolest | 71.12 °C | 72.07 °C | **−0.96 K** |
| median | 108.64 °C | 107.06 °C | **+1.58 K** |
| hottest | 201.70 °C | 201.61 °C | **+0.10 K** |

The previous version of this table read **+8.45 / +11.45 / +40.17 K**, every
error positive. The guard diagnosed why — 100% of the designs the optimiser
could express were outside the surrogate's training distribution — and
[`surrogate_retraining.md`](surrogate_retraining.md) is the fix: a training set
drawn as a superset of the search space, labelled by a direct solve. Error at
optimiser-selected designs fell **14.21 K → 1.36 K**.

**The search got better designs out of it, not just better predictions.** Led by
the retrained surrogate, NSGA-II now finds a front whose coolest member is
**72.07 °C on the reference solver**, against **77.61 °C** for the design the
biased surrogate chose. A surrogate that over-predicts non-uniformly does not
merely misreport a design; it picks the wrong one.

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
| 1 | reference solve, 32×32×10 | ~2.5 ms/design after a 0.2 s factorisation | all 48 front members |
| 2 | reference solve, 64×64×20 | ~130 ms/design after a 19 s factorisation | the 3 designs worth quoting |

Tier 2 exists to show tier 1 is enough: refining 32×32×10 → 64×64×20 moves the
coolest design by **+0.18 °C**, against the 1.88 °C the *training* mesh
(16×16×5) is out. The quotable number for the best design on the front is
**71.89 °C**.

### 6.2 The distribution check

The guard fits a Mahalanobis model on eight shape features of the training power
maps — total power, logic/memory split, and per-die peak-to-mean, active
fraction and radius of gyration. Position is deliberately excluded: the training
set covers the die, so an unusual *location* is not extrapolation while an
unusual *shape* is. The threshold is conformal-style — the 99th percentile of
the training distances — so at most 1% of the training set is flagged by
construction, and a test asserts it. It is calibrated against the training set
of the model being audited, read from the metrics file written beside the
weights, not against whatever dataset happens to be on disk.

| | Mahalanobis distance | |
| :--- | :--- | :--- |
| training set (3,000 maps) | threshold (p99) **6.7** | |
| in-distribution control (32 held-out training maps) | 1.3 – 4.4 | |
| every design on the Pareto front | **2.0 – 6.1** | **0% flagged** |

Before the surrogate was retrained those same front designs sat at **36.4–71.8**
against a threshold of 4.7 — *every one* of them flagged, at 8–15× the
threshold, because `data_gen.py` trained on r=3 discs and single hot memory
cells while the search places 2×2 blocks and a solid 4×4 memory macro. The
guard's job now is to catch the *next* such shift; the retraining closed this
one.

### 6.3 Where the error comes from

The guard splits the error three ways, and the three sum to the total exactly
(closure measured at **0.0 K**):

| Term | Mean | Max | Fixed by |
| :--- | :--- | :--- | :--- |
| network extrapolation (surrogate vs the solver that made its labels, same mesh) | −1.30 K | 3.41 K | retraining — **done**, was +14.21 K |
| solver agreement (that solver vs the reference, same mesh) | 0.00003 K | 0.00004 K | nothing — it is what makes the split valid |
| **training-mesh discretisation (16×16×5 vs 32×32×10)** | **+1.88 K** | **+7.52 K** | re-solving, which is what the guard does |
| total | +0.59 K | 5.21 K | |

**The mesh is now the dominant term.** That is the useful consequence of fixing
the network: the surrogate is 1.5× worse at optimiser-selected designs than on
its own training distribution (1.33 K against 0.90 K), down from 6.8×, and what
is left is a property of the 16×16×5 grid rather than of the network. Moving the
surrogate onto the converged mesh is the open item this now points at
(`critical_review.md` §5 item 11); until then, tier 1 is what stands between a
prediction and a published temperature.

### 6.4 The ranking, measured on the whole front

| | |
| :--- | :--- |
| Kendall τ, surrogate vs reference, across all 48 front members | **0.996** |
| selection regret (the surrogate's own pick vs the coolest design the reference finds) | **+0.00 °C** |

This held even when the surrogate was 8–47 K optimistic (τ was 0.986 then):
ranking survived a bias that absolute values did not. It is worth being precise
about what that bought, though — §5 — because the *front the search explored*
was still worse, so "good enough for ranking" was never the same as "good
enough".

### 6.5 Why the middle tier is an exact solve and not the ROM

The plan for this work was to re-rank on the POD-Galerkin ROM from
`thermal_rom.py` and reserve full solves for the final few. Measured
(`trust_guard.py --calibrate-screen`, over the block layouts the optimiser
actually searches, not the hotspot family the published ROM is parameterised on):

| POD rank | Max held-out field error | Max held-out peak error | ms/design |
| :--- | :--- | :--- | :--- |
| 32 | 7.4e-2 | 22.29 °C | 0.29 |
| 128 | 1.9e-2 | 5.76 °C | 0.57 |
| 200 | 4.6e-3 | 1.50 °C | 1.38 |
| 300 | 7.4e-4 | **0.11 °C** | 3.08 |
| *exact solve* | — | 0 | **2.74** |

To rank to better than 1 °C the basis needs ~300 snapshots — 300 exact solves of
offline cost — and then runs no faster than the exact solve it replaces. The
break-even is above the size of any front this search produces, so the guard
uses the exact solve and the ROM screen stays off. **The reason is the
prefactorisation, not the ROM**: where factorisation is unaffordable the
conclusion flips, and the same 300-mode basis would beat a 130 ms tier-2 solve
by 40×. The measurement is in `reports/surrogate_trust_report.json` so the
threshold can be re-checked rather than re-argued.

### 6.6 What the search publishes

`reports/pareto_front_nsga2.json` and `.csv` carry, per front member:

```json
{ "logic_peak_tj_c": 71.12,          // surrogate, what the search optimised
  "interconnect_span_cells": 34.52,
  "reference_peak_tj_c": 72.07,      // reference solver -- quote this one
  "surrogate_error_k": -0.96,
  "in_training_distribution": true }
```

A test re-derives `reference_peak_tj_c` from the published genome and fails if it
is not a reference solve, so the front cannot quietly drift back to surrogate
predictions. `--no-trust-guard` exists and says in its own help text what it
costs you.

## 7. Related

* [`reports/surrogate_retraining.md`](surrogate_retraining.md) — the training-distribution fix this document's §5 reports the effect of.
* `reports/rom_pinn_validation.md` — the reference solver's own verification, the PINO results, and the POD ROM.
* `reports/surrogate_trust_report.json` — the guard's full output: per-design errors, distances, error budget, ROM calibration.
* `reports/thermal_validation.json` — the surrogate-vs-reference table for the coolest, median and hottest designs.
* `reports/pareto_front_nsga2.json` / `.csv` — the front, its genomes, and the hypervolume baseline.
