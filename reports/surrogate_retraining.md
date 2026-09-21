# 🔁 Retraining the Surrogate on the Distribution the Optimiser Searches

**Status**: ✅ **Done and measured** (2026-09-21)
**Code**: `physics_accelerated/src/dataset.py`, `train.py`, `surrogate_benchmark.py`
**Reproduce**:

```bash
cd physics_accelerated/src
python dataset.py                                                  # 3,800 mixed maps
python dataset.py --distribution layouts  --train 0 --val 0 --test 400 --tag layouts_eval
python dataset.py --distribution hotspots --train 0 --val 0 --test 400 --tag hotspots_eval
cd .. && python src/train.py --dataset ../serdes_architect/data/manifest_mixed.json \
             --tag mixed --lambda_physics 0.1 --epochs 40 --seed 2
python src/surrogate_benchmark.py                                  # the table in §4
```

(`run_full_cycle.sh` phases 1–3 run the same pipeline end to end. Datasets and
weights are build artifacts — `data/` and `results/` are gitignored — so a fresh
clone regenerates them; the seeds make that reproducible rather than merely
similar.)

---

## 1. What the trust guard found, and why it pointed here

The [trust guard](multiobjective_search.md#6-the-trust-guard) measured the
surrogate where its output is actually used — at the designs the optimiser
selects — and split the error into the parts with different fixes:

| Term | Mean | Fixed by |
| :--- | :--- | :--- |
| network extrapolation | **+14.21 K** | retraining |
| training-mesh discretisation | +2.76 K | re-solving (the guard already does this) |
| solver disagreement | 0.00003 K | nothing |

and it found the reason the first row was so large: **every design the optimiser
could express was outside the training distribution.** `data_gen.py` drew random
r=3 discs on the logic die and *single hot cells* on the memory die;
`pareto_search.py` places 2×2 sub-macro blocks and a solid 4×4 memory macro.
Mahalanobis distance on shape features: training p99 **4.7**, every front member
**36.4–71.8**. The same network was 6.8× worse there (14.21 K) than on the
distribution it was fitted to (2.10 K).

That is a training-set problem, not a network problem. This document is the fix
and its measurement.

## 2. The new training set

`physics_accelerated/src/dataset.py`. Two changes from `data_gen.py`:

**The distribution is explicit and selectable.** `layouts` draws macro
placements, deliberately as a *superset* of the search's parameterisation, so
that measuring the retrained model at optimiser-selected designs is still a
generalisation test and not a lookup:

| | training sampler | what the search uses |
| :--- | :--- | :--- |
| logic sub-macros | 1–8 | 4 |
| sub-macro edge | 2–4 cells | 2 |
| memory macro edge | 3–5 cells | 4 |
| logic power fraction | 0.50–0.90 | 0.75 |
| total power | 40–80 W | 60 W |

Every setting the search uses is an interior point of the range it was trained
on. `hotspots` reproduces the old distribution exactly, so old and new models
can be compared on it; `mixed` is half of each, and is what ships — covering the
search space is the point, losing the distribution the surrogate already handled
is not.

**Labels come from a direct solve.** The reference solver factorises the same
16×16×5 discretisation once and back-substitutes: exact for that mesh, ~300×
faster than iterating the FDM solver to a tolerance, and impossible to stop
early. (`data_gen.py` once capped its solve at 200 iterations — 4% of the way to
convergence — and trained the network on fields 21 °C too cold.) The two
agree to **0.0031 K** across the field.

| Split | n | Peak Tj range | Source |
| :--- | :--- | :--- | :--- |
| train | 3,000 | 55.2–369.8 °C | `mixed` |
| val | 400 | 59.4–257.2 °C | `mixed`, separate RNG stream |
| test | 400 | 55.6–267.0 °C | `mixed`, separate RNG stream |
| eval: layouts | 400 | 55.3–300.3 °C | `layouts` only |
| eval: hotspots | 400 | 77.5–149.8 °C | `hotspots` only |

3,800 labelled maps take **under a second** of solver time. The labels' own
heat-equation residual is **3.6e-6 K** — they are solutions of the equation the
physics term penalises, which is the precondition for that term meaning
anything.

## 3. Held out, which it never was before

`train.py` previously trained on every sample it had and reported RMSE on the
same samples. **Every surrogate RMSE this project published before this change
was an in-sample number**, including the 2.03 K that the error band was compared
against. The loader now takes the manifest's train/val/test split (and splits the
legacy pair 80/20 rather than reporting it on itself), normalisation statistics
come from the training split only, and the metrics file carries every split so
the gap between them is visible rather than implied.

For the shipped model that gap is small: train 0.535 K, val 0.593 K, test
0.580 K.

## 4. Old model vs new, on the distributions that matter

`surrogate_benchmark.py`. All numbers held out; both models are asked about the
same designs; the benchmark asserts its own conclusion and fails if retraining
did not help, if the old distribution was lost, or if the search space is still
uncovered.

| Held-out set | Metric | Legacy | Retrained | |
| :--- | :--- | ---: | ---: | :--- |
| `layouts` (400) | field RMSE | 6.744 K | **0.721 K** | 9.4× |
| | peak \|error\| | 10.084 K | **1.229 K** | 8.2× |
| `hotspots` (400) | field RMSE | 2.231 K | **0.347 K** | 6.4× |
| | peak \|error\| | 2.145 K | **0.452 K** | 4.7× |

**At the designs the optimiser selected** — both models asked about the *same*
designs (the published front), against the reference solver on the 16×16×5 mesh
both were trained on, so this is network error with discretisation held out of
it:

| | Legacy | Retrained |
| :--- | ---: | ---: |
| mean \|error\| | 18.31 K | **1.33 K** (13.7× better) |
| worst single design | 34.67 K | **3.41 K** |
| designs outside the training distribution | **100%** | **0%** |
| Mahalanobis, worst design | 71.7 | 6.1 |

That front is the one the *retrained* model found, which is the harder test for
the legacy model and the fairer one for the comparison: both answer for
identical inputs. Measured instead at the front each model actually led its
optimiser to — the number the trust guard reported at the time — it is
**14.21 K → 1.33 K**. The conclusion does not depend on which of the two
readings is used.

Two things in that table are worth separating. The **13.7×** is the answer to the
question this work asked. The **2.231 K → 0.347 K on `hotspots`** is not a
side-effect to skip past: the retrained model is *also* 6.4× better on the old
distribution, because the new training set is 12× larger and its labels are
exact rather than iterated. The retraining did not trade one capability for
another.

For scale, the legacy model's 2.231 K held-out RMSE on `hotspots` is close to
the 2.03 K it reported in sample — the old headline was not badly optimistic on
its own distribution. It was simply never measured anywhere near where it was
used.

## 5. Does the physics term still earn its place?

The λ sweep in [`rom_pinn_validation.md`](rom_pinn_validation.md) §3 was measured
**in sample** on 240 maps and reported −22% field RMSE at λ = 0.1. Re-measured
held out on the new training set, with **three seeds per setting** because a
single run cannot distinguish a real effect from initialisation noise:

| λ | Held-out field RMSE (K) | Held-out PDE residual (K) |
| :--- | :--- | :--- |
| 0 (data-only) | 0.626 ± 0.005 | 0.0915 ± 0.0040 |
| **0.1** | **0.606 ± 0.026** | **0.0457 ± 0.0017** |

(mean ± sample standard deviation over seeds 0, 1, 2.)

**The data-fit improvement does not survive the larger dataset: 3.2%, with a
seed-to-seed spread larger than the difference.** The residual improvement does:
**−50%**, more than ten standard deviations clear. That is the textbook
behaviour of a regulariser — with 240 samples it bought accuracy, with 3,000 it
mostly buys physical consistency — and the earlier −22% should be read as an
in-sample number from the data-starved regime, not as what the physics term is
worth today.

The shipped model is λ = 0.1, selected by **validation** RMSE across the three
seeds (seed 2) and reported on test. Keeping the physics term is a judgement:
its accuracy benefit is now within noise, and its residual benefit is not.

## 6. What this does not fix

* **Discretisation.** The surrogate still predicts on the 16×16×5 mesh its
  labels come from, which reads **+1.88 K** hotter on average (+7.52 K worst) at
  optimiser-selected designs than a 32×32×10 solve — now the *largest* of the
  error terms, and the open item this points at (`critical_review.md` §5
  item 11). Retraining cannot change it; the trust guard's tier-1 re-solve is
  what handles it, and it is why published temperatures are solver output rather
  than predictions.
* **The guard's job.** Nothing here removes the need for it. The flag is what
  would catch the *next* distribution shift — a different macro topology, a
  different power budget, a different stackup — and the re-solve is what makes a
  published number defensible regardless.

## 7. Related

* [`reports/multiobjective_search.md`](multiobjective_search.md) §6 — the trust guard that found this.
* [`reports/surrogate_retrain.json`](surrogate_retrain.json) — the benchmark's full output.
* [`reports/rom_pinn_validation.md`](rom_pinn_validation.md) §3 — the original λ sweep, in sample.
* `serdes_architect/data/manifest_mixed.json` — the dataset's own record: splits, seeds, ranges, label method.
