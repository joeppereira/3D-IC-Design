---

## 5. Architectural Boundaries & Accuracy
The Autonomous Silicon Architect is designed for **High-Fidelity Exploration**. Users must adhere to the following boundary constraints:
*   **Voxel Logic**: The 3D-FDM solver uses a $16 \times 16$ grid. It is optimized for **Global Heat Flux** but does not capture localized transistor-level self-heating or electromigration.
*   **Sign-off Status**: All outputs are **Verification Checklists**. This tool qualifies architectural intent but does not replace foundry-certified golden EDA suites.
*   **RC Feedback**: Extraction is performed on the **Global Routing Grid (M7/M10)**. Local cell-level parasitics are modelled via 3nm node heuristics.

---

## 6. Physics Model Calibrations
*   **Thermal**: Calibrated for 200W SoP on a 18x18mm die with Convective Heat Sink and BSPDN liquid cooling models.
*   **Link SI**:
    *   **Forwarded Clock**: Bonus UI for <50mm (correlated jitter tracking), Penalty for >100mm (skew drift).
    *   **224G DSP**: Explicitly models ADC-DSP Gain (+18dB) required to close the 224G link budget over Flyover Twinax.
    *   **Materials**: Accurate 112GHz loss profiles for FR4 (10dB/in), Megtron 7 (2.5dB/in), and Flyover Twinax (0.45dB/in).

---

**Repository**: `https://github.com/joeppereira/3D-IC-Design`
**Author**: Autonomous Silicon Architect (Gemini CLI)

