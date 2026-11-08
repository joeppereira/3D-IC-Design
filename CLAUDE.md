# Working in this repository

3DIC-X is an architectural explorer for 3D IC / heterogeneous modules: physics
surrogates, a multi-objective search over them, and an interchange layer that
hands results to EDA flows.

This file records conventions **already enforced** by the tests, the gates and
the code — it is a description, not an aspiration. Where a rule has a mechanism,
the mechanism is named. If you find a rule here that the code does not enforce,
that is a defect in this file.

> `GEMINI.md` is a **superseded** Gemini-CLI-era spec, kept for history. Do not
> treat it as authoritative: several of its claims are contradicted by the
> measured reports (see its header). `.gemini/` and `.geminiignore` are not read
> by Claude Code.

---

## 1. The rules that matter most

**Measure before you optimise.** The highest-value move in this repo's history
was a ten-minute measurement that redirected two hours of work:
`vertical_mesh.md` §1 found the surrogate's discretisation error was *vertical*
when the to-do item assumed it was in-plane. Before committing to an expensive
change, measure which term dominates.

**Judge by decisions changed, not by error metrics.** An RMSE improvement that
does not move a ranking, a Pareto front or a feasibility verdict is not a
result. `rank_churn.py` exists to ask whether a correction acts *differentially*
across candidates; `fidelity_integration.md` §9 lists "correcting outputs rather
than parameters" as a failure mode precisely because it is order-preserving and
therefore decision-neutral.

**Every emitted format is read back by an implementation nobody here wrote.**
A round-trip through our own writer and our own reader proves only that the two
agree; if both share a misreading of the spec, they agree and are both wrong.
Hence gdstk for GDSII, klayout for LEF/DEF, scikit-rf for Touchstone,
liberty-parser for Liberty, ngspice for SPICE, PhysicsNeMo + onnxruntime for the
surrogate. See `requirements.txt` and `tests/integrations/test_external_parsers.py`.

**Every claim names its tier.** `integrations/base.py` defines the ladder and
the emitters print it:

| | |
| :--- | :--- |
| `T0` | standard file written, read back by an independent parser |
| `T1` | a licensed vendor tool loaded it cleanly |
| `T2` | vendor high-fidelity result compared, error band published |
| `T3` | sign-off — permanently out of scope |

**Nothing above T0 has ever been reached.** No licensed tool has opened an
artifact from this repository. Do not write prose that implies otherwise.

**Every artifact declares the fidelity of the data behind it** —
`MEASURED`, `FIELD_SOLVED`, `SURROGATE`, `SYNTHETIC` (`base.py`). A synthesised
Touchstone is `SYNTHETIC` even though it is passive, causal and reciprocal.

**Calibration derived from our own output is refused by design.** Fitting our
model to our model's predictions is circular; `correlate.py` rejects it.

**Kelvin, not percentages.** Report physical units with a stated basis. "~95%
accurate" is the kind of claim `GEMINI.md` makes and the reports do not.

**A missing dependency must never read as a pass.** Tests use
`@unittest.skipUnless(HAS_X, "... is unvalidated externally")`; gate scripts
print `⏭ skipped:` with the command that would fix it. Silence is not success.

**Gates assert; they do not print near the answer.** `run_physics_verification.sh`
carries a comment about this: a `tail -5` once swallowed the summary line so a
failing suite read as a passing gate. Grep for the verdict and exit non-zero.

## 2. Precedent worth knowing

`transient_roi_solver.py` was **deleted** from this repository for reporting a
fabricated peak alongside a "100,000× speedup". The concept was fine; the
missing interface checks were not. `submodel.py` is the replacement and it ships
both checks — exactness at matching resolution, and region independence.

The lesson the repo applies: a speedup claim without a correctness check against
something more trustworthy is a liability, not a feature.

## 3. Layout

| Path | |
| :--- | :--- |
| `physics_accelerated/src/` | solvers, surrogate, search, measurement scripts |
| `serdes_architect/src/thermal/` | FDM + transient solvers (`ThermalSolver`) |
| `integrations/` | EDA interchange: `canonical.py` → `vendors/` hooks → `interchange/` writers |
| `reports/` | one `.md` per finding, usually paired with a `.json` of the numbers |
| `regression_suite/` | the two gates |
| `tests/physics/`, `tests/integrations/` | unittest, 285 tests |

**Reports pair prose with data and cite the script that produced it.** A claim in
a `.md` should be traceable to a `.json` and a runnable command. Match that when
adding one.

## 4. Commands

```bash
./regression_suite/run_physics_verification.sh      # 8 stages, no licences
./regression_suite/run_interchange_qualification.sh # T0 + cross-consistency

.venv/bin/python -m unittest discover -s tests/physics -t .
.venv/bin/python -m unittest discover -s tests/integrations -t .

.venv/bin/python -m integrations.cli status          # design record + 17 targets
.venv/bin/python -m integrations.cli emit --target neutral:all
.venv/bin/python -m integrations.cli verify          # cross-consistency gate
```

**Known failure, do not "fix" blindly:** `verify` reports 1 error — the 1 TB
memory module whose die hierarchy contains no memory die. That is a design-data
decision, not a code bug. It fails identically on every commit.

## 5. Environment

* `.venv/` — Python 3.14, **torch pinned at 2.10.0**. The published physics
  numbers were measured against it; a resolver that moves torch underneath them
  invalidates a measurement record. Do not upgrade it casually.
* **Optional deps, deliberately not required**: `nvidia-physicsnemo`, `onnx`,
  `onnxruntime` (see `reports/physicsnemo_interop.md` §7). Without them 14 tests
  skip loudly.
* `ngspice` via Homebrew — not a pip package, and the one simulator available
  here. Use it: it is the only way to make a SPICE claim T0.
* **Trained weights and datasets are build artifacts.** `.gitignore` excludes
  `*.pt`, `results/` and `data/`, so a fresh clone has none. Scripts that need
  them must skip loudly, not crash. `golden_config.json` is force-included
  because it is an input, not an artifact.

## 6. Commit messages

House style: a subject that states the **finding**, not the activity, and a body
that explains what was measured and what it changed. Self-correction is normal
and belongs in the message. Examples from the log:

```
Close item 11: the discretisation error was vertical, and the item pointed the wrong way
Carry the structural correction as a band, and measure that it is not an offset
Add the section the previous commit message claimed
```

**No trailers.** Do not append `Co-Authored-By` or any tool attribution.

Branch for substantial work; a purely additive change with both gates green may
go to `main` directly.

## 7. Open items

`reports/critical_review.md` §5 is the authoritative to-do list — a standing
adversarial audit of which claims the code supports and which it does not. Read
it before claiming something works.

Two known, documented defects not yet fixed:

* **The surrogate's spectral convolution is circular, the die's sides are
  adiabatic.** A macro on the die edge produces +13.6 K of phantom temperature
  on the opposite edge (`reports/physicsnemo_gap_review.md` §1). Fix before
  making path-level thermal claims.
* **`spice_io.write_primesim` emits one global `.temp`.** Per-instance thermal
  injection needs `dtemp`, which ngspice honours and which is therefore
  T0-verifiable today.
