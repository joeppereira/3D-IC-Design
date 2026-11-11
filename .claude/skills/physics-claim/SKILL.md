---
name: physics-claim
description: Make, measure and land a new physics claim in this repo — the measure-first procedure, the .md/.json pairing, and the gate wiring. Use when adding or changing any numerical claim about thermal, timing, parasitic or surrogate behaviour.
---

# Landing a physics claim

The repository's defects have all been claims that outran their measurement, so
the order below is not bureaucracy — it is the order that has caught things.

## 1. Measure what dominates, before you build anything

The highest-value move in this repo's history took ten minutes: `vertical_mesh.md`
§1 decomposed the surrogate's discretisation error and found it was **vertical**
when the to-do item assumed in-plane. In-plane refinement would have cost four
times the training and chased the smaller, noisier half.

So: before committing to the expensive change, measure which term dominates.
Write that measurement down even when it confirms the assumption.

## 2. Make it a script, not a session

The claim must be reproducible by someone who was not there:

- Put it in `physics_accelerated/src/<name>.py` with a module docstring that
  states the **question**, not the method.
- Write results to `reports/<name>.json` — every number the prose will quote.
- Make the script runnable from the repo root with no arguments.

## 3. Check it against something more trustworthy

A number with no independent check is a liability. What counts here:

| Layer | Checked against |
| :--- | :--- |
| Surrogate (L1) | the reference solver, and PhysicsNeMo for the operator itself |
| Reference solver (L2) | analytic 1D slab conduction, global energy balance |
| ROM | held-out snapshots from the reference |
| Transient | the exact matrix exponential (`scipy.linalg.expm`) |
| Search | ZDT1, whose front is known analytically |
| A submodel/ROI | exactness at matching resolution **and** region independence |

A speedup figure with no correctness check beside it is the pattern that got
`transient_roi_solver.py` deleted. Do not quote one alone.

## 4. Ask whether it changes a decision

`reports/rank_churn.json` exists for this. An improvement that moves no
ranking, no Pareto membership and no feasibility verdict is not a result — say
so plainly rather than quoting the delta. Re-solving the published front with
both versions and comparing the non-dominated sets is the standard test.

## 5. Write the report

`reports/<name>.md`, matching the house pattern:

- Header: status, date, the code, and a **Reproduce** block with real commands.
- Lead with what was found, including when it contradicts the item you were
  given — "the item pointed the wrong way" is a normal section heading here.
- **Kelvin, not percentages.** Every quantity gets a unit and a basis.
- Say what the result does *not* establish. Every strong report here has that
  section.

## 6. Verify and wire it in

```bash
python .claude/hooks/claim_lint.py reports/<name>.md physics_accelerated/src/<name>.py
python evals/run_evals.py --only drift     # prose must match the cited .json
./regression_suite/run_physics_verification.sh
```

The drift eval will tell you if you quoted a number the JSON does not contain.
Fix the data, not the prose, when the claim is true and the data is thin — add
the measurement to the script's output.

If the claim is load-bearing, add a stage to
`regression_suite/run_physics_verification.sh`. Gates must **assert** and exit
non-zero, never print near the answer: a `tail -5` once swallowed a summary
line so a failing suite read as a passing gate.
