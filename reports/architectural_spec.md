# 🏗️ Detailed Architectural Specification: Search King 1TB CXL Switch

## 1. Functional Block Breakdown (3nm GAA)
The CXL Switch Logic die contains the following mission-critical IP blocks:

| Block ID | Description | Gate Count (Est) | Power Density |
| :--- | :--- | :--- | :--- |
| **CXL-CORE** | CXL 3.1 Fabric Manager & Dual-port PBR | 350M | High |
| **RDMA-224** | 1.6 Tb/s RDMA Packetizer & NVMe Hook | 150M | Medium |
| **KV-LOOKUP** | Hashing Engine for SRAM-Stacked Tags | 120M | Very High |
| **SEC-ROT** | Caliptra-based Root-of-Trust & SPDM | 80M | Low |
| **L3-BUFFER** | 1.5 Gb internal SRAM cache | 150M | Medium |

## 2. Connectivity & Data Flow
### 2.1 Metadata Fast-Path (SRAM Stacking)
*   **Vertical Interface**: 8,192 Hybrid Bonds.
*   **Operation**: On a CXL.cache 'Key' request, the hashing engine generates a 48-bit address sent vertically to Die 1.
*   **Latency Target**: < 8.5ns round-trip.

### 2.2 Shared DRAM Pooling (8x LPDDR5X)
*   **Total Capacity**: 1024 GB.
*   **Interface**: 8x independent x16 UCIe 2.0 links.
*   **Interposer**: Silicon Interposer with 2.5um track spacing.

## 3. Power Management & Modes
*   **Active Mode**: 180W peak during full-speed RDMA injection.
*   **Low-Power State**: CXL Link-Down (L1.2) supported; VDDQ drops to 0.4V via AVS.