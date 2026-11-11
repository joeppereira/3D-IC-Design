# 📦 The Surrogate as a Product

**Status**: ✅ **Built and verified** (2026-11-11) · 15 tests, `neutral:surrogate` emitting
**Code**: `physics_accelerated/src/surrogate_export.py`, `integrations/interchange/surrogate_io.py`
**Reproduce**:

```bash
pip install onnx onnxscript onnxruntime
python -m integrations.cli emit --target neutral:surrogate
python -m unittest tests.physics.test_surrogate_export -v
```

---

## 1. What was actually unfinished

The question "what is left to finish?" has no answer from inside this
repository — the surrogate is trained, grid-converged, reference-checked,
cross-validated against a foreign FNO implementation, and feeding a search whose
front is re-solved by a trust guard. By its own standards it is done.

It had an answer from outside. Two sibling projects were independently standing
up physics surrogate services:

| Project | What it has | Evidence |
| :--- | :--- | :--- |
| `sec-soc` Project 4 — "central physics AI service" | `ThermalWarpageOperator`, a 16×16 power-grid → temperature operator with **randomly initialised weights** | its own comment: *"weights are random but seeded — Phase 1 mock"* |
| `node-migration` — migration verification loop | `parasitic_surrogate`, `litho_surrogate` | each returns `"placeholder": True, # mock — no trained surrogate` |

`sec-soc`'s mock takes a 16×16 power grid and returns `peak_delta_c` — the same
shape, the same grid, and the same quantity as the trained operator in this
repository. A real surrogate existed and there was **no way to get it out.**

That is the gap: the surrogate was finished as a *model* and unfinished as a
*product*. Sixteen of the seventeen emit targets hand over geometry and
electrical description — DEF, LEF, GDSII, SPEF, Liberty, Touchstone, IBIS,
SPICE — so a receiver can rebuild the stack but cannot run the model that
produced the thermal numbers those artifacts are annotated with.

## 2. Why handing over the `.pt` would not have been enough

A consumer given `fno_model_mixedz2_lam0p1.pt` has a bag of tensors and four
ways to be silently wrong, none of which raises an error:

1. **Units.** The model wants absolute **watts per cell**, not W/m² and not
   W/mm². Feeding density produces a plausible, wrong field.
2. **Normalisation.** The output is normalised. `T_degC = y * std + mean`, and
   `std`/`mean` live in a *different file* (`norm_stats_*.pt`).
3. **Channel layout.** This is a z-refined model: **10 channels = 5 physical
   layers × 2 z-cells**, and a layer's watts are split evenly across its
   sub-cells. A consumer assuming one channel per layer reads the wrong die.
4. **Peak recipe.** Logic peak Tj is `amax` over the *logic-die channels*, not
   over all channels — the latter gives the hottest cell anywhere in the stack.

So the artifact is a bundle: an ONNX graph **plus a contract** that states each
of those, the measured error band, and the known defects.

## 3. What is emitted

`neutral:surrogate`, T0, fidelity `SURROGATE`:

| File | |
| :--- | :--- |
| `surrogate.onnx` | 181 KB, opset 20, dynamic batch |
| `surrogate_contract.json` | units, channel layout, de-normalisation, error band, defects, provenance |
| `surrogate.onnx.provenance.json` | sidecar — ONNX is binary and cannot carry a comment header |

The contract declares the error band as **0.6889 K held-out field RMSE**,
**1.0812 K mean absolute peak error**, **1.33 K at optimiser-selected designs**,
and states its use: *for RANKING designs, not absolute temperatures*. That
matches `node-migration`'s own guardrail — *"surrogates rank and propose;
certified sign-off tools decide"* — which is the same rule this repo enforces
through the T0–T3 ladder.

It also declares **two known defects**, because a consumer running the model
inherits them:

- the spectral convolution is circular while the die's sides are adiabatic —
  **+13.6 K** of phantom temperature opposite an edge-adjacent macro
  ([`physicsnemo_gap_review.md`](physicsnemo_gap_review.md) §1);
- trained on uniform 1.125 mm macro blocks, while real designs concentrate half
  their power in 15–19% of the area — worth **+17…+21 °C**
  ([`power_map_reality.md`](power_map_reality.md)).

A bundle that shipped the error band but hid the defects would be worse than no
bundle: it would make a known-unreliable prediction look quantified.

## 4. No PhysicsNeMo in the shipping path

`surrogate_export.py` imports no PhysicsNeMo. That is deliberate and it was a
correction, not a design: `physicsnemo_bridge.export_onnx` could not be the
export path, because the bridge imports PhysicsNeMo at module scope — so
producing the artifact would have required a twenty-package optional dependency.
`requirements.txt` claimed otherwise and was wrong twice over; `onnxscript` is
also required, since torch's exporter imports it.

The split is now the right one:

- **PhysicsNeMo** — the *verification* path. It checks our operator against an
  implementation nobody here wrote ([`physicsnemo_interop.md`](physicsnemo_interop.md)).
- **`surrogate_export`** — the *shipping* path. torch + onnx + onnxscript.

## 5. Two shape traps, both caught by executing the graph

Neither is visible to a parser, and both produce a graph that passes
`onnx.checker` and runs correctly at the traced batch size while failing at
every other one:

1. **`ScatterND`** — writing the spectral mode blocks by slice assignment bakes
   the batch into the scatter indices. Fixed by zero-padding the blocks and
   adding, which is what PhysicsNeMo's own layer does for `torch.compile`.
2. **`Reshape`** — `nn.Linear` applied to a permuted 4-D tensor folds the traced
   batch into a reshape. Fixed by using 1×1 convolutions throughout:
   mathematically the same map over the channel axis, shape-agnostic.

A third, cosmetic: `dynamic_axes` leaves the *output* shape pinned at the traced
batch under torch's dynamo exporter, so the graph computes correctly while
advertising `{1,…}`. `dynamic_shapes` fixes the metadata.

**The rule this confirms**: parsing proves well-formedness; only *running* the
graph, at a batch size the export never saw, proves a consumer gets our model.
`surrogate_io.validate()` therefore executes at batch 3 and checks the contract
recipe yields a plausible temperature.

## 6. What this repo should not supply

`node-migration` needs a **parasitic** ranking surrogate and a **litho** hotspot
surrogate. Neither is this repository's:

- **Parasitics** — there is a two-scale analytic RC model and a SPEF emitter,
  but no *trained* parasitic surrogate, and the model form is calibrate-not-
  substitute ([`fidelity_integration.md`](fidelity_integration.md) §4).
- **Lithography** — nothing here does litho. No model, no data, no validation
  path. `eda-kit` has the DRC/LVS/PDK machinery; that is where it belongs.

Shipping a thermal bundle and letting it be read as "the physics service" would
recreate exactly the problem this report closes, one level up.

## 7. What is still unfinished

| | |
| :--- | :--- |
| **The edge wrap** | measured, declared in the contract, **not fixed**. Needs the multi-seed padding trial of `physicsnemo_gap_review.md` §1.5. |
| **Per-instance `dtemp`** | `write_primesim` emits one global `.temp`. ngspice honours `dtemp`, so it is T0-verifiable today. |
| **`physics_in_the_loop.md`** | the design record for the two-timescale loop and the fidelity router — still unwritten. |
| **T1/T2** | no licensed tool has opened any artifact. Unchanged, and not closable here. |
| **`verify` cross-consistency** | still 1 error — the 1 TB module with no memory die. A design-data decision. |
