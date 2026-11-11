"""The trained surrogate as an artifact someone else can run.

Everything else in this repository consumes the surrogate in place: import
`FNO2d`, `torch.load` a `.pt`, remember that the normalisation statistics live
in a *different* file, remember that a z-refined model has two channels per
physical layer, remember that the output is normalised. That is fine inside the
repo and useless outside it. A consumer who gets `fno_model_mixedz2_lam0p1.pt`
and nothing else has a bag of tensors and four chances to be silently wrong.

So this module writes the surrogate as a **self-describing bundle**: an ONNX
graph plus a JSON contract that states the input units, the channel layout, the
de-normalisation, the measured error band and the known defects. A consumer who
reads the contract cannot accidentally feed power *density* to a model trained
on watts per cell, or report normalised output as °C.

It deliberately does **not** import PhysicsNeMo. `physicsnemo_bridge` is the
*verification* path -- it checks our operator against a foreign implementation --
and making the shipping artifact depend on it would mean nobody can produce the
artifact without a 20-package optional dependency. (An earlier note in
`requirements.txt` claimed `export_onnx` needed only torch and onnx. It did not:
it lived in the bridge, which imports PhysicsNeMo at module scope. This module
is what that note described.)

    python physics_accelerated/src/surrogate_export.py --out results/handoff/surrogate

The ONNX trick is the same one the bridge documents: `torch.onnx.export` has no
decomposition for a complex-valued `einsum`, so the spectral multiply is written
out in real arithmetic. The FFT itself exports cleanly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from train import FNO2d                                        # noqa: E402

MODES, WIDTH, FNO_LAYERS, DECODER_WIDTH = 8, 32, 4, 128
DEFAULT_MODEL = REPO / "physics_accelerated/results/fno_model_mixedz2_lam0p1.pt"
DEFAULT_STATS = REPO / "physics_accelerated/results/norm_stats_mixedz2_lam0p1.pt"
DEFAULT_CONFIG = REPO / "physics_accelerated/results/golden_config.json"


class RealSpectralConv2d(nn.Module):
    """`train.SpectralConv2d` with the complex multiply in real arithmetic.

    Same mathematics, same mode truncation, ONNX-exportable. Weights are stored
    real with a trailing size-2 axis so a cfloat checkpoint maps onto them with
    `torch.view_as_real`.

    Two details are not cosmetic. The mode blocks are zero-padded and added
    rather than assigned into a zero spectrum, because slice assignment exports
    as a `ScatterND` whose indices freeze at the traced batch size -- the graph
    then runs at batch 1 and fails at every other batch while still passing the
    ONNX checker. And `(a+bi)(c+di) = (ac-bd) + (ad+bc)i` is four real einsums,
    which is the one op `torch.onnx.export` refuses in complex form.
    """

    def __init__(self, in_ch: int, out_ch: int, modes1: int, modes2: int) -> None:
        super().__init__()
        self.modes1, self.modes2 = modes1, modes2
        shape = (in_ch, out_ch, modes1, modes2, 2)
        self.weights1 = nn.Parameter(torch.zeros(shape))
        self.weights2 = nn.Parameter(torch.zeros(shape))

    @staticmethod
    def _mul(xr, xi, w):
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
        zr = F.pad(ar, (0, w - m2, 0, h - m1)) + F.pad(br, (0, w - m2, h - m1, 0))
        zi = F.pad(ai, (0, w - m2, 0, h - m1)) + F.pad(bi, (0, w - m2, h - m1, 0))
        return torch.fft.irfft2(torch.complex(zr, zi), s=(x.size(-2), x.size(-1)))


class ExportableFNO2d(nn.Module):
    """`train.FNO2d`, structurally identical, exportable.

    The forward pass must match `FNO2d` exactly -- same grid features on
    `linspace(0, 1)`, same activation on the first three spectral layers and
    none on the fourth, same decoder. `tests/physics/test_surrogate_export.py`
    asserts that rather than trusting this comment.
    """

    def __init__(self, channels: int) -> None:
        super().__init__()
        self.channels = channels
        # 1x1 convolutions, not Linear-on-permuted-tensor. Mathematically the
        # same map over the channel axis, but `nn.Linear` applied to a 4-D
        # tensor exports as a Reshape with the *traced* batch size folded into
        # it, so the graph passes the ONNX checker, runs at batch 1 and fails
        # at every other batch. That is the second shape trap in this export
        # after the spectral layer's ScatterND, and it has the same shape:
        # a graph that is wrong only off the traced path.
        self.fc0 = nn.Conv2d(channels + 2, WIDTH, 1)
        self.convs = nn.ModuleList(
            [RealSpectralConv2d(WIDTH, WIDTH, MODES, MODES)
             for _ in range(FNO_LAYERS)])
        self.ws = nn.ModuleList(
            [nn.Conv2d(WIDTH, WIDTH, 1) for _ in range(FNO_LAYERS)])
        self.fc1 = nn.Conv2d(WIDTH, DECODER_WIDTH, 1)
        self.fc2 = nn.Conv2d(DECODER_WIDTH, channels, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        nx, ny = x.shape[-2], x.shape[-1]
        gx = torch.linspace(0, 1, nx, dtype=x.dtype, device=x.device)
        gy = torch.linspace(0, 1, ny, dtype=x.dtype, device=x.device)
        gx = gx.reshape(1, 1, nx, 1).expand(x.shape[0], 1, nx, ny)
        gy = gy.reshape(1, 1, 1, ny).expand(x.shape[0], 1, nx, ny)
        x = torch.cat((x, gx, gy), dim=1)

        x = self.fc0(x)
        for i, (conv, w) in enumerate(zip(self.convs, self.ws)):
            x = conv(x) + w(x)
            if i < FNO_LAYERS - 1:
                x = F.gelu(x)
        return self.fc2(F.gelu(self.fc1(x)))

    def load_fno2d(self, state: dict) -> None:
        """Adopt a `train.FNO2d` checkpoint.

        Two conversions: cfloat spectral weights become real pairs, and the
        decoder's `Linear` weights gain two trailing singleton axes to become
        1x1 convolution kernels. Both are reshapes, not approximations.
        """
        own = {
            "fc0.weight": state["fc0.weight"][:, :, None, None],
            "fc0.bias": state["fc0.bias"],
            "fc1.weight": state["fc1.weight"][:, :, None, None],
            "fc1.bias": state["fc1.bias"],
            "fc2.weight": state["fc2.weight"][:, :, None, None],
            "fc2.bias": state["fc2.bias"],
        }
        for k in range(FNO_LAYERS):
            own[f"convs.{k}.weights1"] = torch.view_as_real(state[f"conv{k}.weights1"])
            own[f"convs.{k}.weights2"] = torch.view_as_real(state[f"conv{k}.weights2"])
            own[f"ws.{k}.weight"] = state[f"w{k}.weight"]
            own[f"ws.{k}.bias"] = state[f"w{k}.bias"]
        self.load_state_dict(own, strict=True)


def load(model_path: Path = DEFAULT_MODEL) -> ExportableFNO2d:
    state = torch.load(model_path, map_location="cpu", weights_only=True)
    model = ExportableFNO2d(state["fc2.bias"].numel())
    model.load_fno2d(state)
    model.eval()
    return model


def reference(model_path: Path = DEFAULT_MODEL) -> FNO2d:
    """The in-repo model, for equivalence checks."""
    state = torch.load(model_path, map_location="cpu", weights_only=True)
    m = FNO2d(modes1=MODES, modes2=MODES, width=WIDTH,
              layers=state["fc2.bias"].numel())
    m.load_state_dict(state)
    m.eval()
    return m


def contract(model_path: Path = DEFAULT_MODEL,
             stats_path: Path = DEFAULT_STATS,
             config_path: Path = DEFAULT_CONFIG) -> dict:
    """Everything a consumer must know to use the graph without being wrong.

    Each field exists because getting it wrong is silent. Feeding power density
    instead of watts per cell, forgetting the de-normalisation, or assuming one
    channel per physical layer all produce plausible numbers.
    """
    state = torch.load(model_path, map_location="cpu", weights_only=True)
    stats = torch.load(stats_path, map_location="cpu", weights_only=True)
    cfg = json.loads(config_path.read_text())
    vsp = cfg["voxel_stack_params"]
    channels = int(state["fc2.bias"].numel())
    layers = int(vsp["layers"])
    grid = int(vsp["grid_size"])
    per_layer = channels // layers
    die_mm = float(cfg["die_hierarchy"]["die_0"]["size_mm"][0])

    return {
        "name": "3dic_x_thermal_fno",
        "model_file": model_path.name,
        "task": "steady-state conduction: power map -> temperature field",
        "input": {
            "name": "power_w_per_cell",
            "shape": ["batch", channels, grid, grid],
            "dtype": "float32",
            "units": "W per cell",
            "not_units": "NOT W/m^2 and NOT W/mm^2 -- absolute watts in each cell",
            "cell_pitch_mm": die_mm / grid,
            "channel_layout": (
                f"{channels} channels = {layers} physical layers x {per_layer} "
                f"z-cells. Channel c belongs to physical layer c // {per_layer}. "
                f"A layer's watts are split EVENLY across its {per_layer} z-cells."),
            "layer_names": ["Die", "Hybrid_Bond", "Die", "C4_BGA", "Package"],
            "logic_die_channels": list(range(per_layer)),
            "memory_die_channels": list(range(per_layer, 2 * per_layer)),
        },
        "output": {
            "name": "temperature_norm",
            "shape": ["batch", channels, grid, grid],
            "units": "normalised",
            "denormalise": "T_degC = temperature_norm * std + mean",
            "mean": float(stats["mean"]),
            "std": float(stats["std"]),
            "peak_tj_recipe": (
                "de-normalise, then amax over the logic-die channels for logic "
                "peak Tj; do not take amax over all channels unless you want "
                "the hottest cell anywhere in the stack"),
        },
        "error_band": {
            "held_out_field_rmse_k": 0.6889,
            "held_out_mean_abs_peak_error_k": 1.0812,
            "error_at_optimiser_selected_designs_k": 1.33,
            "basis": "reports/surrogate_retraining.md, "
                     "reports/physicsnemo_interop.md",
            "use_for": "RANKING designs, not absolute temperatures",
        },
        "known_defects": [
            {
                "what": "the spectral convolution is circular; the die's sides "
                        "are adiabatic. A macro on the die edge produces "
                        "phantom temperature on the opposite edge.",
                "magnitude_k": 13.6,
                "where": "reports/physicsnemo_gap_review.md section 1",
                "mitigation": "treat predictions for designs with power in the "
                              "outermost cell ring as unreliable; re-solve them "
                              "on the reference solver",
            },
            {
                "what": "trained on uniform rectangular macro blocks at "
                        "1.125 mm; real power maps concentrate half the power "
                        "in 15-19% of the area",
                "magnitude_k": 21.0,
                "where": "reports/power_map_reality.md",
                "mitigation": "an input-resolution limit, not a solver error",
            },
        ],
        "validation": {
            "tier": "T0",
            "independent_implementations": [
                "NVIDIA PhysicsNeMo FNO -- agrees to 7.4e-05 K on 400 held-out maps",
                "onnxruntime -- executes the exported graph to 5.9e-05 K",
            ],
        },
        "claim_limit": ("Architectural exploration only. Re-verify in a "
                        "certified flow before tape-out."),
    }


def export(outdir: Path, model_path: Path = DEFAULT_MODEL,
           stats_path: Path = DEFAULT_STATS, grid: int = 16,
           opset: int = 20) -> dict:
    """Write `surrogate.onnx` + `surrogate_contract.json` into `outdir`."""
    outdir.mkdir(parents=True, exist_ok=True)
    model = load(model_path)
    onnx_path = outdir / "surrogate.onnx"
    # `dynamic_shapes` rather than the older `dynamic_axes`: with torch's dynamo
    # exporter, `dynamic_axes` leaves the *output* shape pinned at the traced
    # batch, so the graph runs correctly at any batch while advertising {1,...}.
    # onnxruntime warns about the mismatch and a consumer validating shapes
    # against the metadata would reject a correct result.
    batch = torch.export.Dim("batch")
    torch.onnx.export(
        model, (torch.zeros(2, model.channels, grid, grid),), str(onnx_path),
        input_names=["power_w_per_cell"], output_names=["temperature_norm"],
        dynamic_shapes={"x": {0: batch}},
        opset_version=opset,
    )
    doc = contract(model_path, stats_path)
    doc["onnx"] = {"file": onnx_path.name, "opset": opset,
                   "traced_grid": grid,
                   "note": "batch axis is dynamic; an FNO is resolution-"
                           "agnostic but re-export rather than assume"}
    (outdir / "surrogate_contract.json").write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path,
                    default=REPO / "results/handoff/surrogate")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--grid", type=int, default=16)
    a = ap.parse_args(argv)

    if not a.model.exists():
        print(f"no surrogate at {a.model}. Trained weights are build artifacts; "
              f"train one first (see reports/vertical_mesh.md).", file=sys.stderr)
        return 1

    doc = export(a.out, a.model, grid=a.grid)
    onnx_file = a.out / doc["onnx"]["file"]
    print(f"wrote {onnx_file}  ({onnx_file.stat().st_size:,} bytes)")
    print(f"wrote {a.out / 'surrogate_contract.json'}")
    print(f"  input  : {doc['input']['name']} {doc['input']['shape']} "
          f"[{doc['input']['units']}]")
    print(f"  output : T_degC = y * {doc['output']['std']:.4f} + "
          f"{doc['output']['mean']:.4f}")
    print(f"  band   : {doc['error_band']['held_out_field_rmse_k']} K field RMSE, "
          f"{doc['error_band']['error_at_optimiser_selected_designs_k']} K at "
          f"selected designs")
    print(f"  defects: {len(doc['known_defects'])} declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
