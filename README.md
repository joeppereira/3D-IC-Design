# 3D IC Designer: Autonomous Silicon Architect (V2.0)

This repository implements a state-of-the-art **Autonomous Silicon Architect** for 3D IC design. It automates the transition from high-level architectural intent to physically validated layouts using a self-learning loop grounded in 3D physics.

---

## 1. Overall Product Goal
The primary objective is to design a **1000 GB (1TB) CXL 3.1 Switch System-on-Package (SoP)** optimized for AI inference (KV-Cache offloading). 

### Key Specifications:
*   **Capacity**: 1 TB Shared Memory Pool (8x 128GB LPDDR5X Expanders).
*   **Metadata Path**: 3D-Stacked SRAM Search Die via Hybrid Bonding (Cu-to-Cu).
*   **Throughput**: 
    *   SRAM-Switch: ~4 TB/s (Zero-latency lookup).
    *   DRAM-Pool: 1 TB/s aggregate (8x UCIe x16).
    *   XPU-Return: 1.6 Tb/s (8x 224G RDMA links).
*   **Physical Constraints**: 
    *   Target pJ/bit < 6.0.
    *   Thermal Junction Temperature ($T_j$) < 105°C.

---

## 2. The Design Flow (Autonomous Pipeline)

### Phase 1: Intent to Formal Specification
Converts natural language architectural goals into machine-readable JSON specs with validated physical constraints.
*   **Inputs**: Performance targets, lane counts, material preferences.
*   **Output**: `configs/formal_spec.json`.

### Phase 2: Pareto Surface Generation & Selection
Executes a massive sweep of package variations to identify the "Golden Options."
*   **Architectures**: CoWoS-S, 3D Heterogeneous, Stacked SoP (Diamond/Glass), Co-Packaged Optics (CPO), Wafer-Scale.
*   **Optimizer**: Uses Gradient-Enhanced Pareto Acceleration (GEPA) to navigate the trade-offs between Thermal Jitter, Area, and Manufacturing Cost.
*   **Output**: `reports/pareto_dashboard.html`.

### Phase 3: Detailed Design & Sign-off
Performs high-fidelity physics validation on the selected optimal design.
*   **Thermal**: 3D Finite Difference Method (FDM) solver handles the "Thermal Chimney" effect and models Backside PDN (BSPDN) / Liquid Cooling.
*   **Signal Integrity**: 112GHz Nyquist scaling for 224G PAM4 BER sign-off, accounting for Material Permittivity (Flyover/Megtron 7) and DSP Gain.
*   **Layout**: Exports a validated floorplan Tcl script for OpenROAD synthesis.

---

## 3. V2 Autonomous Framework (Self-Learning)
Version 2 implements a **Reinforcement Learning from Physical Feedback (RLPF)** loop.
*   **The Controller**: Gemini CLI acts as the architect.
*   **The Environment**: The physics engines (`serdes_architect`) and surrogate models (`physics_accelerated`).
*   **The Reward**: The agent is "punished" for thermal violations and "rewarded" for maximizing throughput-to-power ratios, naturally discovering advanced strategies like **BSPDN** or **Flyover Cables**.

---

## 4. Usage Instructions

### Pre-requisites
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch numpy pandas matplotlib plotly
```

### Run Full Design Cycle (Single Spec)
```bash
./run_full_cycle.sh configs/formal_spec.json
```

### Run 20-Point Pareto Batch Analysis
```bash
./run_pareto_matrix.sh
# Then generate report
python3 serdes_architect/scripts/harvest_pareto_data.py
python3 serdes_architect/src/pareto_visualizer.py
```

### Aggregate All Batch Results
```bash
python3 aggregate_results.py
```

---

## 5. Physics Model Calibrations
*   **Thermal**: Calibrated for 200W SoP on a 15x15mm die with Convective Heat Sink models.
*   **Link SI**:
    *   **Forwarded Clock**: Bonus UI for <50mm (correlated jitter tracking), Penalty for >100mm (skew drift).
    *   **224G DSP**: Explicitly models ADC-DSP Gain (+15dB) required to close the 224G link budget.
    *   **Materials**: Accurate 112GHz loss profiles for FR4 (10dB/in), Megtron 7 (2.5dB/in), and Flyover Twinax (0.45dB/in).

---

**Repository**: `https://github.com/joeppereira/3D-IC-Design`
**Author**: Autonomous Silicon Architect (Gemini CLI)
