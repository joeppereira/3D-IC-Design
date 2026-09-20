# 🧪 ROM & PINN: Status and Plan
**Status**: ⚠️ **NOT IMPLEMENTED — this document describes a target, not a measurement.**
**Last audited**: 2026-09-20

> An earlier version of this file presented a validation table against "Ansys Icepak
> (High-Fidelity Baseline)" reporting 104.2 °C vs 102.8 °C, an 8 hour → 15 ms solve
> time, and a "1.9M × speedup". No Icepak reference dataset, no POD implementation,
> and no physics-informed loss term exist in this repository. Those numbers were
> illustrative targets presented as results. They have been removed.

## 1. What actually exists today

| Component | Claimed previously | Actually in the repo |
| :--- | :--- | :--- |
| **Reduced-Order Model (POD)** | "10M-element FEA mesh reduced to 50 dominant thermal modes" | **Nothing.** No POD, no SVD, no modal decomposition anywhere in `physics_accelerated/` or `serdes_architect/`. |
| **FEA reference** | "Ansys Icepak high-fidelity baseline" | **No dataset.** `agent/industrial_ingestor.py` can parse an Icepak monitor-point CSV if one is supplied; `external_references/` is empty. |
| **PINN physics loss** | "L = L_data + λ·L_physics penalises violations of the heat equation" | **Plain MSE.** `physics_accelerated/src/train.py` uses `criterion` (MSE) with an optional hotspot weighting map. There is no residual term, no λ, no heat-equation constraint. |
| **Thermal surrogate** | — | **Real but modest.** A 2-D Fourier Neural Operator (`FNO2d`, spectral convolutions) trained on output from the repo's own finite-difference solver. |
| **Ground-truth solver** | — | **Real.** `serdes_architect/src/thermal/solver.py` — Jacobi iteration on a 16×16×5 voxel stack. |

## 2. What the surrogate is actually trained against

The FNO learns to reproduce **this repo's own Jacobi finite-difference solver**, not a
commercial FEA tool. Any accuracy figure derived from that comparison measures how well
the network mimics a coarse 16×16×5 internal solver — it says nothing about agreement
with Icepak, Celsius, or silicon.

Speedup figures are therefore also internal: a surrogate forward pass versus this repo's
own solver, at this repo's own mesh resolution.

## 3. What it would take to make the original claims true

1. **A reference dataset.** Run a parameter sweep in Icepak or Celsius and store the
   temperature fields. Without this there is no baseline to be accurate *against*.
2. **POD.** Assemble the snapshot matrix, take the SVD, retain the leading modes, and
   project the governing equations onto them. Roughly 200 lines, plus validation that
   the truncated basis reproduces held-out snapshots.
3. **A genuine PINN term.** Add the heat-equation residual to the loss:
   `L = L_data + λ‖∂T/∂t − α∇²T − q/(ρc)‖²`, computed via autograd on the network output.
   Report the residual magnitude, not a claim that it is zero.
4. **An honest error band.** Publish mean, p95 and max error against the reference, plus
   the conditions under which the surrogate degrades.

Step 1 is the blocker and it needs a licensed tool. Until it exists, the correct
description of the thermal path is *"an FNO surrogate of an internal finite-difference
solver"*.

## 4. Related

* `reports/eda_vendor_integration_spec.md` §3.1 — the Celsius hook that would supply the
  reference dataset, and the correlation machinery that would publish the error band.
* `python -m integrations.cli correlate --thermal <export>.csv` — computes ΔTj and the
  field RMS once a reference exists, and refuses to feed it back as calibration unless
  the data genuinely came from a third-party tool.
