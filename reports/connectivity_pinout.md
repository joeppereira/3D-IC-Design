# 📍 Connectivity Pin-Out Map: CXL Switch Die (3nm GAA)

This map defines the physical placement of I/O macros to maximize lateral heat spreading and ensure Caliptra Root-of-Trust security isolation.

## 🏗️ Die Edge Distribution
*   **Die Size**: $15 \times 15\text{ mm}$
*   **Total Macros**: 32 (16 UCIe + 16 SerDes)

| Edge | Macro Type | Count | Pitch | Function |
| :--- | :--- | :--- | :--- | :--- |
| **NORTH** | PCIe 7.0 / RDMA | 8 | $1.5\text{ mm}$ | External Host/XPU Escape |
| **SOUTH** | PCIe 7.0 / RDMA | 8 | $1.5\text{ mm}$ | Network/Fabric Expansion |
| **WEST** | UCIe 2.0 (XSR) | 8 | $2.0\text{ mm}$ | DRAM Expander Links (Dies 0-3) |
| **EAST** | UCIe 2.0 (XSR) | 8 | $2.0\text{ mm}$ | DRAM Expander Links (Dies 4-7) |

## 🛡️ Security Isolation (Caliptra Keep-out)
*   **Caliptra RoT Macro**: Centered at coordinates `(7.5, 2.0)` (Near South edge).
*   **EM Guard-band**: $250\mu m$ keep-out zone enforced between Caliptra mailbox and RDMA SerDes Cluster #4.
*   **BSPDN Tap**: Dedicated Backside PDN vias placed directly under Caliptra PQC engine to mitigate ML-KEM thermal spikes.

## 🌡️ Thermal Optimization
*   **Staggered Firing**: Logic fabric alternates activity between North and South clusters to prevent vertical heat accumulation under the SRAM stack.
