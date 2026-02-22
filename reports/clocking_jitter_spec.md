# 🕒 Clocking Specification & Jitter Budget (v1.0)

This document defines the timing architecture and jitter allocation for the Search King 1TB CXL Switch.

## 1. Clock Distribution Architecture
The design utilizes a **Global H-Tree Topology** to ensure uniform phase alignment across the $18 \times 18\text{ mm}$ die.

*   **Primary Reference**: 156.25 MHz Low-Phase-Noise Differential Crystal.
*   **PLL Architecture**: 3nm Ultra-Low Jitter LC-VCO PLLs (Integrated into SerDes clusters).
*   **Clock Tracks**: G-S-G Shielded Metal 7/8 tracks to minimize electromagnetic coupling.

## 2. Jitter Budget Breakdown (224G PAM4)
Target Unit Interval (UI) at 224G = $8.9\text{ ps}$.

| Jitter Component | Symbol | Budget (fs) | Budget (UI) | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Random Jitter** | $Rj$ | 150 | 0.017 | PLL phase noise & thermal noise. |
| **Deterministic Jitter** | $Dj$ | 800 | 0.090 | ISI, Duty Cycle Distortion, and XTK. |
| **Reference Clock** | $Ref$ | 250 | 0.028 | Jitter from off-chip oscillator. |
| **Package Skew** | $T_{skew}$ | 450 | 0.050 | Differential pair length mismatch. |
| **Total Jitter** | $Tj$ | **1650** | **0.185** | Max budget at $10^{-12}$ BER. |

## 3. Protocol-Specific Requirements
### 3.1 UCIe 2.0 (Forwarded Clocking)
*   **Phase Tracking**: Correlated jitter tracking enabled for <10mm reach.
*   **Skew Matching**: Data-to-Clock skew must be matched to within $\pm 2\text{ ps}$ post-routing.

### 3.2 PCIe 7.0 / RDMA (CDR)
*   **CDR Loop Bandwidth**: 10 MHz to 20 MHz (Adaptive).
*   **Tracking**: Must track up to 400 ppm frequency offset between Host and Switch.

## 4. Clock Integrity Verification
*   **Post-Layout Simulation**: Mandatory Monte Carlo analysis across PVT corners (SS/FF, 0.72V to 0.88V, -40C to 125C).
*   **Duty Cycle Correction (DCC)**: Integrated DCC circuits required for every SerDes quad-lane cluster.
