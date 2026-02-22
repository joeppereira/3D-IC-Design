# 📦 Assembly & Packaging Specification (3D-SoP)

This document defines the physical constraints for the assembly house and foundry for the 1TB CXL Switch.

## 1. Stackup Geometry
*   **Total Die Count**: 2 (Stacked) + 8 (Arranged).
*   **Total Package Size**: $35 \times 35 \text{ mm}$.
*   **Z-Height**: $1.2 \text{ mm}$ (from BGA to Top-die backside).

## 2. Interconnect Parameters
| Interface | Type | Pitch | Bump Count | Material |
| :--- | :--- | :--- | :--- | :--- |
| **Logic-SRAM** | Hybrid Bond | $5 \mu\text{m}$ | 8,192 | Cu-Cu |
| **Logic-Interposer** | Microbump | $25 \mu\text{m}$ | 45,000 | SnAg |
| **Interposer-Pkg** | C4 Bump | $130 \mu\text{m}$ | 12,000 | Lead-free Solder |

## 3. Materials & CTE Matching
*   **Interposer**: Silicon ($2.6 \text{ ppm}/^\circ\text{C}$).
*   **Substrate**: Low-Loss Organic (Megtron 7 or equivalent).
*   **Encapsulant**: High-thermal conductivity underfill ($k > 1.5 \text{ W/mK}$) to mitigate the Thermal Chimney effect.

## 4. Mechanical Constraints
*   **Die Thinning**: Switch die thinned to $50 \mu\text{m}$ to minimize TSV aspect ratio.
*   **Warpage Control**: Stiffener ring mandatory on the $35\text{mm}$ package to prevent BGA lift during $260^\circ\text{C}$ reflow.
