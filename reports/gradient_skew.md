# ⏱ Clock Skew from the Temperature Field

**Status**: ✅ **Measured** (2026-09-23) · closes `critical_review.md` §5 item 15
**Code**: `physics_accelerated/src/gradient_skew.py`
**Data**: [`reports/gradient_skew.json`](gradient_skew.json)
**Reproduce**: `cd physics_accelerated/src && python gradient_skew.py`

---

## 1. The number this project had and never used

The reference solver has always returned the whole field. Every report until now
has published `max()` of it. Peak junction temperature is the number a thermal
engineer asks for; the number a *timing* engineer asks for is the difference
between two points, because a clock tree's branches run through different
temperatures and therefore arrive at different times.

That number was already sitting in every solve we have ever run.

## 2. Method, and what it is not

The H-tree is **balanced by construction**: 4³ = 64 sinks, every root-to-sink
path the same wire length, asserted at build time and in the tests. So any
arrival spread it reports is *thermal*, never geometric — on a flat field the
skew is exactly zero.

Each segment carries its share of the nominal insertion delay, scaled by the
local field:

```
d_segment = d_nominal · (1 + α · (T_segment − T_ref))
```

`α` (delay tempco) and the insertion delay are **inputs**, not findings: 0.15 %/°C
and 500 ps here. Skew scales linearly in both, which the tests assert, so the
transferable output is **picoseconds of skew per kelvin of gradient** rather than
any absolute delay. Temperature inversion — delay falling with temperature at low
supply — flips the sign of `α` and leaves the magnitude alone.

This is **not** a static timing analysis. There is no per-instance delay data,
no buffer library and no extracted RC anywhere in this repository, and the clock
distribution of the actual design is not described anywhere either. What is
computed is a sensitivity on a synthetic tree.

## 3. Which budget this lands in

The first version of this module compared die-spanning tree skew against the
224G link's **1.65 ps** total jitter budget and reported *"4745% of budget"*.
That is a category error, and it is recorded here because it is the kind that
reads as a dramatic finding: nobody distributes a 56 GHz clock across 18 mm — a
reference goes out and local PLLs/CDRs regenerate.

On-die skew competes for the **clock period**. A tree built to the usual ~5% of
period has, at 2 GHz, **25 ps** to spend on everything: routing imbalance, OCV,
and the thermal gradient.

The link numbers stay in the report as labelled context, because a real coupling
does exist through data-to-clock matching on forwarded-clock interfaces — over an
interface's span, not the die's.

## 4. Result

Across the 48 published front designs, on the 32×32×10 reference mesh:

| | Skew |
| :--- | :--- |
| Whole front | 10.9 – 78.3 ps (mean 38.6) |
| The 23 designs under 105 °C | **10.9 – 28.1 ps** |
| Worst feasible design | **28.1 ps = 5.6% of a 500 ps period** |
| CTS allowance at 5% of period | 25.0 ps → **exceeded** |

**The thermal gradient alone spends the entire clock-tree skew budget on the
worst feasible design, before any routing imbalance is counted.** At the flat end
of the front it takes 10.9 ps, or 44% of that allowance — still the largest
single contributor most CTS budgets carry.

## 5. The finding: peak Tj and skew are not the same objective

The front was optimised for peak Tj and interconnect span. Skew is a third
quantity the *same solve* already contained, and it does not agree with the
first:

| | |
| :--- | :--- |
| Kendall τ, peak Tj vs skew, across the front | **+0.722** |
| Coolest design | #0 |
| Flattest design | #4 |
| Cost of choosing the coolest | **+2.54 ps** of skew |
| Cost of choosing the flattest | **+2.29 °C** of peak Tj |

τ = 0.72 is correlation, not identity — the two orderings agree on the broad
trend and disagree on the winner. A design can be cool and steep or warm and
flat, and the search has never been told the difference.

This is the first quantity this project has found where the existing Pareto
front is **not** optimal, and it costs nothing to evaluate: the field is already
solved, so skew is one extra pass over a 64-sink tree. Adding it as a third
objective in `pareto_search.py` is a small change with a real trade to explore.

## 6. Caveats

* The tree is synthetic. The design's actual clock distribution is not described
  anywhere in this repository, so this measures what a *representative* balanced
  tree would suffer, not what this design will.
* `α` and insertion delay are assumptions; every number here scales linearly with
  them, which is why §2's per-kelvin figure is the one to carry away.
* The field is sampled on 562 µm cells, so a gradient sharper than a cell is
  averaged out. **This is a lower bound on the skew**, and the ROI submodeling in
  item 12 would raise it.
* Skew here is thermal only. Real CTS skew adds routing imbalance, OCV and
  supply-noise-induced jitter, none of which is modelled.

## 7. Related

* [`reports/clocking_jitter_spec.md`](clocking_jitter_spec.md) — the link jitter budget, and the UCIe ±2 ps matching requirement.
* [`reports/multiobjective_search.md`](multiobjective_search.md) — the front this was measured on.
* [`reports/fidelity_integration.md`](fidelity_integration.md) §5 — why spatial ΔT is the thermal quantity that costs timing margin, while thermal *drift* is tracked by the CDR.
