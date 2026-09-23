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

## 3. Which budget this lands in — and an invented number, removed

Two framings were wrong before this section reached its current form, and both
are worth recording because each read as a finding.

**First: the wrong budget.** The original version compared die-spanning tree
skew against the 224G link's **1.65 ps** total jitter budget and reported
*"4745% of budget"*. That is a category error — nobody distributes a 56 GHz
clock across 18 mm; a reference goes out and local PLLs/CDRs regenerate.

**Second: an invented clock.** The replacement compared skew against *"5.6% of a
500 ps period"* — a 2 GHz core clock that **appears nowhere in this repository**.
There is no clock frequency in any config or spec here; the only frequencies
present are the 56 GHz SerDes Nyquist and a mention of PCIe 7.0. A number I
chose was sitting in a results table looking like a requirement.

The reporting is now inverted, which removes the assumption entirely:

> **given the skew, at what clock frequency does it alone exhaust the
> allowance?**

| Design | Skew | Fills a 5%-of-period allowance at |
| :--- | ---: | ---: |
| Flattest on the front | 10.9 ps | **4.59 GHz** |
| Worst feasible (<105 °C) | 28.1 ps | **1.78 GHz** |

The only remaining assumption is the rule of thumb that a clock tree is built to
a few percent of the period — an argument, not a datasheet, and exposed as a
parameter.

## 4. Which clock domain — the question that decides whether this matters

Interface clocks are much faster than any core clock: PCIe 7.0 signalling and
LPDDR6-class interfaces run well above a few GHz, so a naive reading says the
budget is far tighter there. But those clocks are distributed **inside a PHY**,
not across the die, and a shorter tree cuts *both* the temperature difference it
sees and the insertion delay that difference scales.

Measured on a feasible front design, with insertion delay scaled proportionally
to span:

| Tree span | Insertion | Sink-to-sink ΔT | Skew | Break-even |
| ---: | ---: | ---: | ---: | ---: |
| 18.0 mm (die) | 500 ps | 42.5 °C | **25.3 ps** | 1.98 GHz |
| 9.0 mm | 250 ps | 48.7 °C | 11.7 ps | 4.26 GHz |
| 4.5 mm | 125 ps | 35.6 °C | 3.8 ps | 13.24 GHz |
| 2.2 mm (PHY) | 62 ps | 13.2 °C | **0.72 ps** | **69.69 GHz** |

**A 35× reduction from die span to PHY span**, and the span effect wins
decisively over the frequency effect. The conclusion that follows:

> The thermal gradient is a **core/fabric clock problem**, not an interface
> problem. A PHY-local forwarded clock at 0.72 ps is comfortable even against
> the UCIe ±2 ps matching requirement; a die-spanning tree at 25 ps is not
> comfortable above ~2 GHz.

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
  averaged out. **This is a lower bound on the skew.** [`submodel.md`](submodel.md)
  since measured what that smearing costs: rearranging a macro's watts inside its
  own footprint, at identical total power, moves the peak +36 °C — a sharper
  field means steeper gradients and more skew than reported here.
* Skew here is thermal only. Real CTS skew adds routing imbalance, OCV and
  supply-noise-induced jitter, none of which is modelled.

## 7. Related

* [`reports/clocking_jitter_spec.md`](clocking_jitter_spec.md) — the link jitter budget, and the UCIe ±2 ps matching requirement.
* [`reports/multiobjective_search.md`](multiobjective_search.md) — the front this was measured on.
* [`reports/fidelity_integration.md`](fidelity_integration.md) §5 — why spatial ΔT is the thermal quantity that costs timing margin, while thermal *drift* is tracked by the CDR.
