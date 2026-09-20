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

## 📁 5. Industrial Tool Integration (Handoff to Certified Flows)
*   [reports/eda_vendor_integration_spec.md](eda_vendor_integration_spec.md): Vendor hook spec — vendor-neutral interchange (DEF/LEF, GDS/OASIS, SPEF, Liberty, Touchstone, IBIS-AMI) plus Cadence / Synopsys / Siemens insertion points and the T0–T3 claim ladder.

---
**Status**: 100% Documents Generated. Pending: DOC-01 (Full Arch Spec) and DOC-09 (Detailed Test Plan).
