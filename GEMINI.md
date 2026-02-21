# 🚀 Living Spec: 1TB CXL "Search-Switch" (v2 Hybrid Expert)

This file serves as the **anchor** for autonomous reasoning, ensuring design iterations respect Caliptra security, CXL 3.1 pooling, and 3D-IC physics.

## 🏗️ Repository Taxonomy
*   **/agent**: The Hybrid Expert Brain (12-layer JEPA + 4-bit LLM Reasoning).
*   **/modules/security/caliptra**: Git Submodule for Root-of-Trust.
*   **/modules/fabric**: Protocol logic for CXL 3.1, UALink 128G/200G, and RDMA.
*   **/engines/serdes_architect**: High-fidelity 3D FDM Physics Solver (Ground Truth).
*   **/project_memory**: Persistent Design Embeddings (Vector Store) & Session Checkpoints.

---

## 🎯 Architectural Constraints (The "Guardrails")

### 1. Security: Root-of-Trust (RoT)
*   **Hardware Identity**: All 1TB DRAM accesses must be validated via Caliptra-DICE attestation.
*   **Confidential Computing**: Implement CXL-TSP (Trusted Security Protocol) for TVM trust boundaries.
*   **Physical Isolation**: Caliptra Key Vault macros require a **250µm keep-out zone** from 224G SerDes lanes to mitigate EM side-channel attacks.

### 2. Fabric: High-Speed I/O
*   **Internal Link**: UCIe 2.0 (x16) to 8x DRAM Expanders.
*   **Linear Density Target**: >50 Gbps/mm (25µm pitch).
*   **External Link**: PCIe 7.0 (128G) and UALink 128G/200G.
*   **Loss Budget**: Max 35 dB. Force Megtron 7 material if channel >30 dB.
*   **Eye Margin**: Min 0.20 UI at $10^{-12}$ BER.

### 3. Physical & Thermal (3D-SoP)
*   **Thermal Chimney**: SRAM KV-Cache stacked on Switch Die via Hybrid Bonding ($10m$).
*   **Thermal Cap**: Max $T_j = 105°C$.
*   **PDN Strategy**: Mandatory **Backside PDN (BSPDN)** for the Switch Die to resolve $200W$ power density fail-points.

---

## 🔄 Self-Learning Execution Loop

### Phase #1: Intent-to-Spec
*   Ingest text request via Gemini CLI.
*   Pull RTL from `/modules/security/caliptra` and `/modules/fabric`.
*   Output `formal_spec.json`.

### Phase #2: JEPA Optimization
*   Map `formal_spec.json` into the 12-layer Voxel Grid.
*   Execute a 24-point Pareto Sweep across package variations (CoWoS-S vs. Hybrid Bond).
*   **Reward Function**: Maximize $(\text{Throughput} / \text{Power})$ while $T_j < 105°C$.

### Phase #3: OpenROAD Layout & Sign-off
*   Generate `.tcl` placement scripts for OpenROAD.
*   Perform Multi-Corner Multi-Mode (MCMM) tracking for CTS across PVT.
*   Verify final Eye Margins via `si_analyzer`.

---

## 🛠️ Tool Handshake Guidelines
*   **No Hallucinations**: If the JEPA predicts a thermal fail, the Agent MUST propose a physical mitigation (e.g., Diamond substrate) before proceeding.
*   **Stateless Recovery**: Save design "embeddings" to `/project_memory` after every successful run to enable continuous learning.
*   **LaTeX Usage**: Use LaTeX for formal physics/math (e.g., Skin Depth $\delta = \sqrt{\frac{2\rho}{\omega\mu}}$).

---

## 📊 Current Status: Ready for Milestone #3
*   **Expert Fine-tuned**: Gemma 3 (4B) successfully trained on `secure_fabric_v1` adapter.
*   **Security Anchored**: EM-aware keep-out zones ($250\mu m$) and Caliptra PQC thermal profiles integrated into JEPA-12L reasoning.
*   **Geometry Locked**: Pin-Out Map generated for 32-macro CXL die.
*   **Qualification**: Regression Suite v1.0 PASSED.
