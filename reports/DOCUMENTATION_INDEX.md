# 🗂️ Master Documentation & Sign-off Index: Search King 1TB CXL SoP

This index tracks the mandatory documents required for fab qualification and investor due diligence.

## 📁 1. Project Management & Spec
*   [README.md](../README.md): High-level project summary.
*   [GEMINI.md](../GEMINI.md): Living spec and autonomous reasoning anchor.
*   [configs/formal_spec.json](../configs/formal_spec.json): Machine-readable constraints.

## 📁 2. Architectural & Physical Design (Tape-out Ready)
*   [reports/architectural_spec.md](architectural_spec.md): Block-level functional and power spec.
*   [reports/assembly_packaging_spec.md](assembly_packaging_spec.md): Hybrid bond and substrate material definition.
*   [reports/clocking_jitter_spec.md](clocking_jitter_spec.md): Timing H-tree and jitter budget allocation.
*   [reports/connectivity_pinout.md](connectivity_pinout.md): Die-level macro placement.
*   [serdes_architect/scripts/floorplan.tcl](../serdes_architect/scripts/floorplan.tcl): OpenROAD floorplan commands.

## 📁 3. Electrical & Signal Integrity (Foundry Sign-off)
*   [reports/comprehensive_signoff_dossier.md](comprehensive_signoff_dossier.md): The Master Sign-off (Area, PI, SI, Thermal).
*   [reports/link_verification_margins.md](link_verification_margins.md): Per-link exhaustive testing & SNR report.
*   [reports/functional_simulation_report.md](functional_simulation_report.md): RTL logic verification trace.
*   [reports/search_king_final_eye.png](search_king_final_eye.png): 224G SI proof.
*   [reports/sensitivity_analysis.md](sensitivity_analysis.md): Sensitivity levers.
*   [regression_suite/run_v1_qualification.sh](../regression_suite/run_v1_qualification.sh): System integrity test suite.

## 📁 4. Multi-Objective Analysis
*   [reports/pareto_dashboard.html](pareto_dashboard.html): Interactive trade-off explorer.
*   [reports/pareto_data.csv](pareto_data.csv): Raw data points for 20-point sweep.

---
**Status**: 100% Documents Generated. Pending: DOC-01 (Full Arch Spec) and DOC-09 (Detailed Test Plan).
