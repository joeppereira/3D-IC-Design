# ⬍ The Discretisation Error Was Vertical

**Status**: ✅ **Measured and fixed** (2026-09-23) · closes `critical_review.md` §5 item 11
**Code**: `physics_accelerated/src/dataset.py --refine-z`, `heat_residual.py`, `trust_guard.py`
**Reproduce**:

```bash
cd physics_accelerated/src && python dataset.py --tag mixed_z2 --refine-z 2
cd .. && python src/train.py --dataset ../serdes_architect/data/manifest_mixed_z2.json \
             --tag mixedz2 --lambda_physics 0.1 --epochs 40 --seed 2
python src/trust_guard.py
```

---

## 1. The item said 32×32. The measurement said otherwise.

Item 11 was written as *"regenerate the training set at 32×32×10, widen the
FNO's input, re-measure"*, on the assumption that the surrogate's +1.88 K
discretisation error was in-plane. That assumption was never checked, so it was
checked first — decomposing the error on six front designs before committing to
a retrain:

| Refinement | Mean effect on peak | Consistent? |
| :--- | ---: | :--- |
| In-plane, 16×16 → 32×32 | **−0.27 °C** | **No** — ranges −2.14 to +1.01 |
| Vertical, 1 → 2 z-cells per layer | **+1.77 °C** | **Yes** — +1.01 to +4.71, always positive |

**The error was vertical.** Refining in plane would have chased the smaller and
noisier half, at four times the training cost, and would have looked like a
disappointing result rather than a misdirected one.

A ten-minute measurement redirected roughly two hours of work — which is the
argument for `rank_churn.py`-style sensitivity checks generally: find out what
dominates before optimising it.

## 2. What was actually done

The stack is discretised with **two z-cells per layer** rather than one, and
the surrogate now predicts on that mesh:

* `dataset.py --refine-z 2` labels from the reference solver on the refined
  stack and splits each layer's watts across its sub-cells, so the maps and
  labels carry 10 channels instead of 5.
* `HeatEquationResidual.from_solver(solver, refine_z=2)` builds the physics
  term on the *same* refined stack — same total thickness, same materials, half
  the cell height. Without that the PINO loss would score a field against a
  different discretisation than its labels came from. The labels' own residual
  stays at **3.7e-6 K**, so the physics term is still consistent.
* `load_surrogate` reads the channel count from `fc2.bias` rather than taking
  it from the caller, and `adapt_maps` expands a 5-layer power map to whatever
  the model wants. A model and its channel count therefore cannot be paired
  wrongly.

The network, grid, optimiser and training schedule are unchanged. Only the
vertical resolution of the labels moved.

## 3. Result

Measured by the trust guard at optimiser-selected designs:

| Error term | Before (1 z-cell) | After (2 z-cells) |
| :--- | ---: | ---: |
| Network extrapolation | −1.30 K mean / 3.41 max | **−0.91 / 3.40** |
| Training-mesh discretisation | +1.88 K mean / 7.52 max | **+0.99 / 5.41** |
| **Total vs 32×32×10** | **+0.59 K mean** | **+0.08 K mean** |

The discretisation term roughly halves and the total bias all but vanishes.
Against the *legacy* surrogate on the same designs, the benchmark now reads
**18.03 K → 0.79 K (22.9× better)**, worst design 35.39 K → 2.44 K.

Held-out field RMSE went the other way — **0.580 K → 0.689 K** — because the
model now predicts twice as many channels of a field with more vertical
structure. Field RMSE and peak error at the optimum are different metrics, and
the second is the one the project quotes.

## 4. A bug this exposed, of a familiar kind

The guard's error budget compared the surrogate against a **16×16×5** solve
labelled "the training mesh". Once the surrogate was trained on 16×16×10 that
comparison was wrong: it attributed to discretisation an error the surrogate no
longer had, and to the network a difference against a mesh it had never seen.
The first run after the retrain duly reported the discretisation term getting
*worse* (+2.44 K), which is how it was caught.

`ReferenceCascade.level` now takes in-plane and vertical refinement separately,
and `audit` takes `train_refine_z`, read from the model's own weights. This is
the third time in this project that a number was compared against the wrong
discretisation — the 47 Ω/mm units error and the FDM-vs-reference mesh mismatch
were the others — and it is why the budget's three terms are asserted to sum to
the total, which they do, to **0.0 K**.

## 5. What is still on the table

* **In-plane refinement remains unmeasured as a gain.** It is worth −0.27 °C on
  average and is not consistently signed, so it was not pursued. If the power
  maps ever carry sub-macro structure (`power_map_reality.md`), that changes:
  finer in-plane cells would then be resolving something real rather than
  smoothing a block.
* **The structural band is untouched by this.** +31–66% of the temperature rise
  for power structure the 16×16 grid cannot express is a separate term, and
  still the largest one.

## 6. Related

* [`reports/surrogate_retraining.md`](surrogate_retraining.md) — the distribution fix this builds on.
* [`reports/power_map_reality.md`](power_map_reality.md) — the structural band this does not address.
* [`reports/multiobjective_search.md`](multiobjective_search.md) §6.3 — the error budget in its current form.
