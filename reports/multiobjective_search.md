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

## 5. The important caveat: surrogate error at the optimum

Training RMSE measures a surrogate on data drawn like its training set. An
optimiser deliberately pushes into the extremes, which is exactly where a
surrogate is least reliable. Measured against the reference solver at the designs
the search actually selected (`reports/thermal_validation.json`):

| Front member | Surrogate | Reference | Error |
| :--- | :--- | :--- | :--- |
| coolest | 86.06 °C | 77.61 °C | **+8.45 K** |
| median | 119.43 °C | 107.97 °C | **+11.45 K** |
| hottest | 235.61 °C | 195.44 °C | **+40.17 K** |

Against a training-distribution RMSE of 2.03 K. Every error is positive: the
surrogate systematically **over**-predicts temperature where the optimiser
pushes.

**Practical consequence: use this front for ranking, not for absolute
temperatures.** The ordering held up under reference checking — the shattering
conclusion survived — but any absolute Tj taken from the surrogate at an extreme
design can be tens of kelvin optimistic or pessimistic. Re-solve selected
candidates on the reference solver before quoting a number.

## 6. Related

* `reports/rom_pinn_validation.md` — the reference solver's own verification, and the PINO results.
* `reports/thermal_validation.json` — the full surrogate-vs-reference table.
* `reports/pareto_front_nsga2.json` / `.csv` — the front, its genomes, and the hypervolume baseline.
