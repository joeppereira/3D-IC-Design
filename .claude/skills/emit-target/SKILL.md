---
name: emit-target
description: Add or change an EDA interchange emit target — the hook, the writer, the independent parser that validates it, and the tier/fidelity declaration. Use when touching integrations/ or emitting any vendor format.
---

# Adding an interchange target

The layer's whole claim to trustworthiness is one rule: **a round-trip through
our own writer and our own reader proves only that the two agree.** If both
share a misreading of the spec, they agree and are both wrong. So every format
is read back by an implementation nobody here wrote.

## The four pieces

1. **Writer** — `integrations/interchange/<fmt>_io.py` with `write()`, `read()`
   and `validate()`. `validate()` returns `Finding` objects, not booleans.
2. **Hook** — a `@register`ed `VendorHook` subclass in
   `integrations/vendors/<vendor>.py`, declaring `vendor`, `tool`, `requires`,
   and overriding `emit()` and `validate()`.
3. **Independent validation** — a test in
   `tests/integrations/test_external_parsers.py` that hands the artifact to a
   foreign parser.
4. **Provenance** — every file carries a header from `base.provenance()`:
   run id, git sha, design-record hash, generator, fidelity, claim limit.

## Picking the foreign reader

| Format | Reader | Status |
| :--- | :--- | :--- |
| GDSII | `gdstk` | installed |
| LEF/DEF | `klayout` | installed |
| Touchstone | `scikit-rf` | installed |
| Liberty | `liberty-parser` | installed |
| SPICE | `ngspice` | installed — it **runs** the deck |
| Surrogate | PhysicsNeMo + `onnx`/`onnxruntime` | optional |
| SPEF | — | **none exists in Python**; needs OpenROAD or PrimeTime |
| IBIS | `ibischk7` | licence-gated download; an owner action |

If no independent reader exists, say so in the spec's §10 rather than letting a
round-trip test stand in for one.

## Declaring the tier honestly

`integrations/base.py` defines the ladder, and it is not decorative:

- `T0` — written, and read back by an independent parser. **This is the ceiling
  today.**
- `T1` — a licensed vendor tool loaded it cleanly. **Never reached.**
- `T2` — vendor result compared, error band published. **Never reached.**
- `T3` — sign-off. Permanently out of scope.

Also declare the **fidelity** of the upstream data: `MEASURED`, `FIELD_SOLVED`,
`SURROGATE`, `SYNTHETIC`. A synthesised Touchstone is `SYNTHETIC` even when it
is passive, causal and reciprocal. Emitting prints these as warnings — that is
intended, not noise to suppress.

**Calibration derived from our own output is refused by design** (`correlate.py`).
Do not add a path around it.

## Do not describe behaviour the emitter does not have

`write_primesim` once advertised "per-ROI temperature injection" while emitting
three identical comment lines, because `GEMINI.md` asserted the capability and
the docstring cited the spec. Describe what the function writes. If a capability
is planned, name what it would take — for per-instance thermal injection that is
a `dtemp` per instance, which ngspice honours and is therefore T0-verifiable
here before any licence is involved.

## Verify

```bash
python -m integrations.cli emit --target <vendor>:<tool>
python -m integrations.cli verify            # cross-consistency
./regression_suite/run_interchange_qualification.sh
python .claude/hooks/claim_lint.py integrations/ reports/
```

`verify` reports **1 known error** — the 1 TB memory module whose die hierarchy
contains no memory die. That is a design-data decision, not a code bug, and it
fails identically on every commit. Do not "fix" it by editing the checker.
