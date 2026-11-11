#!/usr/bin/env python3
"""Evals for the guardrails themselves, and for prose-against-data drift.

Two things are checked here, and neither is physics -- the physics has its own
gate. These check *claims*, which is where this repository's defects have
actually lived.

  1. **Linter evals.** `.claude/hooks/claim_lint.py` is only worth running if it
     fires on bad prose and stays silent on good prose. The cases in
     `cases/claims.md` are labelled examples, most of them lifted verbatim
     from real retracted claims in this repository's own history. A linter with
     no eval drifts into either noise or decoration.

  2. **Prose-against-data drift.** Every report pairs an `.md` with a `.json`.
     The prose is written by hand and the JSON is generated, so they can
     disagree -- and a number that drifts out of a report is exactly the
     failure this project keeps finding. For each report, every physical
     quantity in the prose that *looks* like it came from the paired JSON is
     checked against it.

    python evals/run_evals.py
    python evals/run_evals.py --only drift
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES = Path(__file__).resolve().parent / "cases"

spec = importlib.util.spec_from_file_location(
    "claim_lint", REPO / ".claude/hooks/claim_lint.py")
claim_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(claim_lint)


# --- 1. linter evals ---------------------------------------------------------
def _parse_cases(path: Path) -> list[dict]:
    """Minimal reader for the case file.

    Deliberately not yaml: `pyyaml` is not in requirements.txt and adding a
    dependency so an eval can read its own fixtures is the wrong trade. Format
    is one case per block:

        --- <rule-or-"clean">
        <text, one or more lines>
    """
    cases, cur = [], None
    for line in path.read_text().splitlines():
        if line.startswith("--- "):
            if cur:
                cases.append(cur)
            cur = {"expect": line[4:].strip(), "text": []}
        elif cur is not None and not line.lstrip().startswith("#"):
            cur["text"].append(line)
    if cur:
        cases.append(cur)
    for c in cases:
        c["text"] = "\n".join(c["text"]).strip("\n")
    return [c for c in cases if c["text"].strip()]


def eval_linter() -> tuple[int, int]:
    """Each case is linted as a standalone .md; the fired rules must match."""
    path = CASES / "claims.md"
    cases = _parse_cases(path)
    passed = failed = 0
    tmp = CASES / "_tmp_case.md"
    for i, case in enumerate(cases, 1):
        tmp.write_text(case["text"] + "\n")
        try:
            fired = {f[2] for f in claim_lint.lint(tmp)}
        finally:
            tmp.unlink(missing_ok=True)
        want = set() if case["expect"] == "clean" else {case["expect"]}
        # Case files only assert the rule under test; other rules may also fire
        # on the same snippet and that is not a failure unless "clean".
        ok = (not fired) if case["expect"] == "clean" else want <= fired
        if ok:
            passed += 1
        else:
            failed += 1
            first = case["text"].splitlines()[0][:88]
            print(f"  ✗ case {i}: expected {case['expect'] or 'clean'}, "
                  f"fired {sorted(fired) or 'nothing'}\n      {first}")
    print(f"  linter evals: {passed} passed, {failed} failed "
          f"({len(cases)} cases)")
    return passed, failed


# --- 2. prose-against-data drift --------------------------------------------
NUM_IN_PROSE = re.compile(
    r"(?<![\w.])(\d+\.\d+)\s*(?:K\b|°C|kelvin|ps\b|W\b|dB\b)")


def _json_numbers(obj, out: set[float]) -> set[float]:
    if isinstance(obj, dict):
        for v in obj.values():
            _json_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.add(round(abs(float(obj)), 6))
    return out


def eval_drift() -> tuple[int, int]:
    """Numbers in report prose must appear in the JSON the report cites.

    A quantity written to two decimals is matched against the JSON rounded to
    the same precision, so 0.6889 in prose matches 0.68892574... in the file.
    Prose carries plenty of numbers that are not from the paired JSON -- budget
    figures, references, round numbers -- so a miss is reported only when the
    report cites exactly one JSON and the value is absent from it.
    """
    reports = REPO / "reports"
    passed = failed = 0
    for md in sorted(reports.glob("*.md")):
        text = md.read_text()
        cited = sorted({m for m in re.findall(r"[\w/]+\.json", text)})
        if len(cited) != 1:
            continue
        data_path = reports / Path(cited[0]).name
        if not data_path.exists():
            continue
        try:
            nums = _json_numbers(json.loads(data_path.read_text()), set())
        except json.JSONDecodeError:
            continue
        # Pre-round the JSON at every precision the prose might use.
        by_prec = {p: {round(v, p) for v in nums} for p in range(0, 5)}
        missing = []
        for raw in NUM_IN_PROSE.findall(text):
            prec = len(raw.split(".")[1])
            if round(abs(float(raw)), prec) not in by_prec.get(prec, set()):
                missing.append(raw)
        if missing:
            failed += 1
            print(f"  ✗ {md.name} cites {data_path.name} but these prose "
                  f"quantities are not in it: {sorted(set(missing))[:8]}")
        else:
            passed += 1
    print(f"  drift evals: {passed} report(s) consistent, {failed} with "
          f"unbacked quantities")
    return passed, failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=("linter", "drift"))
    a = ap.parse_args(argv)

    print("=" * 66)
    print(" CLAIM EVALS")
    print("=" * 66)
    failed = 0
    if a.only in (None, "linter"):
        print("\n--- [1/2] does the claim linter fire where it should? ------")
        failed += eval_linter()[1]
    if a.only in (None, "drift"):
        print("\n--- [2/2] does report prose match the data it cites? ------")
        # Drift findings are informational: prose legitimately carries numbers
        # from elsewhere. They are printed, not failed.
        eval_drift()

    print("\n" + "=" * 66)
    print(" CLAIM EVALS " + ("PASSED" if not failed else "FAILED"))
    print("=" * 66)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
