# 🔁 PhysicsNeMo: The Surrogate's First Foreign Reader

**Status**: ✅ **Measured** (2026-10-31) · 14 tests, all passing
**Code**: `physics_accelerated/src/physicsnemo_bridge.py`, `tests/physics/test_physicsnemo_interop.py`
**Reproduce** (PhysicsNeMo is an optional dependency; see §7):

```bash
pip install nvidia-physicsnemo onnx onnxruntime
python -m unittest tests.physics.test_physicsnemo_interop -v
```

---

## 1. Why the surrogate needed this and the file formats already had it

`requirements.txt` states the rule for the interchange layer plainly: a
round-trip through our own writer and our own reader proves only that the two
agree, so every emitted format is handed to an implementation nobody here
wrote — gdstk for GDSII, klayout for LEF/DEF, scikit-rf for Touchstone,
liberty-parser for Liberty.

The surrogate never had that check. `physics_accelerated/src/train.py` contains
a hand-written FNO; our loop trains it, our scripts score it, and
[`rom_pinn_validation.md`](rom_pinn_validation.md) quotes errors measured
entirely inside that loop. A misreading of Li et al. 2020 in the spectral
convolution — a mode-truncation off-by-one, a wrong FFT normalisation, a grid
feature in the wrong order — would be invisible from inside, exactly the failure
mode the interchange tests exist to catch.

NVIDIA PhysicsNeMo (formerly Modulus; `pip install nvidia-physicsnemo`, v2.2.2)
ships `physicsnemo.models.fno.FNO`, a production implementation of the same
operator. It is the gdstk of our surrogate layer.

## 2. The architectures are not weight-compatible, and the reason is one layer

Mapping our checkpoint onto theirs is 1:1 for 22 of 24 tensors:

| ours | PhysicsNeMo |
| :--- | :--- |
| `conv{k}.weights{1,2}` (cfloat) | `spec_encoder.spconv_layers.{k}.weights{1,2}` (real, trailing complex axis) |
| `w{k}.{weight,bias}` | `spec_encoder.conv_layers.{k}.{weight,bias}` |
| `fc1.{weight,bias}` | `decoder_net.layers.0.linear.{weight,bias}` |
| `fc2.{weight,bias}` | `decoder_net.final_layer.linear.{weight,bias}` |
| `fc0.{weight,bias}` | `spec_encoder.lift_network.0.conv.{weight,bias}` — **substituted** |

The lift differs. PhysicsNeMo lifts the input with two 1×1 convolutions and a
nonlinearity between them (`in → latent/2 → latent`); our FNO2d, following the
original paper, lifts with a single linear map. A single linear map is not
expressible as that two-layer network, so **stock PhysicsNeMo cannot host our
weights** and the bridge substitutes that one layer. Everything downstream — the
spectral stack, the activation and residual ordering, the coordinate features,
the decoder — is PhysicsNeMo's code running our numbers.

Two further things had to match, and both are the kind of detail that would have
produced a confident wrong answer:

* **`padding=0`.** PhysicsNeMo zero-extends the domain by 8 cells before the FFT
  by default. We never trained that way. Leaving the default on would make the
  two disagree for a reason unrelated to either being wrong — and the fact that
  their default exists at all is the subject of §5.
* **Parameter counts differ by design.** Ours reports 534,442 parameters, theirs
  1,058,730. The difference is exactly the 524,288 complex spectral weights,
  which `numel()` counts once as cfloat and twice as real pairs. The test
  asserts that identity rather than the raw equality.

## 3. What the comparison found

Agreement is at float32 round-off, which is the answer that means our spectral
core is right.

| Input | Max \|ΔT\| | RMS ΔT |
| :--- | ---: | ---: |
| Random normal, 16×16 | 2.4e-05 K | 3.7e-06 K |
| **400 held-out power maps** | **7.4e-05 K** | 4.4e-06 K |
| Random, 32×32 (zero-shot resolution) | 2.4e-05 K | 2.9e-06 K |

Held-out accuracy is *the same number* to four decimals — field RMSE **0.6889 K**
and mean absolute peak error **1.0812 K** from both implementations, matching
the figure recorded in `train_metrics_mixedz2_lam0p1.json`.

The 32×32 row matters more than it looks. At 16×16 with 8 modes the upper and
lower mode blocks are exactly adjacent, and the two implementations fill them
differently — ours assigns into a zero spectrum, PhysicsNeMo accumulates with
`+`. Those are identical only while the blocks do not overlap. They agree at 16,
32 and 64.

One difference is not round-off: **below the mode count both implementations
crash** (8×8 with 8 modes raises in the einsum). Ours is not worse than theirs
here, and no grid we use is that small, but neither degrades gracefully.

### Decisions, not decimals

This project judges a surrogate by whether the design the search selects
survives the change, not by RMSE. Re-evaluating all 48 members of the published
NSGA-II front with both implementations:

| | result |
| :--- | :--- |
| Non-dominated set | **identical**, symmetric difference 0 of 48 |
| Rank order by logic peak Tj | **identical** |
| Coolest-logic pick | same member |
| Max \|Δ\| on logic and memory peak Tj | **1.5e-05 K**, against objective ranges of 71–190 °C |

Nothing moves. That is the intended result for a cross-implementation check: it
converts "our FNO is probably a correct FNO" into a measured claim.

## 4. The surrogate as a handoff artifact

The interchange layer emits 17 targets and the surrogate is not one of them. A
receiver gets our DEF, LEF, GDSII, SPEF, Liberty, Touchstone, IBIS and SPICE, but
cannot run the model that produced the thermal numbers. Two routes now exist,
both measured:

| Route | Size | Receiver needs | Verified by |
| :--- | ---: | :--- | :--- |
| `.mdlus` | 4.2 MB | PhysicsNeMo + `physicsnemo_bridge.py` | `Module.from_checkpoint` rebuilt it and reproduced the field **bit-exactly** (0.0 K) |
| **ONNX** | **307 KB** | nothing of ours | `onnx.checker` full_check passed; **onnxruntime executed it** to 5.9e-05 K |

`.mdlus` only works because the bridge is a `Module` *subclass*. PhysicsNeMo
checkpoints record constructor arguments and rebuild from them, so a stock `FNO`
with its lift swapped after construction fails its own reload on a shape
mismatch — the file describes a two-layer lift and the weights are for a
one-layer one. That failure was real before the subclass fixed it.

### ONNX needed a fix, and PhysicsNeMo's own exporter does not have it

Exporting any FNO fails at a single operator:

```
No ONNX function found for <OpOverload(op='aten.einsum', ...)>.
  Failure message: No decompositions registered for the complex-valued input
```

This is why PhysicsNeMo's FNO metadata declares `onnx_cpu=False`, and
`physicsnemo.deploy.onnx.export_to_onnx_stream` does not help — it calls
`torch.onnx.export` at opset 15 with no dynamic axes and hits the same wall.

The FFT is **not** the problem. `rfft2`, `irfft2` and `torch.complex` all export
cleanly at opset 20. Only the complex einsum does not, and
`RealSpectralConv2d` splits it into four real ones:

    (a + bi)(c + di) = (ac − bd) + (ad + bc)i

Parameter names and shapes are unchanged, so both layers load the same
checkpoint and agree to 3.8e-05 K. A second trap followed: writing the mode
blocks by slice assignment exports as a `ScatterND` whose indices are frozen at
the traced batch size, so the graph parses, passes the checker, runs at batch 1
and *fails at any other batch*. Zero-padding the blocks and adding — which is
what PhysicsNeMo's own layer does, for `torch.compile`'s sake rather than
ONNX's — fixes it. The test therefore runs onnxruntime at a batch size the
export never saw.

**Claim tier: T0.** Emitted, read back and executed by implementations nobody
here wrote. Unlike the vendor formats, this one has no T1/T2 ceiling waiting on
a licence — onnxruntime is the real consumer.

## 5. The critical half: what PhysicsNeMo recommends that we do not do

See [`physicsnemo_gap_review.md`](physicsnemo_gap_review.md). The short version
is that the single most substantive item is the padding default mentioned in §2:
our spectral convolution is circular over a die with adiabatic sides, and that
is measurable in kelvin, not in principle.

## 6. What this does not establish

* **Nothing about model-form error.** Both implementations solve the same
  equations on the same 5-layer, 16×16 voxel stack. Agreeing to 1e-05 K says
  the operator is implemented correctly, not that the operator describes the
  package. The tens-of-°C estimate in
  [`fidelity_integration.md`](fidelity_integration.md) §2 is untouched.
* **Nothing about training.** The comparison transplants our trained weights.
  PhysicsNeMo's training recipe is a separate question, and §5 is where it is
  asked.
* **Nothing about GPUs.** Everything here ran CPU-only on macOS/arm64 with
  Python 3.14. PhysicsNeMo installs and its FNO runs without CUDA; the CUDA
  extras (`[cu12]`/`[cu13]`) were never installed. Wall clock on 400 maps:
  ours 118 ms, theirs 134 ms — a statement about two CPU implementations of a
  534k-parameter model, and no basis for any speed claim.

## 7. Dependency position

PhysicsNeMo is **not** in `requirements.txt` and is not installed in the project
venv. It was verified in an isolated virtualenv; in the project venv all 14
tests skip with a loud reason, in the same idiom as
`tests/integrations/test_external_parsers.py`. The full physics suite is
unaffected: 149 tests, OK.

The reason for holding off is specific rather than squeamish. PhysicsNeMo pulls
roughly twenty packages including `torchvision`, `warp-lang`, `zarr`, `s3fs` and
`timm`, and `torchvision` constrains the torch version. This repository's
published physics numbers were measured against torch 2.10.0 in that venv, and
a resolver that quietly moves torch underneath them invalidates a measurement
record. Installing it is a one-line decision, but it belongs to whoever owns
those numbers.

The ONNX half has no such problem: `export_onnx` needs torch and `onnx`, not
PhysicsNeMo.
