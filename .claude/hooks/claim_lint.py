#!/usr/bin/env python3
"""Mechanical guardrails against this repository's actual failure mode.

Every defect catalogued in `reports/critical_review.md` is the same shape:
prose that outran the measurement. A "6.5 °C headroom" that was never measured.
A `transient_roi_solver.py` reporting a fabricated peak beside a "100,000x
speedup". A `1 µm/50 nm` ROI mesh that was never run. A `write_primesim`
docstring advertising per-ROI temperature injection that emits three identical
comments. None of these were caught by a test, because none of them were code
defects -- they were *claims*.

So these rules check claims, not code. Each one is deliberately narrow: a rule
that fires on honest prose is worse than no rule, because it trains people to
pass `--fix` without reading. The rules were calibrated by running them over the
existing reports and tightening until every hit was a real finding.

    python .claude/hooks/claim_lint.py                 # tracked .md and .py
    python .claude/hooks/claim_lint.py path [path ...]
    python .claude/hooks/claim_lint.py --staged        # pre-commit use

Exit 1 if any ERROR. Warnings never fail the run; they are for a human to read.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Tools that exist on nobody's machine here. T1 has never been reached: no
# licensed tool has ever opened an artifact from this repository.
VENDOR_TOOLS = (r"Icepak|StarRC|HFSS|PrimeSim|PrimeTime|Celsius|Voltus|Calibre"
                r"|Quantus|Spectre|Clarity|SIwave|Flotherm|HyperLynx|Redhawk"
                r"|Totem|Eldo|Symphony")

TIER_TOKEN = re.compile(r"\bT[0-3]\b")

# Phrases that mark prose as discussing a limit rather than asserting a result.
HEDGE = re.compile(
    r"\b(not|never|cannot|can't|would|requires?|needs?|absent|unmeasured"
    r"|out of scope|unvalidated|if |once |before |until |no licen|lacks?"
    r"|pending|planned|unbuilt|fabricat|overclaim|claimed|asserted"
    r"|superseded|stale|contradict|outstanding|missing|unavailable"
    r"|advertis|so-called|misleading|wrong|overstates?|purport)\b", re.I)

# Terms that make a ratio accountable: it is quoted beside a correctness check.
CORRECTNESS = re.compile(
    r"\b(exact|converged?|agree|within|error|RMSE|residual|tolerance"
    r"|checked|analytic)\b", re.I)

# Text inside quotes or backticks is being *reported*, not asserted. A report
# that criticises `"99.97% accurate"` must not be flagged for claiming it --
# which is the single most common false positive these rules can produce.
QUOTED = re.compile(r"[\"'`“”]([^\"'`“”]{0,200})[\"'`“”]")


def _unquoted(line: str) -> str:
    return QUOTED.sub(" ", line)


def _rule_percent_accuracy(line: str, window: str):
    """Accuracy as a percentage, with no basis. The house unit is kelvin."""
    bare = _unquoted(line)
    if HEDGE.search(window):
        return None
    if re.search(r"~?\s*\d{1,3}(?:\.\d+)?\s*%\+?\s*(?:accurate|accuracy)",
                 bare, re.I):
        return ("ERROR", "percent-accuracy",
                "accuracy as a bare percentage -- report the physical unit and "
                "the basis (e.g. '1.33 K at optimiser-selected designs')")
    return None


def _rule_speedup(line: str, window: str):
    """A speedup claim with no correctness check beside it.

    transient_roi_solver.py was deleted for exactly this pairing: a large
    speedup quoted next to a peak nobody had checked.

    Narrow deliberately. `900 x 600 um` is a macro footprint, `240x240` is a
    matrix and `128x UCIe lanes` is a count -- none is a ratio. So the line
    must actually say it is faster, the `x` must not be followed by another
    number, and a correctness term anywhere in the line clears it.
    """
    bare = _unquoted(line)
    if not re.search(r"\b(faster|speed-?ups?|quicker|cheaper)\b", bare, re.I):
        return None
    if HEDGE.search(window) or CORRECTNESS.search(window):
        return None
    m = re.search(r"\b(\d[\d,]{2,})\s*[x×](?!\s*\d)", bare)
    if m:
        return ("WARN", "unchecked-speedup",
                f"speedup of {m.group(1)}x -- a ratio needs a correctness "
                "check against something more trustworthy in the same breath "
                "(see the transient_roi_solver precedent)")
    return None


def _rule_vendor_executed(line: str, window: str):
    """Claiming a licensed tool ran, confirmed or validated something.

    It has not. T1 is empty. This is the rule that would have caught the
    'ROMs from high-fidelity Ansys Icepak data' line in GEMINI.md.
    """
    bare = _unquoted(line)
    if not re.search(VENDOR_TOOLS, bare, re.I):
        return None
    if HEDGE.search(window) or TIER_TOKEN.search(window):
        return None
    if re.search(r"\b(validated|verified|confirmed|correlated|measured by"
                 r"|signed off|sign-off|qualified|certified|ingested"
                 r"|data from|extracted from|produced by)\b", bare, re.I):
        return ("ERROR", "vendor-executed",
                "implies a licensed vendor tool ran or produced data. No "
                "licensed tool has ever opened an artifact from this repo -- "
                "T1 is empty. State the tier, or say what it *would* take")
    return None


def _rule_signoff(line: str, window: str):
    """'Sign-off' or 'qualified' asserted about our own result.

    T3 is permanently out of scope. Discussing it is fine; claiming it is not,
    and naming an artifact (`run_v1_qualification.sh`, "the qualification
    gate") is neither.
    """
    bare = _unquoted(line)
    if re.search(r"\bqualif\w*[\s_-]+(gate|suite|summary|checklist|plan|run|"
                 r"script|report)\b", bare, re.I):
        return None
    if not re.search(r"\b(sign-?ed?[- ]off|qualif(?:ied|ication)|certified"
                     r"|tape-?out ready)\b", bare, re.I):
        return None
    if HEDGE.search(window) or TIER_TOKEN.search(window):
        return None
    if re.search(r"\b(this|our)\s+(design|result|flow|module|candidate)\b",
                 bare, re.I):
        return ("ERROR", "signoff-claim",
                "asserts sign-off or qualification. T3 is permanently out of "
                "scope; use 'exploratory verification' or 'architectural pass'")
    return None


LINE_RULES = (_rule_percent_accuracy, _rule_speedup, _rule_vendor_executed,
              _rule_signoff)


def _rule_vendor_needs_tier(path: Path, text: str):
    """A document that discusses vendor tools must name a tier somewhere.

    Mentions inside blockquotes or backticks do not count: `rom_pinn_validation.md`
    names Icepak only to quote a retracted claim, which is the opposite of
    making an integration claim.
    """
    if path.suffix != ".md" or TIER_TOKEN.search(text):
        return []
    body = "\n".join(l for l in text.splitlines()
                     if not l.lstrip().startswith(">")
                     and not HEDGE.search(l))
    if not re.search(VENDOR_TOOLS, _unquoted(body), re.I):
        return []
    return [(0, "WARN", "untiered-vendor-doc",
             "names vendor tools but never states a tier (T0-T3). Every "
             "integration claim must name its tier")]


def _rule_report_cites_data(path: Path, text: str):
    """A report full of numbers should cite the data and the script.

    Reports in this repo pair prose with a .json and name the command that
    produced it. One that does not is unreproducible by construction.
    """
    try:
        rel = path.relative_to(REPO)
    except ValueError:
        return []
    if rel.parts[0] != "reports" or path.suffix != ".md":
        return []
    numbers = re.findall(r"\b\d+\.\d+\s*(?:K|°C|C|ps|W|dB|µm|um|mm|GHz|TB/s)\b",
                         text)
    if len(numbers) < 5:
        return []
    if re.search(r"\.json|\.py\b|```bash|```sh", text):
        return []
    return [(0, "WARN", "unsourced-report",
             f"{len(numbers)} physical quantities but no .json, no script and "
             "no reproduce block. Pair the prose with the data that backs it")]


FILE_RULES = (_rule_vendor_needs_tier, _rule_report_cites_data)

SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git", "dist"}

# Frozen by intent. GEMINI.md is a superseded historical document kept
# deliberately unedited below its header, and that header already tabulates
# every claim these rules would flag. Editing it to satisfy a linter would
# falsify the history it exists to preserve.
EXEMPT = {
    "GEMINI.md": "superseded historical document, unedited by intent",
    # The eval corpus is *made of* bad claims on purpose -- that is what makes
    # it an eval. Linting it reports every positive case as a defect, which is
    # how a guardrail ends up flagging its own test fixtures.
    "evals/cases/claims.md": "labelled bad claims, by construction",
}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.md", "*.py"],
                         capture_output=True, text=True)
    return [REPO / p for p in out.stdout.split() if p]


def staged_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--cached", "--name-only",
         "--diff-filter=ACM"], capture_output=True, text=True)
    return [REPO / p for p in out.stdout.split()
            if p.endswith((".md", ".py")) and (REPO / p).exists()]


def lint(path: Path) -> list[tuple]:
    rel = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)
    if rel in EXEMPT:
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    findings = []
    for rule in FILE_RULES:
        findings += list(rule(path, text))
    lines = text.splitlines()
    in_fence = False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        # Code and quoted history are not claims. A line quoting a retracted
        # claim in order to retract it must not be flagged for making it.
        if in_fence or line.lstrip().startswith((">", "#", "*   [", "|")):
            continue
        # A claim is a sentence, not a line. Wrapped prose and multi-line
        # docstrings routinely put the number on one line and the hedge that
        # qualifies it on the next, so rules match on `line` but judge intent
        # over a three-line window.
        window = " ".join(lines[max(0, n - 2):n + 1])
        for rule in LINE_RULES:
            if (hit := rule(line, window)):
                findings.append((n, hit[0], hit[1], hit[2]))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--staged", action="store_true",
                    help="lint git-staged files only")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress warnings; errors only")
    a = ap.parse_args(argv)

    if a.paths:
        files = []
        for p in a.paths:
            if p.is_dir():
                files += [q for q in p.rglob("*")
                          if q.suffix in (".md", ".py")
                          and not SKIP_DIRS & set(q.parts)]
            else:
                files.append(p)
    else:
        files = staged_files() if a.staged else tracked_files()

    errors = warns = 0
    for path in sorted(set(files)):
        for n, sev, rule, msg in lint(path):
            if sev == "WARN":
                warns += 1
                if a.quiet:
                    continue
            else:
                errors += 1
            where = f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path}"
            loc = f"{where}:{n}" if n else where
            print(f"[{sev:5}] {loc}: {rule}\n         {msg}")

    print(f"\nclaim lint: {len(set(files))} files, {errors} error(s), "
          f"{warns} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
