# 🧠 Where the Memory Goes: Stacked, PoP, or Beside the SoC

**Status**: ✅ **Measured** (2026-09-21)
**Code**: `physics_accelerated/src/memory_attach.py`
**Data**: [`reports/memory_attach.json`](memory_attach.json)
**Reproduce**: `cd physics_accelerated/src && python memory_attach.py`

---

## 1. Why this is a decidable question

DRAM is the part of a module with a thermal **knee** rather than a slope:
retention falls roughly by half per 10 °C, and above ~85 °C a device runs in
extended temperature range with refresh at double rate. A knee makes an
architectural choice decidable — you are on one side of it or the other — where
a smooth penalty would leave the answer inside the model's error bar.

So this is the first study here that treats **memory junction temperature as the
decision variable** rather than as the diagnostic it has been until now. (The
Pareto search dropped memory Tj as an objective precisely because a 5 µm Cu-Cu
hybrid bond at k = 300 coupled the dies to within 0.5 K — true for that
topology, and the point of this study is that it is not true for the others.)

85 °C and 105 °C are used as general DRAM thresholds, configurable in the
script. They are **not** quoted from any JEDEC document, and nothing below
depends on an LPDDR-specific number.

## 2. What is compared

Three attach options on the same footprint, cooling and ambient, so only the
heat path differs:

| Option | Path from memory to the cold plate |
| :--- | :--- |
| `stacked` | 5 µm Cu-Cu hybrid bond (k = 300) to the logic die, then out |
| `pop` | 150 µm mold gap (k = 0.8) to the logic die, then out |
| `adjacent` | laterally through mold and substrate — **the case a per-layer conductivity cannot express at all** |

The third is why `Region` now exists: a rectangular in-plane patch of a
different material inside one layer, so mold and silicon can sit at the same
height. That change also made the in-plane conductance a harmonic mean of the
two half-cells — which reduces exactly to the old form on a uniform layer, and
the analytic-slab benchmark still passes at 1.04e-9 °C.

Each option is run in **four configurations**: cold plate on the logic side or
the memory side, with and without a 500 µm copper lid. Reporting one of them
would have generalised a module result to a phone.

## 3. The arithmetic, and one trap in it

Conduction with fixed boundary conditions is linear in the load, so the *field*
is affine in power: two solves give the exact coefficients per cell.

The trap: the **peak** is a max over cells of affine functions, which is convex
and *not* affine. Fitting a line to two peak values is wrong wherever the
hotspot moves between them — which is exactly what happens when the neighbouring
die's power changes. The first version of this script did that and its own
linearity assertion caught it, 0.0994 °C out. Coefficients are therefore kept
per cell, every peak is a max over them, and the power at which a die reaches a
threshold is exact:

```
P* = min over cells of (threshold − a_cell) / b_cell
```

## 4. Result

Feasible SoC power is the *binding* limit of two: memory at its 85 °C knee, and
logic at 105 °C. Reporting only the memory's budget would reward decoupling the
dies at any cost to the logic — which is precisely what `adjacent` does.

**Cold plate on the logic side:**

| Option | ΔTj_mem/W | ΔTj_logic/W | Coupling | Memory knee | Logic max | **Feasible** | Binds |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `stacked` | 0.384 | 0.384 | 1.00 | 153.3 W | 205.4 W | **153.3 W** | memory |
| `pop` | 0.380 | 0.384 | 0.99 | 150.2 W | 205.4 W | **150.2 W** | memory |
| `adjacent` | 0.069 | 1.259 | 0.05 | 818.7 W | 63.4 W | **63.4 W** | logic |
| `adjacent` + lid | 0.305 | 0.842 | 0.36 | 191.2 W | 94.6 W | **94.6 W** | logic |

**Cold plate on the memory side:**

| Option | ΔTj_mem/W | ΔTj_logic/W | Coupling | **Feasible** | Binds |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `stacked` | 0.410 | 0.411 | 1.00 | **143.2 W** | memory |
| `pop` | 0.407 | 0.977 | 0.42 | **80.6 W** | logic |
| `adjacent` | 0.177 | 5.844 | 0.03 | **13.7 W** | logic |
| `adjacent` + lid | 1.643 | 2.539 | 0.65 | **30.0 W** | logic |

`stacked > pop > adjacent` in **all four configurations**, and under every
perturbation `rank_churn.py` sweeps (±50% on cooling coefficient and on lateral
conductivity). This choice does not need a licensed run.

## 5. What the numbers say that the ranking does not

* **Side-by-side decouples the dies by 20× and costs more than it buys.**
  Coupling falls from 1.00 to 0.05 — the memory barely feels the SoC — but a die
  surrounded by mold has no lateral path, so its own ΔTj/W triples. Net: less
  than half the feasible SoC power. Decoupling is not the objective; the binding
  limit is.
* **A copper lid is worth more to the adjacent option than the attach is.**
  63.4 W → 94.6 W, a 49% gain, from one 500 µm layer. The lid *is* the lateral
  path a mold-embedded die lacks. An earlier version of this study omitted the
  lid from every option and would have concluded that `adjacent` loses by 2.4× —
  a stackup artifact, the same class of unfairness that once put +52 °C on the
  shattered-macro claim.
* **On the memory side, the lid becomes a heat bridge.** Coupling rises 0.03 →
  0.65: copper spanning both dies carries the SoC's heat straight to the DRAM.
  The same component helps in one orientation and hurts in the other.
* **The PoP mold gap does not protect the DRAM** when the plate sits above the
  logic (150.2 W vs `stacked`'s 153.3 W). The memory's only good path to the
  plate runs *through* the logic die, so insulating it from the logic also seals
  its own escape. Flip the plate to the memory side and the gap becomes
  decisive — the logic's budget collapses from 205 W to 80.6 W.

## 6. What this does not settle

* **Same-footprint framing.** All options share an 18 × 18 mm footprint, so the
  adjacent dies are each about half the width. That is a real cost of going
  side-by-side, but it means the comparison is at fixed *module* area, not fixed
  die size.
* **Uniform power per die.** This compares heat *paths*, not floorplans — the
  floorplan question is `pareto_search.py`, and the two should eventually be run
  together.
* **Representative stackup.** Mold and gap thicknesses are plausible, not a
  datasheet. The absolute watt figures move with them; the ordering survived
  every perturbation tested, which is the claim being made.
* **No electrical side.** Attach choice also decides link energy and reach, and
  for a short single-ended interface this repo's analytic channel model is not
  adequate — reflections and crosstalk dominate there, and it models neither.

## 7. Related

* [`reports/multiobjective_search.md`](multiobjective_search.md) §6.7 — the perturbation sweep this study reuses.
* [`reports/rank_churn.json`](rank_churn.json) — what a vendor correlation could and could not change.
* `physics_accelerated/src/thermal_reference.py` — `Region`, and the harmonic-mean in-plane conductance it required.
