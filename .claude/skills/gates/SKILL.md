---
name: gates
description: Run this repo's verification gates and interpret the output, including the one failure that is expected. Use before committing, when asked whether the repo is green, or when a gate fails and you need to know whether it is yours.
---

# Running and reading the gates

Four things to run, in increasing cost. None needs a licence.

```bash
# 1. claims (seconds)
python .claude/hooks/claim_lint.py
python evals/run_evals.py

# 2. unit tests (~3 min)
.venv/bin/python -m unittest discover -s tests/physics -t .
.venv/bin/python -m unittest discover -s tests/integrations -t .

# 3. the two gates (~5 min)
./regression_suite/run_physics_verification.sh
./regression_suite/run_interchange_qualification.sh
```

## What green looks like

| | Expected |
| :--- | :--- |
| `tests/physics` | `OK (skipped=14)` — 149 tests; 14 skip without PhysicsNeMo |
| `tests/integrations` | `OK` — 136 tests |
| physics gate | `PHYSICS VERIFICATION PASSED`, 8 stages |
| interchange gate | `T0 FORMAT QUALIFICATION : PASSED` **and** `CROSS-CONSISTENCY GATE : FAILED` |
| claim lint | 0 errors; a few warnings are tolerated |
| evals | `CLAIM EVALS PASSED` — drift findings print but do not fail |

## The expected failure

The interchange gate's cross-consistency stage reports **1 error**:

```
stack_coverage: assembly_packaging_spec.md documents 4 layers but
['dram_stack'] have no die in the emitted stackup (3 dies)
```

A 1 TB memory module whose die hierarchy contains no memory die. It is a
**design-data decision, not a code bug**, it is documented in `README.md` and
`reports/eda_vendor_integration_spec.md` §10, and it fails identically on every
commit. Do not silence the checker to make it pass.

To confirm a new failure is not yours, run the same command on a `main`
worktree and compare the error count:

```bash
git worktree add /tmp/mainwt main
(cd /tmp/mainwt && python -m integrations.cli verify 2>&1 | grep -c "^\[ERROR")
git worktree remove /tmp/mainwt
```

## Skips are not passes

Both gates skip loudly when an artifact is missing, because trained weights and
datasets are build artifacts — `.gitignore` excludes `*.pt`, `results/` and
`data/`, so a fresh clone has none. A stage printing `⏭ skipped:` has not run.
Read the skip reason before reporting the gate as green; it names the command
that would fix it.

## When adding a stage

Assert on the result and exit non-zero. Never print the verdict and hope a
reader notices: `run_physics_verification.sh` carries a comment about a
`tail -5` that once swallowed the summary line, so a failing suite read as a
passing gate.
