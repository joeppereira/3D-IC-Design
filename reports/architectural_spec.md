# 🏗️ Architectural Specification: Search King 1TB CXL Switch

## 1. System Overview
The Search King is a 3D-Stacked System-on-Package (SoP) designed for high-performance AI inference. It integrates a dedicated metadata search engine directly above the CXL logic fabric to minimize latency.

## 2. Die Hierarchy
### 2.1 Logic Die (Die 0 - 3nm GAA)
*   **Fabric**: CXL 3.1 Dual-Port Switching.
*   **RDMA Engine**: 1.6 Tb/s packet encapsulation.
*   **PHY Edge**: 16x UCIe 2.0 (DRAM side) + 16x PCIe 7.0/RDMA (External side).

### 2.2 SRAM Search Die (Die 1 - 3nm GAA)
*   **Capacity**: 1GB KV-Cache Tags.
*   **Interconnect**: 8,192 Hybrid Bonds ($5\mu m$ pitch) to Logic Die.
*   **Latency**: < 10ns lookup response.

## 3. Memory Map
*   **Local Pool**: 1000 GB Shared DRAM (8x LPDDR5X).
*   **Addressing**: CXL Type-3 Device managed via Port-Based Routing (PBR).
