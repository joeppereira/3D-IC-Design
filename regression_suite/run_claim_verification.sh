#!/bin/bash
# Claim verification: the guardrails that catch what tests cannot.
#
# The physics gate checks that the code computes what it says. This gate checks
# that the *prose* says what the code computed -- which is where every defect in
# reports/critical_review.md actually lived:
#
#   a "6.5 C headroom" that was never measured
#   a "100,000x speedup" beside a fabricated peak
#   a "1 um / 50 nm ROI mesh" that was never run
#   a docstring advertising per-ROI temperature injection that emits comments
#   "ROMs from Ansys Icepak data" where no licensed tool has ever run
#
# None was a code defect, so no test caught any of them.
#
# Fast and licence-free: run it before committing.
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
[ -x .venv/bin/python ] && PY=.venv/bin/python

echo "=================================================================="
echo " CLAIM VERIFICATION"
echo "=================================================================="

echo
echo "--- [1/2] claim lint over tracked .md and .py --------------------"
# Errors fail the gate; warnings are printed for a human to weigh.
if ! $PY .claude/hooks/claim_lint.py; then
    echo
    echo "  ❌ claim lint found errors. Each one is a claim the repository"
    echo "     cannot support as written. Fix the claim, not the linter --"
    echo "     and if a rule is genuinely wrong, add a 'clean' case to"
    echo "     evals/cases/claims.md so it stays wrong on purpose."
    exit 1
fi

echo
echo "--- [2/2] evals: do the guardrails work, and does prose match data? --"
if ! $PY evals/run_evals.py; then
    echo
    echo "  ❌ the claim linter no longer behaves as its labelled cases say."
    echo "     A linter without working evals drifts into noise or decoration."
    exit 1
fi

echo
echo "=================================================================="
echo " CLAIM VERIFICATION PASSED"
echo " Drift findings above are informational: report prose legitimately"
echo " cites other reports. Investigate any quantity you cannot trace."
echo "=================================================================="
