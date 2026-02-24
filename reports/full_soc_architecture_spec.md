# 📄 Full SoC Architecture Specification: Search King (v1.0)
**Project**: 1000 GB CXL 3.1 AI-Inference Switch SoP
**Technology**: TSMC 3nm GAA (N3P)
**Package**: 3D Heterogeneous System-on-Package (SoP)

---

## 1. System Overview
The Search King is a high-bandwidth, low-latency memory orchestrator designed to solve the "Memory Wall" in Large Language Model (LLM) inference. It provides a unified 1TB DRAM pool with a 3D-stacked "Metadata Fast-Path" for zero-latency KV-cache lookups.

## 2. Die Hierarchy & Physical Geometry
The system consists of a 10-die assembly integrated via 2.5D and 3D technologies.

| Die | Role | Area | Technology | Connectivity |
| :--- | :--- | :--- | :--- | :--- |
| **Die 0** | **Logic Core** | $324 \text{ mm}^2$ | 3nm GAA | Central Switch Logic |
| **Die 1** | **Search Die** | $225 \text{ mm}^2$ | 3nm GAA | 3D Stacked (Top) |
| **Die 2** | **Power Die** | $324 \text{ mm}^2$ | 28nm/High-V | 3D Stacked (Bottom) |
| **Die 3-10**| **DRAM Expander**| $144 \text{ mm}^2$ | LPDDR5X | 2.5D Perimeter |

## 3. Internal & External I/O Specification
The SoC manages 32 high-speed physical macros partitioned across four die edges.

### 3.1 External System Links (Escape I/O)
*   **Host-to-Switch**: 16x PCIe 7.0 Lanes (128 GT/s).
    *   *Signaling*: Differential, 0.8V VDDQ.
    *   *Reach*: 800mm via Flyover Twinax.
    *   *Sign-off*: 0.48 UI Margin @ $10^{-12}$ BER.
*   **XPU-Return**: 16x RDMA Lanes (224 Gbps PAM4).
    *   *Signaling*: Differential, 0.75V AVS Optimized.
    *   *Reach*: 300mm via Flyover Twinax.
    *   *Sign-off*: 0.47 UI Margin with ADC-DSP.

### 3.2 Internal Chiplet Links (Fabric I/O)
*   **DRAM Interface**: 128x UCIe 2.0 Lanes (8 dies x 16 lanes).
    *   *Rate*: 64 GT/s PAM4.
    *   *Signaling*: Single-Ended (SE), 0.4V VDDQ.
    *   *Reach*: < 10mm Silicon Interposer.
    *   *Termination*: High-Z (Standard).

## 4. Memory Subsystem
### 4.1 Internal Memory (On-Die)
*   **L3 System Buffer**: 1.5 Gb SRAM integrated on Die 0 for CXL flit staging.
*   **KV-Cache Tags**: 1 GB SRAM on Die 1 (3D Stacked).
    *   *Interface*: 8,192 Hybrid Bonds ($5\mu m$ pitch).
    *   *Bandwidth*: 4.2 TB/s aggregate vertical throughput.

### 4.2 External Memory (Pooled)
*   **Capacity**: 1024 GB (1 TB).
*   **Type**: 8x LPDDR5X-8300 (LVSTL_03).
*   **Bus**: 512-bit total (64-bit per expander).

## 5. Logic IP Blocks & Functional Units
*   **CXL PBR Manager**: Port-Based Routing logic supporting CXL 3.1 fabrics. Manages memory IDs for the 1TB pool.
*   **RDMA Offload Engine**: Hardware-based packet encapsulation for direct GPU memory injection.
*   **KV-Search Engine**: Parallel hashing and tag-comparison logic for <10ns metadata lookups.
*   **Caliptra RoT**: Silicon Root-of-Trust providing DICE-based attestation and SPDM 1.2 identity.

## 6. Power & Thermal Constraints
*   **Peak Power (TDP)**: 180.0 W.
*   **PDN Strategy**: Vertical Power delivery via Die 2 (Power Die). 12,000 C4 bumps.
*   **IR-Drop Target**: < 1.0% (Verified: 0.42% with Power Die).
*   **Thermal Cap**: $105^\circ C$ Junction.
*   **Cooling**: BSPDN + Active Liquid Cooling Manifold.

## 7. Security Architecture
*   **Confidential Computing**: CXL-TSP encryption for all 1TB DRAM traffic.
*   **Physical Protection**: 250µm EM isolation zone around Caliptra key-vault.
*   **Identity**: DICE Unique Device Secret (UDS) per die layer.

---
**Approval Status**: 🟢 ARCHITECTURE FROZEN
**Sign-off Reference**: `reports/comprehensive_signoff_dossier.md`
