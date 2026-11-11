# 🔍 What PhysicsNeMo Recommends That We Do Not Do

**Status**: ✅ **Reviewed, one defect measured** (2026-10-31)
**Companion to**: [`physicsnemo_interop.md`](physicsnemo_interop.md) (the bridge and its tests)
**Code**: `physics_accelerated/src/boundary_artifact.py` → [`boundary_artifact.json`](boundary_artifact.json)
**Reproduce**:

```bash
python physics_accelerated/src/boundary_artifact.py
```

---

## 0. The finding in one paragraph

PhysicsNeMo's FNO zero-pads the domain before the FFT by default. Ours has no
padding at all. A spectral convolution is *circular*, so without padding column
0 of the die is adjacent to column 15 — and our reference model has adiabatic
sides, which is the opposite of periodic. This is not a stylistic difference:
with a hot macro placed against the die edge, the surrogate puts **+13.6 K on
the opposite edge of an 18 mm die that the reference solver does not**. The
same effect is visible in-distribution as a +0.067 K/W coupling between edge
error and power on the *opposite* edge, which survives controlling for total
map power. Everything else PhysicsNeMo recommends is either a convenience at
our scale, or — in one case — something we should decline.

The irony is that both conclusions have the same root. PhysicsNeMo assumes
periodicity in two places. In the FNO it compensates for it by default and we
do not. In `PhysicsInformer` it does not compensate at all, and **we** do
(§4.1).

---

## 1. The defect: no domain padding, non-periodic domain

### 1.1 Where the error lives

Held-out error on the 400-map test set, by distance from the nearest die edge:

| Ring (0 = touching the edge) | cells/map | mean \|err\| | bias |
| ---: | ---: | ---: | ---: |
| **0** | 60 | **0.5290 K** | −0.033 K |
| 1 | 52 | 0.3896 K | −0.096 K |
| 3 | 36 | 0.3006 K | −0.071 K |
| 5 | 20 | 0.2475 K | −0.089 K |
| 7 (core) | 4 | 0.2252 K | −0.085 K |

The outer ring carries **2.35×** the error of the core. The bias is flat across
rings, so this is scatter rather than an offset — the edge is where the model
is *unreliable*, not where it is shifted.

### 1.2 The mechanism, isolated

One 2×2 logic macro carrying the full 45 W logic budget, walked in from the
edge. Power and concentration are held constant and only the position changes,
so extrapolation cannot explain a spike at one position. The far edge is the
column opposite the macro:

| macro at x | reference far edge | surrogate far edge | **Δ** | ref peak |
| ---: | ---: | ---: | ---: | ---: |
| **0 (on the edge)** | 26.16 °C | 39.76 °C | **+13.60 K** | 231.94 °C |
| 1 | 26.35 °C | 27.11 °C | +0.76 K | 190.44 °C |
| 2 | 26.71 °C | 29.00 °C | +2.29 K | 176.06 °C |
| 4 | 28.12 °C | 29.10 °C | +0.98 K | 167.39 °C |
| 7 (centred) | 33.86 °C | 34.16 °C | +0.30 K | 165.39 °C |

The reference says the far edge sits at ambient — with adiabatic sides the heat
leaves vertically, 18 mm away. The surrogate invents a 14 °C rise there. And it
simultaneously **under**-predicts the peak (223.9 vs 231.9 °C): energy leaves
the hotspot and reappears on the far side, which is what a wrap looks like,
not what generic inaccuracy looks like.

Moving the macro one cell inward collapses the effect to +0.76 K. The spike
belongs to the boundary, not to the power level.

### 1.3 In-distribution, with the obvious confound removed

A map with a lot of edge power is also a hotter map, and hotter maps have bigger
errors everywhere — that alone would manufacture an "antipodal" correlation. So
the coupling is fitted with controls:

| regression of edge error on … | slope |
| :--- | ---: |
| opposite-edge power (simple, r = +0.357) | **+0.0655 K/W** |
| …controlling for total map power | **+0.0678 K/W** |
| …controlling for total power *and* same-edge power | **+0.0667 K/W** |
| total map power, as a coefficient in that fit | −0.0053 K/W |

The coupling is unchanged by the controls, and opposite-edge power is only
weakly correlated with total power (r = 0.12). Earlier checks pointed the same
way: same-edge power gives a *negative* slope (−0.018 K/W), and an interior
column's error against its own power gives essentially zero (r = −0.006).
The coupling is specific to the opposite edge, which is the only pair of
locations a circular convolution makes adjacent.

### 1.4 How much does it matter today — honestly, not much, yet

Of the 48 published front members, **0 place a logic sub-macro on a die edge**
(coordinates run 2…12 of a possible 0…14) and 11 put the memory block against
one. The memory block spreads 15 W over 4×4 cells, so it is nowhere near the
probe's intensity. **The published designs are not materially wrong because of
this.**

The exposure is in the search, not the front. NSGA-II explores edge placements —
spreading macros is how it buys thermal headroom — and the surrogate makes
edge-adjacent designs look wrong in both directions at once. The
[trust guard](multiobjective_search.md#6-the-trust-guard) re-solves what the
search *selects*; it never sees what the search discarded on the way there. A
candidate rejected for a phantom +13 K is invisible to every check this
repository has.

### 1.5 What padding actually buys — measured, and not a clean win

PhysicsNeMo's FNO trained on our z-refined mixed training set, 40 epochs, plain
MSE, identical seed and optimiser, `padding=0` vs their default `padding=8`.
Both arms use *their* model, so padding is the only variable
(`physics_accelerated/src/padding_ablation.py` →
[`padding_ablation.json`](padding_ablation.json)):

| | padding=0 | padding=8 |
| :--- | ---: | ---: |
| Held-out field RMSE | 0.6328 K | **0.5514 K** (−13%) |
| Mean abs peak error | **0.9778 K** | 1.2042 K (+23%) |
| Outer-ring / core error | 1.95× | **1.31×** |
| Antipodal slope | +0.0557 K/W | +0.0740 K/W |
| Training time | 183 s | 265 s (+45%) |

Padding does what it claims where it claims it: the boundary error
concentration drops from 1.95× to 1.31×, and field RMSE improves 13%. But
**peak error gets 23% worse**, and the antipodal coupling does not improve at
this seed. Peak error is the statistic the search actually consumes.

This is one seed and one architecture, and the peak and antipodal numbers are
tail statistics that one seed cannot resolve. The honest conclusion is that
padding is **worth a multi-seed trial with the §1.2 probe as the acceptance
test**, not a drop-in adoption. Turning it on and quoting the 13% RMSE
improvement would be exactly the kind of decimal this project has committed to
not reporting as progress.

Cheaper alternatives exist and should be in the same trial: training with
macros deliberately placed on edges (the distribution currently under-samples
them), or adding the boundary distance as an input channel.

---

## 2. Worth adopting, in rough order of decision impact

### 2.1 Mesh-based geometry — the only item that touches model-form error

[`fidelity_integration.md`](fidelity_integration.md) §2 names the binding
limitation: 5 layers of uniform *k* with rectangular regions, finest cell
562 µm, against a real stack of TSVs, µbumps, BEOL, lid and TIM. No amount of
refining a uniform voxel grid represents a TSV array, so none of our
grid-convergence work can reach it. PhysicsNeMo ships `physicsnemo.mesh`
(geometry, boundaries, calculus, neighbours) and mesh-native operators —
MeshGraphNet, DoMINO, Transolver, FIGConvNet — built for exactly this.

This is the expensive item and the only one on the list that could move the
unmeasured tens-of-°C model-form error rather than the measured sub-kelvin
numerical one. It is a project, not a patch.

### 2.2 The active-learning loop we are already running by hand

`physicsnemo.active_learning` formalises train → **query** (which samples are
most informative) → **label** (run the expensive solver) → **metrology** (criteria
beyond validation loss that decide whether the surrogate can be trusted inside a
loop). That is a precise description of what
[`surrogate_retraining.md`](surrogate_retraining.md) did once, by hand, and of
what the trust guard does continuously — our guard *is* a metrology phase that
does not know it is one.

We did one round and got the error at optimiser-selected designs from 14.21 K to
1.33 K. Nobody has asked what a second round buys. The scaffolding is the cheap
part; the honest reason to care is that §1.4's blind spot — candidates discarded
during the search — is exactly what a query strategy is for.

### 2.3 Checkpoints that describe themselves

`pareto_search.load_surrogate` reads the channel count out of `fc2.bias` because
nothing in our checkpoint records it, and its docstring defends this as making a
mismatch impossible. It is a symptom: a bare `state_dict` records no
architecture, no dataset, no normalisation, no version. The z-refined model and
the 5-channel model are distinguishable only by a filename convention.

PhysicsNeMo's `.mdlus` stores constructor arguments and rebuilds from them, which
is why `Module.from_checkpoint` works at all
([`physicsnemo_interop.md`](physicsnemo_interop.md) §4). We now have that path.
The norm stats still travel in a separate `.pt` file and should be inside the
checkpoint.

### 2.4 Spectral validation

`physicsnemo.metrics.general.power_spectrum` exists because an operator's
characteristic failure is spectral: it smooths high-wavenumber content while
looking fine pointwise. We validate with RMSE, peak error and the heat residual
— all pointwise.

This is decision-relevant here specifically.
[`power_map_reality.md`](power_map_reality.md) found real designs put half their
power in 15–19% of the area, and [`submodel.md`](submodel.md) found that
rearranging a macro's watts *inside its own footprint* moves the peak +36 °C.
Both are statements about high-wavenumber content. A surrogate that quietly
attenuates it would pass every metric we currently compute.

### 2.5 Calibrated uncertainty

`metrics.general` ships `calibration.py`, `crps.py` and `ensemble_metrics.py`,
and the `uq-extras` bring gpytorch. Our trust guard flags extrapolation by
distance from the training distribution and re-solves — a binary, geometric
test. CRPS and a calibration curve would turn "the surrogate may not know" into
a number, which is the difference between a guard that fires and a guard whose
false-negative rate is known.

---

## 3. Deliberately not adopted

Each of these is a real PhysicsNeMo practice, dismissed with a reason rather
than overlooked.

| Practice | Why not |
| :--- | :--- |
| **Per-channel normalisation** | Measured: per-layer label σ spans 14.88–15.65 K against a global 15.49 K — 0.96× to 1.01×. The stack is near-isothermal in z. Buys nothing. |
| **DistributedManager, multi-GPU, AMP, CUDA graphs, transformer-engine** | 534k parameters; 40 epochs over 3,000 samples takes 183 s on a laptop CPU. The bottleneck is label generation, not training. |
| **Hydra configs, LaunchLogger, MLflow/W&B** | Genuine practice, but `train_metrics_*.json` plus the dataset manifest already pin seed, dataset, hyperparameters and every split metric. Adoption is churn with no decision changed. |
| **Datapipes, zarr/HDF5 pipelines** | The entire training set is 30 MB and fits in RAM. |
| **`physicsnemo.deploy.onnx`** | Tried. `export_to_onnx_stream` calls `torch.onnx.export` at opset 15 with no dynamic axes; it fails on the same complex einsum and would give a batch-1-only graph. Our `export_onnx` is strictly better for this model. |

## 4. Declined on physics grounds

### 4.1 Do not replace our heat residual with `PhysicsInformer`

The obvious adoption — swap our hand-written `HeatEquationResidual` for
PhysicsNeMo's `PhysicsInformer` and get symbolic PDE residuals — is the one
thing here that would be a regression.

NVIDIA/physicsnemo issue **#2001** (open) reports that
`GradientsFiniteDifference` and `GradientsSpectral`, and therefore
`PhysicsInformer`, compute derivatives with `torch.roll` unconditionally: they
assume the domain wraps, with no parameter to say otherwise and no warning when
it does not. Their own tests exclude boundary cells before validating.

Our residual pads with `mode="replicate"` precisely because the sides are
adiabatic, and `from_solver` builds it from the same solver that defines the
discretisation, so the two cannot drift. For our boundary conditions ours is
the more correct implementation, and the label residual it reports —
3.7e-06 K on the training set — is evidence it is right.

This is the same periodicity assumption as §1, with the opposite conclusion.
In the FNO, PhysicsNeMo compensates and we do not. In the residual, we
compensate and PhysicsNeMo does not.

---

## 5. Recommended order

1. **Multi-seed padding trial** with the §1.2 edge probe as the acceptance
   test, alongside the two cheaper alternatives (edge-weighted training
   distribution, boundary-distance input channel). Decides a measured defect;
   roughly an hour of compute. *(Do not adopt padding on the §1.5 single-seed
   result.)*
2. **Spectral validation** of the existing surrogate — no training, and it
   either clears §2.4 or finds something.
3. **Fold the norm stats and architecture into the checkpoint** (§2.3).
4. **Second active-learning round** (§2.2), with a query strategy aimed at the
   edge placements of §1.4.
5. **Mesh-native geometry** (§2.1) — the only item that addresses model-form
   error, and the only one that is a project rather than a task.

Items 1–4 need no licence, which keeps them consistent with
[`fidelity_integration.md`](fidelity_integration.md) §10: the measured evidence
still says the binding error is ours rather than the vendor's.
