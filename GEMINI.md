# 🚀 Living Spec: Data Center "Search-Switch" (v2 Unified Expert)

This file anchors the autonomous reasoning for a unified Data Center architecture, ensuring multi-protocol compliance and physical sign-off.

## 🏗️ Expert Domains
*   **IO Fabric**: PCIe Gen 5/6/7, CXL 3.1, UCIe 2.0 (XSR/USR), **UALink 128G/200G**.
*   **Memory**: LPDDR5, LPDDR5X, LPDDR6.
*   **Data Path**: RDMA over NVMe, RDMA over CXL 3.1.
*   **Security**: SPDM 1.2+, DICE Attestation, Caliptra RoT.
*   **Physical Design**: OpenROAD (CTS, Routing, Floorplan), 3D-FDM Thermal.

---

## 🎯 Protocol Guardrails

### 1. Signaling & Modulation (PAM4/PAM2/NRZ)
*   **Single-Ended (SE)**: Default for LPDDR5/6 and parallel UCIe. Higher crosstalk penalty (6dB) vs Diff.
*   **Differential (Diff)**: Mandatory for PCIe 5-7, UALink, and SerDes RDMA.
*   **Modulation**:
    *   **NRZ/PAM2**: Optimized for latency in <10mm reaches.
    *   **PAM4**: Mandatory for 56G+ (PCIe 6/7, UALink) to manage Nyquist frequency.

### 2. High-Speed Physics (UALink 200G)
*   **UALink**: Optimized for XPU-to-XPU scaling. Requires < 5.0 pJ/bit link efficiency.
*   **200G/224G**: Forced Megtron 7 or Flyover Twinax for reaches > 100mm.
*   **Skew**: Forwarded Clocking restricted to < 50mm for 112G+ operations.

### 3. Physical Synthesis (OpenROAD)
*   **CTS**: Balanced H-tree for high-speed clock distribution.
*   **Routing**: G-S-G shielding for all 112G/224G differential pairs.

---

## 🔄 Self-Learning Execution Loop (V2 Autonomous)
*   **Phase #1**: Spec ingestion & Protocol Selection.
*   **Phase #2**: Multi-Objective Pareto Sweep (Cost/Lat/Thermal).
*   **Phase #3**: OpenROAD Layout (Grid-Aware Floorplanning).
*   **Phase #4**: Sign-off (SI BER & Thermal MCMM).
