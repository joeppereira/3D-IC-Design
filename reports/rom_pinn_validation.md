# 🧪 Physics Validation: Reference Solver, PINO, and Multi-Objective Search
**Status**: ✅ **Implemented and measured** (2026-09-20)
**Reproduce**: `python -m unittest discover -s tests/physics -t .` (149 tests total in the repo)

> **History.** The first version of this file presented a validation table against
> "Ansys Icepak (High-Fidelity Baseline)" — 104.2 °C vs 102.8 °C, 8 hours → 15 ms,
> "1.9M × speedup" — with no Icepak dataset, no POD implementation and no physics
> residual anywhere in the repository. The second version replaced it with an
> honest "not implemented" status. This third version reports what has now been
> built and measured. No number below is an aspiration.

---

## 1. Reference solver: verified, not asserted

`physics_accelerated/src/thermal_reference.py` — finite-volume steady-state
conduction in SI units, harmonic-mean face conductances, Robin (convective)
boundaries, direct sparse solve.

| Verification | Result |
| :--- | :--- |
| **Analytic 1D slab** (uniform heating, insulated bottom, convective top) | error **1.04e-9 °C** against the closed-form solution |
| **Global energy balance** (heat out through convective faces = power in) | relative error **8.4e-12** |
| **Grid convergence**, 3-die stack, 18×18 mm, 60 W, concentrated hotspot | Richardson-extrapolated peak **83.87 °C**, **GCI 0.081%** → grid-converged |

The discretisation reproduces the analytic benchmark *exactly* at every mesh
(error at round-off), which is stronger than a second-order claim — and it means
the scheme's formal order of accuracy cannot be measured from that case. On the
realistic discontinuous hotspot the Richardson exponent comes out near 5, which
is **not** an order of accuracy: the hotspot's discrete footprint changes as the
mesh refines, so the grids are not in the asymptotic range. The GCI and the
extrapolated value are the usable outputs. This caveat is recorded in the
method's docstring and in `mesh_convergence_audit.json` so it is not quoted
wrongly later.

**83.87 °C is the first defensible peak-temperature number this project has
had.** For comparison, the repository previously carried 98.5 °C (a literal in
`final_design_audit.json`), 102.8 °C and 104.2 °C (this document's earlier
fabricated table), 112 °C (legacy), and 25.03 °C — ambient — which was what the
flow's own solver actually stored.

## 2. The production solver, corrected and measured

`serdes_architect/src/thermal/solver.py` used `dx = dy = dz = 1.0` ("normalized")
with `PHYSICAL_SCALE = 500.0` documented as *"Calibrated for 100W on 10mm die →
~85C"* — on a config describing an **18 mm** die. Its output was a relative field,
not a temperature. It now uses real geometry from `size_mm`, per-layer
thicknesses, convective boundaries with `h` in W/m²K, and iterates to a residual
tolerance instead of a fixed 1000 steps.

| Check | Result |
| :--- | :--- |
| Agreement with the reference solver, same mesh | **0.0036 °C** (different methods, same equations) |
| Global energy balance | 8.9e-4 relative |
| Discretisation error of the 16×16 training mesh vs grid-converged | **−0.50 °C** |

**Two data bugs surfaced during this work**, both of which had been silently
shaping every thermal result:

* `Hybrid_Bond` was absent from `k_map`, so the 5 µm Cu-Cu bond was modelled at
  the fall-through default of **1.0 W/mK** instead of ~300 — a near-insulator in
  the most important path of a 3D stack. Correcting it **lowered peak Tj by
  6.02 °C**. Note that the project separately claims "recovered 6.5 °C headroom
  via shattered logic macros": a single missing table entry was the same
  magnitude as the headline thermal win, so that claim cannot be separated from
  modelling error without a controlled comparison. The solver now raises on an
  unknown material rather than defaulting.
* `data_gen.py` capped the label solve at 200 iterations. On the corrected solver
  that is ~4% of the way to convergence: labels peaked at **36.28 °C** where the
  converged answer is **57.11 °C**. The network was being trained on fields that
  were both mis-scaled and 21 °C too cold.

## 3. PINO: the physics residual, and what it actually bought

An FNO is an **architecture**; "physics-informed" is a property of the **loss**.
Trained on labels alone this was a data-driven neural operator, which is why it
faithfully reproduced a non-physical field for months. Adding the discrete
heat-equation residual (`physics_accelerated/src/heat_residual.py`) makes it a
*physics-informed neural operator* (PINO, Li et al. 2021):

`L = L_data + λ·‖ r ‖²`, where `r` is the finite-volume conduction residual
divided by the total face conductance, so it is expressed in **kelvin** and is
directly interpretable: "this field violates the heat equation by X K per cell".

Measured on 240 samples, 60 epochs:

| λ | Field RMSE (K) | PDE residual (K) |
| :--- | :--- | :--- |
| 0 (data-only baseline) | 2.604 | 0.343 |
| 0.001 | 2.480 | 0.325 |
| 0.01 | 2.300 | 0.233 |
| **0.1** | **2.031** (−22%) | 0.140 (−59%) |
| 1.0 | 2.285 | **0.082** (−76%) |

The physics term improves **both** metrics at λ = 0.1 — it acts as a
regulariser, which is the published behaviour. Training labels measure
4.1e-5 K residual, confirming the data pipeline now converges.

Honest note: at λ = 0.1 on only 60 samples the physics term *hurt* (RMSE
2.604 → 2.605 → worse), a gradient-imbalance pathology. The benefit above needs
the larger sample count.

## 4. What is still not claimed

* **No POD / reduced-order model.** Still not implemented. The reference solver
  makes one possible (snapshot matrix → SVD → modal projection) but it does not
  exist.
* **No Ansys or Cadence correlation.** The reference is an independently-verified
  in-house FVM solver, not a commercial tool. The correct phrase is
  *"correlated against a grid-converged finite-element reference"*, never
  *"Ansys-correlated"*. The hook that would supply vendor data exists and is
  tested (`integrations` → `cadence:celsius`), and is waiting on a licence.
* **No speedup claim.** Any surrogate-vs-solver ratio here is internal to this
  repository, at this mesh, on this hardware.

## 5. Related

* `reports/mesh_convergence_audit.json` — the measured convergence study.
* `reports/thermal_validation.json` — surrogate error at optimiser-selected designs.
* `reports/pareto_front_nsga2.json` — the multi-objective front and its hypervolume baseline.
* `reports/critical_review.md` — how these claims came to be audited.
