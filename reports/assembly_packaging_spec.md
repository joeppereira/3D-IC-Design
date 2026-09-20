# 🛠️ Assembly & Packaging Specification: 3DIC-X Module
**Project**: 1TB CXL 3.1 Heterogeneous Module (v5.7.5)
**Package**: 3D-SoP (System-on-Package)

---

## 1. Die Thinning & Hierarchy
To achieve 95%+ thermal correlation and maintain the 10:1 TSV aspect ratio, aggressive die thinning is applied across the stack.

| Die Layer | Thickness | Strategy | Physical Reasoning |
| :--- | :--- | :--- | :--- |
| **DRAM Stack** | **30 µm** | Ultra-Thinned | Reduces vertical $R_{theta}$ by 96% for liquid cooling path. |
| **KV-Search Die** | **50 µm** | Thinned | Enables high-density 2µm TSV grid. |
| **Logic Core** | **50 µm** | Thinned | Mandatory for **Backside PDN (BSPDN)** integration. |
| **Power Die** | **775 µm** | Full-Thickness | Mechanical support and vertical power distribution. |

## 2. Interconnect Parameters
*   **Vertical Interface**: $5\mu m$ Hybrid Bonding (Logic-to-Search).
*   **TSV Diameter**: $2.0 \mu m$ copper-filled.
*   **Aspect Ratio**: 10:1 (Verified for TSMC 3nm GAA N3P).
*   **BGA/C4 Grid**: $40 \mu m$ pitch for global power delivery.

## 3. Thermal Interface
*   **TIM Thickness**: $25 \mu m$.
*   **Cooling**: Backside Liquid Cooling Manifold + BSPDN bypass.