# 🔬 Submodeling: What the 562 µm Cell Cannot See

**Status**: ✅ **Measured** (2026-09-23) · closes `critical_review.md` §5 item 12
**Code**: `physics_accelerated/src/submodel.py`
**Data**: [`reports/submodel.json`](submodel.json)
**Reproduce**: `cd physics_accelerated/src && python submodel.py`

---

## 1. The distinction this rests on

The grid-convergence study reported **GCI 0.081%** and a 0.18 °C difference
between 32×32×10 and 64×64×20. That is a true statement about the
*discretisation* and it has been quietly load-bearing for every absolute
temperature this project publishes.

It is also the answer to a question nobody asked. The power map fed to that
solve is already smeared into **1.125 mm blocks** — a macro's watts spread
evenly across its own footprint, because that is all a 16×16 grid can express.
Refining the mesh under a smeared input converges to the smeared answer.

Two different things were being conflated:

| | Converged? |
| :--- | :--- |
| **Discretisation** — does the mesh resolve the given power map | **Yes**, 0.18 °C |
| **Input** — does the power map resolve the real heat source | **Never measured** |

This report measures the second.

## 2. Method

Solve globally coarse, cut out a region, re-solve it on a fine mesh that
inherits its surroundings through a prescribed boundary temperature (Dirichlet,
which the solver did not previously support). Cost scales with the region: a
9 mm box at 70 µm resolution is affordable where the same resolution over 18 mm
is not.

Two checks make this trustworthy rather than merely plausible, and both of them
found bugs:

**Exactness at matching resolution.** Run the submodel at the parent's own
in-plane resolution and it must reproduce the parent's interior to solver
tolerance.

| | Interior error |
| :--- | :--- |
| First version | 3.03e-2 °C |
| After the fix | **3.89e-11 °C** |

The bug: a **corner cell has two open faces looking at two different
neighbours**, and the boundary array carried one value per cell rather than one
per face. Small, entirely at the corners, invisible to inspection, and the sort
of thing that would have quietly biased every submodel result.

**Region independence.** Enlarge the box; the peak must stop moving, because the
submodel inherits the parent's error at its boundary and that boundary has to sit
where the error no longer matters.

| Box | Cells | Peak | Lateral flux |
| :--- | ---: | ---: | ---: |
| 3.9 × 3.9 mm | 1,960 | 72.200 °C | +7.08 W |
| 5.6 × 5.6 mm | 4,000 | 72.201 °C | +4.01 W |
| 7.3 × 7.3 mm | 6,760 | 72.197 °C | +0.43 W |
| 9.0 × 9.0 mm | 10,240 | 72.194 °C | −1.83 W |

Stable to 0.007 °C while the boundary flux swings through zero — the box is far
enough out.

A third fix came with them: the energy balance only ever counted the top and
bottom convective faces, so a solve with a prescribed lateral boundary read a
**58% "error"** while being perfectly correct. The lateral term is now in the
balance (closing to ~1e-12), and it doubles as the interface flux above.

## 3. Result: the same watts, arranged differently

Fixed design, fixed total power, fixed mesh. Only the arrangement of the macro's
power *within its own footprint* changes — structure a 562 µm cell cannot
represent:

| Power in core | Core area | Peak density | Peak Tj | vs uniform |
| ---: | ---: | ---: | ---: | ---: |
| 0% | 100% | 111 W/cm² | 72.21 °C | — |
| 25% | 25% | 194 W/cm² | 78.87 °C | +6.65 °C |
| 50% | 25% | 278 W/cm² | 85.52 °C | +13.31 °C |
| **50%** | **6.25%** | **944 W/cm²** | **108.21 °C** | **+36.00 °C** |
| 75% | 6.25% | 1361 W/cm² | 126.21 °C | +54.00 °C *(beyond plausible density)* |
| 90% | 1.56% | 6411 W/cm² | 199.34 °C | +127.12 °C *(beyond plausible density)* |

**The published 72.07 °C is the temperature of a design whose power is uniform
inside each macro.** If half a macro's power sits in 6% of its area — 944 W/cm²,
within the range normally discussed for a logic hotspot — the peak is 108 °C.

Rows above 1000 W/cm² are marked and excluded from the headline: they show where
the trend goes, and are not predictions.

## 4. What this means for everything else here

* **It is not a defect in the solver.** Given its input, the solver is right and
  grid-converged. The error is in what the input can express.
* **No vendor correlation of the same input would find it.** Icepak fed the same
  1.125 mm blocks returns the same smeared answer. This is a *modelling*
  resolution gap, not a model-form gap, and it is invisible to the T1/T2 ladder.
* **The trust guard's error budget gets a fourth term.** Network extrapolation
  (−1.30 K), solver agreement (0.00003 K) and training-mesh discretisation
  (+1.88 K) now sit beside an input-resolution sensitivity of **up to +36 °C** —
  an order of magnitude larger than all three combined, and not of the same
  kind: it is a statement about an unknown, not a measured error.
* **The gradient-skew result is a lower bound**, as its own report warned.
  Sharper fields mean steeper gradients, and 28.1 ps was measured on the smeared
  field.
* **Rankings are probably safe, absolutes are not.** Concentration affects every
  candidate in the same direction, so the Pareto ordering should survive — but
  `rank_churn.py` has not been run with concentration as a perturbation axis, so
  that is an expectation, not a measurement.

## 5. Caveats

* The concentration profile is a **parameterised assumption**, not a floorplan.
  This measures sensitivity to unresolved structure; it does not claim to know
  what the structure is. Closing that needs real per-instance power data, which
  this repository does not have.
* The submodel inherits its parent at the boundary, which is what region
  independence tests — it does not improve on the parent *outside* the box.
* Still no lateral heterogeneity below the material level, no electro-thermal
  feedback, and no vendor correlation.

## 6. Related

* [`reports/rom_pinn_validation.md`](rom_pinn_validation.md) §1 — the grid-convergence study this qualifies.
* [`reports/gradient_skew.md`](gradient_skew.md) — the skew result this makes a lower bound.
* [`reports/fidelity_integration.md`](fidelity_integration.md) §4 — where submodeling sits among the coupling mechanisms.
