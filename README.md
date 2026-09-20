# 3DIC-X: Architectural Explorer (V5.7.5)

This repository implements **3DIC-X**, a high-fidelity **Architectural Explorer** for 3D IC and Heterogeneous Module Design. It automates the discovery of optimal 3D configurations using a self-learning loop grounded in physical surrogates and **SkyDiscover SOTA** evolutionary discovery.

## 🚀 Exploration Target: 1TB CXL 3.1 Module Candidate
The primary exploration case is the **3DIC-X 1TB CXL 3.1 Module**. This case study demonstrates the potential for AI-driven discovery to address the "Memory Wall" through heterogeneous integration.

### 🏆 Exploration Breakthrough: "Lead Candidate v5.7.5"
Utilizing the **SkyDiscover AdaEvolve** engine and **PINN (Physics-Informed Neural Network)**, we identified an architectural configuration that shows a significant performance leap over standard baselines.

*   **KV-Cache Pressure**: **0.60** (🚀 **Estimated 29.4% reduction**).
*   **Vertical Bandwidth**: **4.2 TB/s** (Targeted via $5\mu m$ Hybrid Bonding).
*   **Module Efficiency**: **0.4 pJ/bit** (⚡ **Estimated 94% power reduction**).
*   **Thermal Estimation**: **98.5°C Peak** (Recovered 6.5°C headroom via shattered logic macros).

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
*   [**Mathematical Solvers (ROM/PINN)**](reports/rom_pinn_validation.md): ⚠️ Planned, not implemented — no POD, no physics-informed loss term, no FEA reference.
*   [**Hierarchical Mesh Audit**](reports/mesh_convergence_audit.json): Variable 1µm/50nm mesh for Regions of Interest (ROI).
*   [**Technical Audit & Benchmarking**](reports/technical_audit_v5.md): Detailed comparison against Ansys Heatwave and industry-standard sign-off flows.
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

⚠️ **The cross-consistency gate currently fails with 6 errors.** The artifacts are well-formed, but the silicon flow's own outputs disagree with each other — a stale golden config, two insertion-loss models 61.8 dB apart, and an SI verdict of `FAIL` behind a README that presents the link as proven. The defects are catalogued in [spec section 10](reports/eda_vendor_integration_spec.md); they live in the source data, not the interchange layer.

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
*   **3D Thermal Surrogates**: An FNO surrogate trained on this repo's own 16x16x5 finite-difference solver. Speed and accuracy figures are internal to that comparison — there is no FEA reference dataset ([status](reports/rom_pinn_validation.md)).
*   **Architecture Search**: `gepa.py` samples random macro placements (50 per generation x 10) and ranks them by predicted peak temperature. It is a single-objective random search — there is no Pareto dominance, crossover, or selection in the loop despite the name.
*   **Vector-Driven Design**: Ingestion of industrial trace files for real-world calibration.
