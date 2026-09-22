# 3DIC-X: Architectural Explorer (V5.7.5)

This repository implements **3DIC-X**, a high-fidelity **Architectural Explorer** for 3D IC and Heterogeneous Module Design. It automates the discovery of optimal 3D configurations using a self-learning loop grounded in physical surrogates and **SkyDiscover SOTA** evolutionary discovery.

## 🚀 Exploration Target: 1TB CXL 3.1 Module Candidate
The primary exploration case is the **3DIC-X 1TB CXL 3.1 Module**. This case study demonstrates the potential for AI-driven discovery to address the "Memory Wall" through heterogeneous integration.

### 🏆 Exploration Breakthrough: "Lead Candidate v5.7.5"
Utilizing the **SkyDiscover AdaEvolve** engine and **PINN (Physics-Informed Neural Network)**, we identified an architectural configuration that shows a significant performance leap over standard baselines.

*   **KV-Cache Pressure**: **0.60** (🚀 **Estimated 29.4% reduction**).
*   **Vertical Bandwidth**: **4.2 TB/s** (Targeted via $5\mu m$ Hybrid Bonding).
*   **Module Efficiency**: **0.4 pJ/bit** (⚡ **Estimated 94% power reduction**).
*   **Peak Junction Temperature**: **83.87 °C**, grid-converged (GCI 0.081%) on a reference solver verified to 1.04e-9 °C against analytic 1D conduction — [the measurement](reports/mesh_convergence_audit.json). Shattered logic macros recover **37.02 °C** against the best monolithic placement — an exhaustive scan over both macros' positions, solved on the reference ([thermal_validation.json](reports/thermal_validation.json)); the earlier "6.5 °C headroom" was an unmeasured claim the same size as a modelling defect since fixed.

### 🧠 Triple-Brain Intelligence
The tool utilizes a 2026-era hybrid intelligence stack:
1.  **Expert Heuristics**: Zero-latency hardware standard validation.
2.  **Local Phi-3.5 Brain**: Private, WebGPU-accelerated reasoning.
3.  **Cloud Gemini Pro Brain**: Global strategic optimization and protocol compliance.
4.  **SkyDiscover Engine**: SOTA adaptive evolution (AdaEvolve) and strategy discovery (EvoX).

---

## 🏛️ Physical & Mathematical Foundation
3DIC-X exploration is grounded in high-fidelity industrial engineering principles:

*   [**Die Thinning & 3D Assembly**](reports/assembly_packaging_spec.md): Thinned 30µm/50µm silicon layers for thermal and TSV optimization.
*   [**Physics Validation (reference solver + PINO + POD ROM)**](reports/rom_pinn_validation.md): Grid-converged reference solver verified to **1e-9 °C** against analytic conduction; a physics-informed loss that cuts the PDE residual **50%** (held out, across seeds); POD-Galerkin ROM with **1.43 °C** worst held-out peak error.
*   [**Surrogate Retraining**](reports/surrogate_retraining.md): the surrogate retrained on the distribution the optimiser actually searches — held-out field RMSE **0.58 K**, and error at optimiser-selected designs **14.21 K → 1.33 K**.
*   [**Multi-Objective Search**](reports/multiobjective_search.md): NSGA-II verified on ZDT1; shattered-macro headroom of **+37.02 °C** confirmed on the reference solver (prediction and reference agree to 0.20 °C); every published design re-solved and distribution-checked by the [trust guard](reports/multiobjective_search.md#6-the-trust-guard).
*   [**Memory Attach Study**](reports/memory_attach.md): memory Tj as the decision variable — stacked / PoP / side-by-side, with the feasible SoC power each affords before the DRAM crosses its refresh knee, robust under ±50% on cooling and spreading.
*   [**Mesh Convergence Audit**](reports/mesh_convergence_audit.json): measured 12/24/48 grid-refinement study with Richardson extrapolation and a published GCI. (It is not the variable 1 µm/50 nm ROI mesh an earlier README described — that mesh was never run.)
*   [**Technical Audit & Benchmarking**](reports/technical_audit_v5.md): Detailed comparison against Ansys Heatwave and industry-standard sign-off flows.
*   [**Critical Review**](reports/critical_review.md): Adversarial audit of this repository — which claims the code supports, which it does not, and why.
*   [**EDA Vendor Integration Spec**](reports/eda_vendor_integration_spec.md): Hook architecture and interchange layer for handoff into Cadence, Synopsys, and Siemens flows.

### 🔌 EDA Handoff (implemented)
The `integrations/` package emits standard artifacts from the physics surrogates and reads vendor results back:

```bash
python -m integrations.cli status                       # design record + the 17 emit targets
python -m integrations.cli emit --target neutral:all    # DEF/LEF, GDSII, SPEF, Liberty, Touchstone, IBIS, SPICE
python -m integrations.cli emit --target cadence:celsius
python -m integrations.cli correlate --thermal celsius_temperature.csv   # vendor result -> error band
python -m integrations.cli verify                       # cross-consistency vs the silicon flow
./regression_suite/run_interchange_qualification.sh     # both gates, no licenses needed
```

Artifacts land in `results/handoff/<run_id>/` with a manifest, SHA-256 per file, and a provenance header declaring whether the data behind them is `SURROGATE` or `SYNTHETIC`. Every claim is currently **T0** (emitted and independently parsed); `T1`/`T2` require licensed vendor tools. Calibration derived from our own output is refused by design.

⚠️ **The cross-consistency gate currently fails with 1 error** (a 1 TB memory module whose die hierarchy contains no memory die — a design decision, not a code fix).  Five further defects found by that gate have been fixed; all are catalogued in [spec section 10](reports/eda_vendor_integration_spec.md) and [the critical review](reports/critical_review.md).

### 📖 Performance Documentation
*   [**Design Evolution**](reports/design_evolution_story.md): The journey from initial failure to the lead 3DIC-X candidate.
*   [**Technical Solution Recommendation**](reports/final_architectural_solution.md): Detailed breakdown of the recommended module configuration.
*   [**Power Efficiency Analysis**](reports/power_reduction_proof.json): Numerical estimation of potential vertical link savings.
*   [**SOTA vs Legacy Benchmarking**](reports/final_design_audit.json): Side-by-side comparison of discovery strategies.

## ⚠️ Architectural Scope & Sign-off Disclaimer
**3DIC-X is an architectural exploration platform.** 

*   **Internal Verification**: All results (Thermal, SI, PI) are generated using internal physics surrogates (FNO, ROM, PINN) intended for early-stage design discovery and Pareto optimization.
*   **No Final Sign-off**: This tool **does not provide final foundry sign-off**. "Architectural Pass" or "Verification" status within this tool indicates that a design candidate is viable for transition to industry-standard, foundry-certified golden sign-off suites (e.g., Ansys, Cadence, Synopsys, Siemens).
*   **Fabrication**: Never use 3DIC-X outputs for tape-out or fabrication without prior validation through certified sign-off flows.

---

## 🚀 Key Features
*   **224G/112G SerDes Optimization**: AI-driven SI/PI trade-offs for Next-Gen Fabrics.
*   **3D Thermal Surrogates**: A physics-informed neural operator (FNO + heat-equation residual), trained on macro layouts drawn as a superset of what the optimiser searches, with labels from a direct solve on the same discretisation. **Held-out** field RMSE **0.58 K**, and **1.33 K** mean error at optimiser-selected designs — down from 14.21 K, when 100% of the search space sat outside the training distribution ([the measurement](reports/surrogate_retraining.md)). Absolute temperatures are still reference-solver output rather than predictions: see [the trust guard](reports/multiobjective_search.md#6-the-trust-guard).
*   **Multi-Objective Architecture Search**: [NSGA-II](reports/multiobjective_search.md) (non-dominated sorting, crowding distance, SBX, polynomial mutation), verified against ZDT1's analytic front to **0.0037** mean distance and beating random sampling at equal budget (hypervolume 0.930 vs 0.908, front size 48 vs 24). Every front member is re-solved on the reference solver before publication (Kendall τ **0.996** against the surrogate's ranking, selection regret **0.00 °C**).
*   **Vector-Driven Design**: Ingestion of industrial trace files for real-world calibration.
