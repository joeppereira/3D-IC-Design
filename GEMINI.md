# 🚀 Living Spec: Data Center "Search-Switch" (v2 Unified Expert)

This file anchors the autonomous reasoning for a unified Data Center architecture, ensuring multi-protocol compliance and physical sign-off.

## 🏗️ Expert Domains
*   **IO Fabric**: PCIe Gen 5/6/7, CXL 3.1, UCIe 2.0 (XSR/USR).
*   **Memory**: LPDDR5, LPDDR5X, LPDDR6.
*   **Data Path**: RDMA over NVMe, RDMA over CXL 3.1.
*   **Security**: SPDM (Security Protocol & Data Model), DICE (Device Identifier Composition Engine), Caliptra RoT.
*   **Physical Design**: OpenROAD (Floorplan, CTS, Global/Detail Route), 3D-FDM Thermal.

---

## 🎯 Protocol Guardrails

### 1. Security & Identity (SPDM/DICE)
*   **Attestation**: Mandatory SPDM 1.2+ measurement exchange for all CXL fabric devices.
*   **DICE**: Unique Device Secret (UDS) derivation required for each 3D-stacked die layer.
*   **Isolation**: SPDM control logic must be physically isolated from high-toggle RDMA engines.

### 2. High-Speed Physics (PCIe 7 / UALink)
*   **Reach**: Support XSR (<10mm), MR (<500mm), and LR (>1m with Flyover).
*   **Power**: Max link power targets: PCIe 7 (128G) < 8.0 pJ/bit; LPDDR6 < 1.2 pJ/bit.
*   **Clocking**: Unified support for Forwarded Clock (UCIe) and CDR (PCIe/RDMA).

### 3. Physical Synthesis (OpenROAD Aware)
*   **CTS**: Balanced H-tree for high-speed SerDes clock distribution.
*   **Routing**: Priority routing for 224G differential pairs with G-S-G shielding.
*   **Density**: 25µm bump pitch for UCIe 2.0 lateral links.

---

## 🔄 Self-Learning Execution Loop (V2 Autonomous)
*   **Phase #1**: Spec ingestion & Protocol Selection (PCIe vs CXL vs RDMA).
*   **Phase #2**: Multi-Objective Pareto Sweep (Cost vs Latency vs Thermal).
*   **Phase #3**: OpenROAD Layout (Floorplan -> CTS -> Route).
*   **Phase #4**: Sign-off (SI BER check & Thermal MCMM).

---

## 🛠️ Tool Handshake Guidelines
*   **No Hallucinations**: Agent MUST propose physical mitigations for any predicted thermal/SI failures.
*   **Stateless Recovery**: Save design "embeddings" to `/project_memory` after every successful run.
*   **LaTeX Usage**: Use LaTeX for formal physics/math (e.g., Skin Depth $\delta = \sqrt{\frac{2\rho}{\omega\mu}}$).

---

## 📊 Current Status: Ready for Milestone #4
*   **Unified Expert**: Support added for PCIe 5-7, LPDDR5-6, and SPDM/DICE.
*   **EDA Specialized**: Layout generator updated for CTS and Routing awareness.
*   **Expert Fine-tuned**: Gemma 3 (4B) trained on `secure_fabric_v1`.
*   **Qualification**: Regression Suite v1.0 PASSED.