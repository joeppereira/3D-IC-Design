# 🗂️ Master Documentation & Architectural Verification Index: 3DIC-X 1TB CXL SoP

This index tracks the mandatory documents required for architectural verification and design exploration.

## 📁 1. Project Management & Spec
*   [README.md](../README.md): High-level project summary.
*   [GEMINI.md](../GEMINI.md): Living spec and autonomous reasoning anchor.
*   [reports/full_soc_architecture_spec.md](full_soc_architecture_spec.md): Full SoC Spec (Every IP, Memory, and IO).
*   [configs/formal_spec.json](../configs/formal_spec.json): Machine-readable constraints.

## 📁 2. Architectural & Physical Design (Architectural Pass)
*   [reports/architectural_spec.md](architectural_spec.md): Block-level functional and power spec.
*   [reports/assembly_packaging_spec.md](assembly_packaging_spec.md): Hybrid bond and substrate material definition.
*   [reports/clocking_jitter_spec.md](clocking_jitter_spec.md): Timing H-tree and jitter budget allocation.
*   [reports/connectivity_pinout.md](connectivity_pinout.md): Die-level macro placement.
*   [serdes_architect/scripts/floorplan.tcl](../serdes_architect/scripts/floorplan.tcl): OpenROAD floorplan commands.

## 📁 3. Electrical & Signal Integrity (Architectural Verification)
*   [reports/architectural_verification_dossier.md](architectural_verification_dossier.md): The Master Architectural Pass (Area, PI, SI, Thermal).
*   [reports/link_verification_margins.md](link_verification_margins.md): Per-link exhaustive testing & SNR report.
*   [reports/functional_simulation_report.md](functional_simulation_report.md): RTL logic verification trace.
*   [reports/3dic_x_final_eye.png](3dic_x_final_eye.png): 224G SI proof.
*   [reports/sensitivity_analysis.md](sensitivity_analysis.md): Sensitivity levers.
*   [regression_suite/run_v1_qualification.sh](../regression_suite/run_v1_qualification.sh): System integrity test suite.

## 📁 4. Multi-Objective Analysis
*   [reports/pareto_dashboard.html](pareto_dashboard.html): Interactive trade-off explorer.
*   [reports/pareto_data.csv](pareto_data.csv): Raw data points for 20-point sweep.

## 📁 5. Physics Verification (measured)
*   [reports/rom_pinn_validation.md](rom_pinn_validation.md): Reference solver verified to 1e-9 °C against analytic conduction and 8e-12 on energy balance; grid-converged peak Tj 83.87 °C (GCI 0.081%); PINO λ-sweep.
*   [reports/multiobjective_search.md](multiobjective_search.md): NSGA-II verified on ZDT1; shattered-vs-monolithic headroom +37.02 °C confirmed on the reference solver; surrogate error at optimiser-selected designs and the trust guard that re-solves them.
*   [reports/mesh_convergence_audit.json](mesh_convergence_audit.json): The measured convergence study (replaces a fabricated one).
*   [reports/thermal_validation.json](thermal_validation.json): Surrogate vs reference at the designs the search selected.
*   [reports/surrogate_trust_report.json](surrogate_trust_report.json): The trust guard's output — every front member re-solved on the reference solver, the out-of-distribution flag and its in-distribution control, the network/mesh error split, and the ROM-vs-exact screen calibration.
*   [reports/surrogate_retraining.md](surrogate_retraining.md): The surrogate retrained on the distribution the optimiser actually searches — the new dataset, the first held-out numbers this project has published, old vs new on both distributions, and the λ sweep re-measured across seeds.
*   [reports/surrogate_retrain.json](surrogate_retrain.json): The retraining benchmark's full output.
*   [reports/pareto_front_nsga2.json](pareto_front_nsga2.json): The Pareto front, genomes, and hypervolume baseline.
*   [reports/rank_churn.json](rank_churn.json): What a vendor correlation could change — perturbation sweeps, churn thresholds, and the finding that an additive calibration cannot reorder a ranking.
*   [reports/vertical_mesh.md](vertical_mesh.md): The surrogate's discretisation error was vertical, not in-plane — measured before retraining, which redirected the work; z-refined labels take the total bias from +0.59 K to +0.08 K.
*   [reports/power_map_reality.md](power_map_reality.md): What a power map actually looks like — the floorplan the DEF emitter carries, plus a real OpenROAD/ASAP7 placed design, giving 50% of power in 15–19% of area and a measured +17…+21 °C for real structure.
*   [reports/submodel.md](submodel.md): What the 562 µm cell cannot see — region refinement with exactness and region-independence checks, and the finding that rearranging a macro's watts inside its own footprint moves the peak by +36 °C at fixed total power.
*   [reports/gradient_skew.md](gradient_skew.md): Clock skew caused by the temperature field — 10.9–28.1 ps across the feasible front against a ~25 ps CTS allowance, and the finding that peak Tj and skew rank designs differently (Kendall τ +0.72).
*   [reports/memory_attach.md](memory_attach.md): Memory Tj as the decision variable — stacked vs package-on-package vs side-by-side, in four cooling/lid configurations, with the feasible SoC power each affords.
*   [tests/physics/](../tests/physics/): the physics verification suite (`python -m unittest discover -s tests/physics -t .`).

## 📁 6. Critical Review & Honest Status
*   [reports/fidelity_integration.md](fidelity_integration.md): Design record — the fidelity ladder from compact model to meshed vendor tooling, what each coupling mechanism can buy, calibrate-vs-substitute, the two-timescale scheme for sub-ns margin against thermal transients, and how to tell whether fidelity bought anything.
*   [reports/critical_review.md](critical_review.md): Adversarial review from a new reader's perspective — claims checked against code, the 61.8 dB modeling error and its blast radius, what was fixed, what remains open, and what the project can defensibly claim today.

## 📁 7. Industrial Tool Integration (Handoff to Certified Flows)
*   [reports/eda_vendor_integration_spec.md](eda_vendor_integration_spec.md): Vendor hook spec — vendor-neutral interchange (DEF/LEF, GDS/OASIS, SPEF, Liberty, Touchstone, IBIS-AMI) plus Cadence / Synopsys / Siemens insertion points and the T0–T3 claim ladder. Section 10 records what is implemented.
*   [integrations/](../integrations/): The implementation — 17 emit targets, per-format readers, and the vendor-result correlation loop (`python -m integrations.cli status`).
*   [regression_suite/run_interchange_qualification.sh](../regression_suite/run_interchange_qualification.sh): T0 gate — format round-trips, Touchstone passivity/causality/reciprocity, and ngspice execution of the emitted deck. No vendor licenses required.
*   `python -m integrations.cli verify`: Cross-consistency gate — checks the emitted artifacts against the silicon flow's own outputs. **Currently failing with 6 errors**; the defects are catalogued in spec section 10 and live in the source data, not the emitters.

---
**Status**: 100% Documents Generated. Pending: DOC-01 (Full Arch Spec) and DOC-09 (Detailed Test Plan).
