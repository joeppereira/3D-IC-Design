---
name: tier-audit
description: Audit a claim, report or docstring for honesty — tier, fidelity, units, and whether the prose matches the data. Use before publishing a claim, when reviewing a report, or when asked whether something in this repo is actually true.
---

# Auditing a claim

`reports/critical_review.md` is a standing adversarial audit of this repository
and §5 is the authoritative to-do list. This skill is how a new claim gets the
same treatment before it joins them.

## Run the mechanical checks first

```bash
python .claude/hooks/claim_lint.py <paths>
python evals/run_evals.py
```

They catch four patterns, all drawn from real retractions here: accuracy as a
bare percentage, a speedup with no correctness check, prose implying a licensed
tool ran, and sign-off asserted about our own result.

They do **not** catch the interesting cases. The rest is reading.

## The questions that have actually found things

**Does the number exist anywhere outside the prose?** The "6.5 °C headroom" did
not. Trace every quantity to a `.json` and the script that wrote it. The drift
eval automates part of this, but only for reports citing exactly one JSON.

**Is the mechanism in the code, or only in the docstring?** `write_primesim`
claimed per-ROI temperature injection and emitted three identical comments. Read
the emitted artifact, not the function name. Generate it and grep it.

**Is the speedup paired with a correctness check?** `transient_roi_solver.py`
reported a fabricated peak beside a "100,000× speedup" and was deleted. A ratio
alone is a liability.

**Is the converged thing the thing that matters?** A GCI of 0.081% on a power
map already smeared into 1.125 mm blocks is a converged answer to a question
nobody asked. Check that the *input* is as resolved as the mesh.

**Does the correction act differentially?** A correction applied uniformly to
every candidate is order-preserving and therefore decision-neutral. `rank_churn`
exists to answer this; `fidelity_integration.md` §9 lists it as a failure mode.

**Is a claimed tier supported?** T1 means a licensed tool loaded the artifact.
Nothing in this repository has reached it. Prose implying otherwise is wrong
regardless of how carefully it is phrased.

**Is the dependency really present?** A test that silently skips is not a
passing test. Check that skips are loud and that the gate says `⏭ skipped:`
with the command that would fix it.

## Writing the finding

State what the claim says, what the code or data actually supports, and the gap
in physical units. Then either fix it or carry it into
`reports/critical_review.md` §5 as a numbered item. Do not leave it only in a
commit message.

Self-correction is the house style — "the item pointed the wrong way" is a
normal section heading here, and a report that says what it does **not**
establish is stronger than one that does not.
