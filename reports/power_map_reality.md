# 🗺 What a Power Map Actually Looks Like

**Status**: ✅ **Measured** (2026-09-23) · closes `critical_review.md` §5 item 17
**Code**: `physics_accelerated/src/floorplan_power.py`, `openroad_power.py`, `scripts/openroad/`
**Data**: [`reports/floorplan_power.json`](floorplan_power.json), [`reports/openroad_power.json`](openroad_power.json)

---

## 1. The gap this closes

[`submodel.md`](submodel.md) measured that rearranging a macro's watts *inside
its own footprint* — structure below a 562 µm cell — moves peak Tj by up to
+36 °C at fixed total power. It also had to admit that this repository had no
data on that arrangement at all, so the sweep was parameterised guesswork.

Every power map solved here had been one of two abstractions:

| | What it is |
| :--- | :--- |
| The search's map | four uniform 2×2 cells of logic, one 4×4 memory block |
| The design record | macro rectangles at fixed origins, uniform within each |

Neither says anything about how power sits *inside* a block. This report
measures it two ways: from the floorplan the DEF emitter already carries, and
from a real place-and-route run.

## 2. The floorplan the repository already had

`floorplan_power.py` rasterises `integrations/canonical.py` — the same record
DEF/LEF is emitted from. **Real**: 16 `SERDES_224G_PHY` at 600 × 900 µm and 16
`UCIE2_PHY` at 900 × 600 µm with their fixed origins and orientations; die
footprints; the 39 W / 15 W / 6 W split that sums to the 60 W budget.
**Estimated**: how much of a die's power sits inside its macros — swept, not
quoted.

| | Real floorplan | Search abstraction |
| :--- | ---: | ---: |
| Peak Tj | **53.01 °C** | 77.61 °C |
| Peak / die-mean power density | 2.66 | 16.0 |
| Area holding 50% of power | 24.5% | 3.1% |
| Active area fraction | 100% | 6.2% |

**The search's abstraction is far more concentrated at macro level than the
actual floorplan**, because it crams 45 W into four small blocks while the real
design spreads it over 32 macros around the die perimeter plus distributed
logic. On that axis the search has been over-predicting by ~25 °C.

Orientation is taken from `canonical.footprint_um`, not re-derived — a 900 × 600
macro placed `E` covers 600 × 900 of die, and re-deriving that rule is how two
macros silently overlapped once before.

## 3. A real placed design

`scripts/openroad/` runs OpenROAD (open source, no licence) on ASAP7: Yosys
synthesises, OpenROAD places, OpenSTA reports power per instance, and
`openroad_power.py` joins placement to power to get watts at cell resolution.

| Design | Instances | Power | Cell | Peak/mean | **50% of power in** |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `gcd` | 415 | 1.66 mW | 1.39 µm | 8.31 | **15.0%** |
| `aes` | 12,485 | 72.6 mW | 7.61 µm | 8.79 | **18.6%** |

Two designs three orders of magnitude apart in size agree on the shape: **half
the power sits in roughly 15–19% of the area**, with peak-to-mean around 8–9.
Power splits 56–64% internal, 36–44% switching, leakage negligible at this
activity.

## 4. The answer

Feeding the *measured* shapes into the submodel sensitivity curve — same design,
same total watts, same mesh, only the arrangement inside the macro changing:

| Arrangement | Peak Tj | vs uniform |
| :--- | ---: | ---: |
| Uniform macro — **what the search assumes** | 72.21 °C | — |
| `aes` measured (50% in 18.6%) | 89.05 °C | **+16.84 °C** |
| `gcd` measured (50% in 15.0%) | 93.61 °C | **+21.40 °C** |
| *previously assumed* (50% in 25%) | 85.52 °C | +13.31 °C |
| *previously assumed* (50% in 6.25%) | 108.21 °C | +36.00 °C |

**Real power-map structure is worth +17 to +21 °C on this stack** — not the
+13 °C optimistic end of the old sweep, and not the +36 °C worst case. Measured
from two independent designs rather than assumed.

## 5. The two errors run in opposite directions

This is the part that matters for how the numbers are used:

* **Above macro level**, the search abstraction is *too* concentrated: four hot
  blocks where the real floorplan has 32 spread macros. Worth about **−25 °C**.
* **Below macro level**, it is *not concentrated enough*: uniform where a real
  design puts half its power in a sixth of its area. Worth about **+17 to
  +21 °C**.

Neither error was visible without the other measurement, and they partially
cancel — which is exactly why quoting either one alone would have been
misleading. The net on the published 72.07 °C is small but the *uncertainty* is
not, and it is asymmetric.

## 6. Caveats

* ASAP7 is a predictive 7 nm library and `gcd`/`aes` are ORFS benchmarks, not a
  CXL switch. **Absolute W/cm² does not transfer**; the shape does, and shape is
  what the sensitivity curve consumes.
* **The flow stops at placement.** CTS crashes under amd64 emulation on Apple
  silicon (`illegal instruction` in TritonCTS), so clock-tree buffers and
  routing parasitics are absent. Both would add power and concentrate it
  further, so **15–19% is an upper bound on the area, and +17…+21 °C is a lower
  bound on the penalty**.
* Switching activity is an assumption (0.2), stated in the report and swept-able.
* `sta::instance_power` segfaults in this environment; power is parsed from
  `report_power -instances`. Recorded in `scripts/openroad/README.md`.

## 7. Related

* [`reports/submodel.md`](submodel.md) — the sensitivity curve this supplies the real input to.
* [`reports/gradient_skew.md`](gradient_skew.md) — also a lower bound for the same reason; a sharper field means steeper gradients.
* [`reports/fidelity_integration.md`](fidelity_integration.md) §4 — where open-source EDA sits among the coupling mechanisms.
