"""Carry our trained FNO surrogate into NVIDIA PhysicsNeMo, and check it survives.

Why this exists. `requirements.txt` already states the rule for the file formats:
a round-trip through our own writer and our own reader proves only that the two
agree, so every emitted format is read back by an implementation nobody here
wrote -- gdstk for GDSII, klayout for LEF/DEF, scikit-rf for Touchstone. The
surrogate has had no such check. `physics_accelerated/src/train.py` contains a
hand-written FNO, trained by our own loop, validated by our own scripts, and
`reports/rom_pinn_validation.md` quotes errors measured entirely inside that
loop. If our spectral convolution misreads the FNO of Li et al. 2020, nothing in
this repository would notice.

PhysicsNeMo (NVIDIA Modulus, renamed) ships `physicsnemo.models.fno.FNO`: an
independent implementation of the same operator, by the people who productised
it. This module maps our weights onto theirs and runs both on the same inputs.
Agreement to float precision means our spectral core, mode truncation, grid
features and residual structure match a reference implementation. Disagreement
would be a defect in the surrogate, not in the comparison.

**One architectural difference is real and is not papered over.** PhysicsNeMo
lifts the input with two 1x1 convolutions and a nonlinearity between them
(`in -> latent/2 -> latent`); our FNO2d, following the original paper, lifts
with a single linear map (`in -> latent`). A single linear map is not expressible
as that two-layer network, so stock PhysicsNeMo cannot host our weights. The
bridge therefore substitutes *one* layer -- the lift -- and leaves PhysicsNeMo's
own code to do the spectral stack, the activation/residual ordering, the
coordinate features and the decoder. That is the part worth testing, and it is
tested with their code rather than ours.

Everything else maps exactly:

    ours                        PhysicsNeMo
    fc0.{weight,bias}           spec_encoder.lift_network.0.conv.{weight,bias}   [substituted layer]
    conv{k}.weights{1,2}        spec_encoder.spconv_layers.{k}.weights{1,2}      [cfloat -> (...,2) real]
    w{k}.{weight,bias}          spec_encoder.conv_layers.{k}.{weight,bias}
    fc1.{weight,bias}           decoder_net.layers.0.linear.{weight,bias}
    fc2.{weight,bias}           decoder_net.final_layer.linear.{weight,bias}

`padding=0` matters: PhysicsNeMo pads the domain by 8 cells before the FFT by
default, which is the usual trick for a non-periodic domain and is *not* what we
trained. Leaving the default on would make the two disagree for a reason that
has nothing to do with either implementation being wrong.
"""
from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

from physicsnemo.models.fno import FNO
from physicsnemo.nn.module.fully_connected_layers import Conv2dFCLayer

# Our training script's hyperparameters, from pareto_search.load_surrogate.
MODES = 8
WIDTH = 32
FNO_LAYERS = 4
DECODER_WIDTH = 128


def _single_layer_lift(encoder) -> None:
    """Replace PhysicsNeMo's two-layer lift with the paper's single linear map.

    Called after construction so the rest of the encoder is PhysicsNeMo's,
    untouched. `encoder.in_channels` already includes the +2 coordinate
    features.
    """
    lift = nn.Sequential()
    lift.append(Conv2dFCLayer(encoder.in_channels, encoder.fno_width))
    encoder.lift_network = lift


class ThermalFNO(FNO):
    """Our thermal surrogate, as a PhysicsNeMo `Module`.

    A subclass rather than a configured `FNO` because of the lift. PhysicsNeMo
    checkpoints record the constructor arguments and rebuild the model from
    them, so a stock `FNO` with its lift swapped out after construction cannot
    be reconstructed from its own `.mdlus` file -- the file describes a
    two-layer lift and the weights are for a one-layer one, and the reload
    fails on a shape mismatch. Putting the substitution inside `__init__` means
    the architecture is a property of the class, and `Module.from_checkpoint`
    rebuilds it correctly.

    The cost is that the `.mdlus` file names this class, so a receiver needs
    this module importable. That is one file, not the repository, but it is a
    dependency -- `export_onnx` exists for receivers who want none.
    """

    def __init__(self, channels: int) -> None:
        super().__init__(
            in_channels=channels,
            out_channels=channels,
            decoder_layers=1,
            decoder_layer_size=DECODER_WIDTH,
            decoder_activation_fn="gelu",
            dimension=2,
            latent_channels=WIDTH,
            num_fno_layers=FNO_LAYERS,
            num_fno_modes=MODES,
            padding=0,             # we never trained with domain padding
            activation_fn="gelu",
            coord_features=True,   # grid features, as ours appends
        )
        _single_layer_lift(self.spec_encoder)


class RealSpectralConv2d(nn.Module):
    """PhysicsNeMo's `SpectralConv2d`, with the complex multiply written out in
    real arithmetic.

    Purely an export shim. `torch.onnx.export` refuses the real layer at
    `aten.einsum` -- "No decompositions registered for the complex-valued
    input" -- which is why PhysicsNeMo's own FNO metadata declares
    `onnx_cpu=False`. The FFT is *not* the problem: `rfft2`/`irfft2` and
    `torch.complex` all export cleanly at opset 20. Only the complex einsum
    does not, and splitting it into four real einsums

        (a + bi)(c + di) = (ac - bd) + (ad + bc)i

    removes the single unsupported op. Parameter names and shapes are
    unchanged, so this and the real layer load the same checkpoint and must
    agree to float round-off -- which is the assertion the test makes.
    """

    def __init__(self, in_channels: int, out_channels: int,
                 modes1: int, modes2: int) -> None:
        super().__init__()
        self.modes1, self.modes2 = modes1, modes2
        shape = (in_channels, out_channels, modes1, modes2, 2)
        self.weights1 = nn.Parameter(torch.zeros(shape))
        self.weights2 = nn.Parameter(torch.zeros(shape))

    @staticmethod
    def _mul(xr: torch.Tensor, xi: torch.Tensor, w: torch.Tensor):
        wr, wi = w[..., 0], w[..., 1]
        return (torch.einsum("bixy,ioxy->boxy", xr, wr)
                - torch.einsum("bixy,ioxy->boxy", xi, wi),
                torch.einsum("bixy,ioxy->boxy", xr, wi)
                + torch.einsum("bixy,ioxy->boxy", xi, wr))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        ft = torch.fft.rfft2(x)
        xr, xi = ft.real, ft.imag
        m1, m2 = self.modes1, self.modes2
        h, w = xr.size(-2), xr.size(-1)
        ar, ai = self._mul(xr[:, :, :m1, :m2], xi[:, :, :m1, :m2], self.weights1)
        br, bi = self._mul(xr[:, :, -m1:, :m2], xi[:, :, -m1:, :m2], self.weights2)
        # Zero-pad the two mode blocks back up to full spectrum and add, rather
        # than assigning into a zero tensor. PhysicsNeMo's own layer does this
        # for torch.compile's sake; here it is for ONNX's -- slice assignment
        # exports as a ScatterND whose indices are fixed at the traced batch
        # size, so the graph runs at batch 1 and fails at any other.
        lo_r = F.pad(ar, (0, w - m2, 0, h - m1))
        lo_i = F.pad(ai, (0, w - m2, 0, h - m1))
        hi_r = F.pad(br, (0, w - m2, h - m1, 0))
        hi_i = F.pad(bi, (0, w - m2, h - m1, 0))
        return torch.fft.irfft2(torch.complex(lo_r + hi_r, lo_i + hi_i),
                                s=(x.size(-2), x.size(-1)))


class ThermalFNOExportable(ThermalFNO):
    """`ThermalFNO` with ONNX-exportable spectral layers. Same state_dict."""

    def __init__(self, channels: int) -> None:
        super().__init__(channels)
        for k, old in enumerate(self.spec_encoder.spconv_layers):
            self.spec_encoder.spconv_layers[k] = RealSpectralConv2d(
                WIDTH, WIDTH, old.modes1, old.modes2)


def build(channels: int, exportable: bool = False) -> ThermalFNO:
    """A PhysicsNeMo FNO shaped like ours: `channels` power maps in, `channels`
    temperature fields out."""
    return ThermalFNOExportable(channels) if exportable else ThermalFNO(channels)


def translate(state: dict) -> dict:
    """Our FNO2d state_dict -> a PhysicsNeMo FNO state_dict."""
    out = {
        "spec_encoder.lift_network.0.conv.weight": state["fc0.weight"][:, :, None, None],
        "spec_encoder.lift_network.0.conv.bias": state["fc0.bias"],
        "decoder_net.layers.0.linear.weight": state["fc1.weight"],
        "decoder_net.layers.0.linear.bias": state["fc1.bias"],
        "decoder_net.final_layer.linear.weight": state["fc2.weight"],
        "decoder_net.final_layer.linear.bias": state["fc2.bias"],
    }
    for k in range(FNO_LAYERS):
        for w in ("weights1", "weights2"):
            # Their spectral weights are real with a trailing complex axis,
            # read through view_as_complex; ours are native cfloat.
            out[f"spec_encoder.spconv_layers.{k}.{w}"] = \
                torch.view_as_real(state[f"conv{k}.{w}"])
        out[f"spec_encoder.conv_layers.{k}.weight"] = state[f"w{k}.weight"]
        out[f"spec_encoder.conv_layers.{k}.bias"] = state[f"w{k}.bias"]
    return out


def load(model_path: str | Path, channels: int | None = None,
         exportable: bool = False) -> ThermalFNO:
    """Load one of our checkpoints as a PhysicsNeMo model.

    Channel count comes from the weights, not the caller, for the same reason
    `pareto_search.load_surrogate` does it that way: a z-refined surrogate has
    two channels per physical layer, and pairing a model with the wrong count
    should be impossible rather than a shape error deep inside a search.
    """
    state = torch.load(model_path, map_location="cpu", weights_only=True)
    channels = channels or state["fc2.bias"].numel()
    model = build(channels, exportable=exportable)
    missing, unexpected = model.load_state_dict(translate(state), strict=True)
    assert not missing and not unexpected
    model.eval()
    return model


def export_onnx(model_path: str | Path, onnx_path: str | Path,
                grid: int = 16, opset: int = 20) -> Path:
    """Write the surrogate as ONNX: the handoff artifact that needs none of our
    code, and no PhysicsNeMo, at the far end.

    Uses the real-arithmetic spectral layers, because the complex einsum has no
    ONNX decomposition. `grid` is only the shape traced through; the batch axis
    is dynamic and an FNO is resolution-agnostic, but a receiver who wants a
    different grid should re-export rather than assume.
    """
    model = load(model_path, exportable=True)
    channels = model.in_channels
    torch.onnx.export(
        model, (torch.zeros(1, channels, grid, grid),), str(onnx_path),
        input_names=["power_w_per_cell"], output_names=["temperature_norm"],
        dynamic_axes={"power_w_per_cell": {0: "batch"},
                      "temperature_norm": {0: "batch"}},
        opset_version=opset,
    )
    return Path(onnx_path)
