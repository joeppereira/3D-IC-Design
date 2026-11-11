"""The trained surrogate as an interchange artifact.

Sixteen of the seventeen emit targets hand over *geometry and electrical
description* -- DEF, LEF, GDSII, SPEF, Liberty, Touchstone, IBIS, SPICE. A
receiver can rebuild the stack and extract from it, but cannot run the model
that produced the thermal numbers those artifacts are annotated with. So the
numbers arrive without the thing that made them, and a consumer wanting more
designs evaluated has to ask us.

This emits the surrogate itself: an ONNX graph plus the contract that says what
its tensors mean. Written as a hook like any other so it inherits the run id,
the design-record hash, the SHA-256 manifest and the tier declaration, rather
than being a file someone copies out of `results/`.

The foreign readers are `onnx` (checker) and `onnxruntime` (execution), which
is what makes this T0 on the same terms as gdstk for GDSII. Unlike the vendor
formats this one has no T1 ceiling waiting on a licence: onnxruntime is the
real consumer, so emitted-and-executed is the whole claim.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from ..base import (Finding, SEV_ERROR, SEV_WARN, SEV_INFO, REPO_ROOT,
                    write_sidecar)

SRC = REPO_ROOT / "physics_accelerated/src"

ONNX_FILE = "surrogate.onnx"
CONTRACT_FILE = "surrogate_contract.json"


def available() -> tuple[bool, str]:
    """Can this target be emitted on this machine?

    Three ways it cannot, each reported rather than raised: torch's ONNX
    exporter needs `onnxscript`, the graph needs `onnx`, and the trained
    weights are build artifacts that a fresh clone does not have.
    """
    for mod, hint in (("onnx", "pip install onnx"),
                      ("onnxscript", "pip install onnxscript")):
        if importlib.util.find_spec(mod) is None:
            return False, f"{mod} is not installed ({hint})"
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    try:
        import surrogate_export as sx
    except Exception as exc:                        # pragma: no cover
        return False, f"surrogate_export unimportable: {exc}"
    if not sx.DEFAULT_MODEL.exists():
        return False, (f"no trained surrogate at "
                       f"{sx.DEFAULT_MODEL.relative_to(REPO_ROOT)} -- weights "
                       f"are build artifacts, train one first")
    return True, "ok"


def write(outdir: Path, prov: dict) -> list[str]:
    """Emit the bundle; returns the file names written."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    import surrogate_export as sx

    doc = sx.export(outdir)
    # The contract is generated from the weights, so the provenance block is
    # merged in afterwards rather than being baked into surrogate_export --
    # that module must stay usable without the interchange layer.
    contract_path = outdir / CONTRACT_FILE
    doc = json.loads(contract_path.read_text())
    doc["provenance"] = prov
    contract_path.write_text(json.dumps(doc, indent=2) + "\n")
    # ONNX is binary and cannot carry a comment header.
    side = write_sidecar(outdir / ONNX_FILE, prov)
    return [ONNX_FILE, CONTRACT_FILE, side.name]


def read(outdir: Path) -> dict:
    return json.loads((outdir / CONTRACT_FILE).read_text())


def validate(outdir: Path) -> list[Finding]:
    """Hand the graph to implementations nobody here wrote, and check that the
    contract describes the graph it ships with.

    A contract that disagrees with its own artifact is worse than no contract:
    it converts a consumer's correct reading into a wrong result.
    """
    findings: list[Finding] = []
    onnx_path = outdir / ONNX_FILE
    if not onnx_path.exists():
        return [Finding(SEV_ERROR, "exists", f"{ONNX_FILE} was not written")]

    doc = read(outdir)

    # 1. an independent parser
    try:
        import onnx
        model = onnx.load(str(onnx_path))
        onnx.checker.check_model(model, full_check=True)
        findings.append(Finding(SEV_INFO, "onnx_checker",
                                "onnx.checker full_check passed"))
    except Exception as exc:
        return findings + [Finding(SEV_ERROR, "onnx_checker", f"{exc}"[:200])]

    # 2. the contract must name the graph's actual tensors
    g_in = [i.name for i in model.graph.input]
    g_out = [o.name for o in model.graph.output]
    if doc["input"]["name"] not in g_in:
        findings.append(Finding(
            SEV_ERROR, "contract_io",
            f"contract declares input '{doc['input']['name']}' but the graph "
            f"has {g_in}"))
    if doc["output"]["name"] not in g_out:
        findings.append(Finding(
            SEV_ERROR, "contract_io",
            f"contract declares output '{doc['output']['name']}' but the graph "
            f"has {g_out}"))

    # 3. the declared channel count must be the graph's channel count
    try:
        dim = model.graph.input[0].type.tensor_type.shape.dim[1].dim_value
        if dim and dim != doc["input"]["shape"][1]:
            findings.append(Finding(
                SEV_ERROR, "contract_shape",
                f"contract declares {doc['input']['shape'][1]} channels, graph "
                f"has {dim}"))
    except (IndexError, AttributeError):
        pass

    # 4. an independent runtime must execute it, at a batch size the export
    #    never traced -- a graph with the batch folded into a Reshape passes
    #    every check above and still fails here.
    if importlib.util.find_spec("onnxruntime") is None:
        findings.append(Finding(
            SEV_WARN, "onnxruntime",
            "onnxruntime not installed: the graph is parsed but never executed, "
            "which is the half of T0 that catches batch-shape defects"))
    else:
        try:
            import numpy as np
            import onnxruntime as ort
            sess = ort.InferenceSession(str(onnx_path),
                                        providers=["CPUExecutionProvider"])
            ch = doc["input"]["shape"][1]
            x = np.zeros((3, ch, 16, 16), dtype=np.float32)
            x[:, 0, 6:10, 6:10] = 2.5
            y = sess.run(None, {doc["input"]["name"]: x})[0]
            t_c = y * doc["output"]["std"] + doc["output"]["mean"]
            peak = float(t_c[:, doc["input"]["logic_die_channels"]].max())
            if not (25.0 < peak < 400.0):
                findings.append(Finding(
                    SEV_ERROR, "onnxruntime_sanity",
                    f"following the contract gives a logic peak of {peak:.1f} C, "
                    f"which is not a plausible temperature -- the "
                    f"de-normalisation or the channel layout is wrong"))
            else:
                findings.append(Finding(
                    SEV_INFO, "onnxruntime",
                    f"executed at batch 3 (export traced batch 1); contract "
                    f"recipe gives a logic peak of {peak:.1f} C"))
        except Exception as exc:
            findings.append(Finding(SEV_ERROR, "onnxruntime",
                                    f"graph parses but will not run: {exc}"[:200]))

    # 5. the honesty fields a consumer depends on
    if doc.get("validation", {}).get("tier") != "T0":
        findings.append(Finding(SEV_ERROR, "tier",
                                "the surrogate bundle must declare tier T0"))
    if not doc.get("known_defects"):
        findings.append(Finding(
            SEV_ERROR, "known_defects",
            "the contract declares no known defects. The boundary wrap "
            "(reports/physicsnemo_gap_review.md) is measured and must be "
            "disclosed to anyone running this model"))
    return findings
