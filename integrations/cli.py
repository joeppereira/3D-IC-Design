"""3DIC-X <-> EDA interchange CLI.

    python -m integrations.cli status
    python -m integrations.cli emit --target neutral:all
    python -m integrations.cli emit --target cadence:celsius
    python -m integrations.cli ingest celsius_temperature.csv --kind thermal
    python -m integrations.cli correlate --thermal celsius_temperature.csv \
                                         --ir voltus_ir_drop.csv
    python -m integrations.cli roundtrip        # the T0 gate, no licenses needed
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .base import (REPO_ROOT, HOOK_REGISTRY, resolve, run_id, git_sha,
                   fmt_findings, SEV_ERROR)
from .canonical import load_design
from . import correlate as corr
from .importers import vendor_results as vr
from . import vendors  # noqa: F401  (registers every hook)

HANDOFF = REPO_ROOT / "results/handoff"


def _design(args):
    return load_design(getattr(args, "golden", None), getattr(args, "deck", None))


def cmd_status(args) -> int:
    design = _design(args)
    print(f"design      : {design.project}")
    print(f"record sha  : {design.sha256()[:16]}  (git {git_sha()})")
    print(f"sources     : {json.dumps(design.sources, indent=14)[14:]}")
    print(f"dies        : {len(design.dies)}  macros: {len(design.macros)}  "
          f"nets: {len(design.nets)}  links: {len(design.links)}")
    p = design.predictions
    print(f"predictions : Tj {p.tj_peak_c} C | droop {p.droop_mv} mV | "
          f"IL {p.insertion_loss_db} dB | eye {p.eye_margin_ui} UI")
    cal = corr.load_calibration()
    print(f"calibration : {cal or 'none applied (no trustworthy T2 correlation yet)'}")
    print(f"\n{'target':28} {'tier':5} {'fidelity':10} requires")
    for key in sorted(HOOK_REGISTRY):
        h = HOOK_REGISTRY[key]
        print(f"{key:28} {h.tier:5} {h.fidelity:10} {','.join(h.requires) or '-'}")
    return 0


def cmd_emit(args) -> int:
    design = _design(args)
    rid = args.run_id or run_id()
    root = Path(args.outdir) if args.outdir else HANDOFF / rid
    try:
        hooks = resolve(args.target)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    manifests, failed = {}, []
    for cls in hooks:
        hook = cls()
        outdir = root / f"{hook.vendor}_{hook.tool}"
        result = hook.run(design, outdir, rid=rid)
        man = result.manifest(outdir)
        (outdir / "manifest.json").write_text(json.dumps(man, indent=2) + "\n")
        manifests[hook.target] = man
        status = "ok  " if result.ok else "FAIL"
        print(f"[{status}] {hook.target:28} {len(result.files):2} files -> "
              f"{outdir.relative_to(REPO_ROOT) if outdir.is_relative_to(REPO_ROOT) else outdir}")
        for note in result.notes:
            print(f"         . {note}")
        for f in result.findings:
            if f.severity != "info" or args.verbose:
                print(f"         {f}")
        if not result.ok:
            failed.append(hook.target)

    top = {"run_id": rid, "git_sha": git_sha(), "design": design.project,
           "design_record": design.sha256(),
           "targets": {k: {"tier": v["tier"], "fidelity": v["fidelity"],
                           "ok": v["ok"], "files": len(v["files"])}
                       for k, v in manifests.items()}}
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(top, indent=2) + "\n")
    print(f"\nrun {rid}: {len(hooks) - len(failed)}/{len(hooks)} targets ok")
    if failed:
        print("failed: " + ", ".join(failed), file=sys.stderr)
    return 1 if failed else 0


def cmd_ingest(args) -> int:
    for path in args.files:
        try:
            res = vr.read_any(Path(path), args.kind)
        except Exception as exc:
            print(f"[FAIL] {path}: {exc}", file=sys.stderr)
            return 1
        print(f"[ok  ] {path}  kind={res['kind']}"
              + ("  self-generated" if corr.is_self_generated(Path(path)) else ""))
        for k, v in res.items():
            if k in ("kind", "source", "field", "coords_um", "s", "freqs_hz",
                     "il_db", "il_at"):
                continue
            if isinstance(v, dict) and len(v) > 6:
                v = f"{len(v)} entries"
            print(f"         {k}: {v}")
    return 0


def cmd_correlate(args) -> int:
    design = _design(args)
    results = []
    if args.thermal:
        results.append(corr.thermal(design, vr.read_thermal_field(Path(args.thermal))))
    if args.ir:
        results.append(corr.ir_drop(design, vr.read_ir_drop(Path(args.ir))))
    if args.spef:
        results.append(corr.parasitics(design, vr.read_starrc_spef(Path(args.spef))))
    if args.sparam:
        link = next((l for l in design.links if l.name == args.link), design.links[0])
        results.append(corr.channel(design, link, vr.read_sparameters(Path(args.sparam))))
    if not results:
        print("nothing to correlate: pass --thermal/--ir/--spef/--sparam",
              file=sys.stderr)
        return 2

    for c in results:
        print(c.finding())
        for k, v in c.detail.items():
            print(f"         {k}: {v}")
    report = corr.write_report(results)
    cal = corr.write_calibration(results)
    print(f"\nreport      -> {report.relative_to(REPO_ROOT)}")
    print(f"calibration -> {cal.relative_to(REPO_ROOT)}")
    print(f"calibrated  : {corr.apply_calibration(design, corr.load_calibration(cal))}")
    if any(c.tier == "T0" for c in results):
        print("\nnote: at least one input was generated by this repo, so this run "
              "validates plumbing (T0), not physics.")
    return 0


def cmd_roundtrip(args) -> int:
    """The T0 gate: emit every hook into a temp dir and fail on any error."""
    design = _design(args)
    rid = run_id()
    failures = []
    with tempfile.TemporaryDirectory(prefix="3dicx-t0-") as tmp:
        root = Path(tmp)
        for key in sorted(HOOK_REGISTRY):
            hook = HOOK_REGISTRY[key]()
            result = hook.run(design, root / key.replace(":", "_"), rid=rid)
            errs = [f for f in result.findings if f.severity == SEV_ERROR]
            print(f"[{'ok  ' if result.ok else 'FAIL'}] {key:28} "
                  f"{len(result.files):2} files, {len(errs)} errors")
            for f in errs:
                print(f"         {f}")
            if errs:
                failures.append(key)
    print(f"\nT0 round-trip: {len(HOOK_REGISTRY) - len(failures)}/{len(HOOK_REGISTRY)} targets clean")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m integrations.cli",
                                description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--golden", help="path to golden_config.json")
    p.add_argument("--deck", help="path to the vector deck json")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show the design record and hook registry"
                   ).set_defaults(func=cmd_status)

    e = sub.add_parser("emit", help="write artifacts for a target")
    e.add_argument("--target", default="neutral:all",
                   help="'neutral:all', 'all', 'cadence:celsius', ...")
    e.add_argument("--outdir")
    e.add_argument("--run-id")
    e.set_defaults(func=cmd_emit)

    i = sub.add_parser("ingest", help="read a vendor result file")
    i.add_argument("files", nargs="+")
    i.add_argument("--kind", choices=sorted(vr.READERS))
    i.set_defaults(func=cmd_ingest)

    c = sub.add_parser("correlate", help="compare vendor results to the surrogate")
    c.add_argument("--thermal")
    c.add_argument("--ir")
    c.add_argument("--spef")
    c.add_argument("--sparam")
    c.add_argument("--link", default="LINK_0")
    c.set_defaults(func=cmd_correlate)

    sub.add_parser("roundtrip", help="T0 gate: emit + validate everything"
                   ).set_defaults(func=cmd_roundtrip)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
