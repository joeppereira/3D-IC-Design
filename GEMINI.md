# 🚀 Living Spec: Data Center "Search-Switch" (v2 Unified Expert)

## 🏗️ Expert Domains
*   **Fabric**: PCIe 5-7, CXL 3.1, UCIe 2.0 (A/S), BoW (Bunch of Wires), HDI/HBW.
*   **Physical**: OpenROAD, 3D-FDM Thermal (Heatwave style), Hardened IR-Drop, MCMM Qualification.
*   **EDA Tools**: Smart Netlist Exporter (SPICE), CILD (Impedance Aware), VTF Analyzer.
*   **Security**: SPDM 1.2+, DICE, Caliptra RoT.

---

## 🎯 Hardened Physics & EDA Guardrails (Enterprise Grade)

### 1. Chiplet PHY & EM Design (Keysight W3650B Level)
*   **UCIe 2.0 A/S**: Support for Advanced (A) and Standard (S) packages with unique noise floors.
*   **BoW (Bunch of Wires)**: Model for low-cost organic substrate chiplet interfaces.
*   **Forward Clocking**: Measurement of Voltage Transfer Function (VTF) and phase-tracking correlated jitter.
*   **CILD**: Controlled Impedance Line modeling for all interposer and PCB traces.

### 2. Electrothermal (ETH) & Device Modeling
*   **Heatwave Logic**: Resolve fine temperature variations between layers and localized self-heating impact on device mobility.
*   **Device Calibration**: Mathematical model adjustment (MBP/MQA style) based on simulated vs. measured V/I curves.

### 3. Physics-Informed EDA (Smart Netlist)
*   **Netlist Pruning**: Large flat netlists must be pruned into "Smart Simulation Decks."
*   **ROI Detail**: RC extraction and transistor-level detail for "Hotspots" (ROIs).
*   **Physics Injection**: Automatic injection of local `.TEMP` and `.VDD` tags into SPICE sub-circuits based on 3D-FDM predictions.

---

## 🔄 Self-Learning Execution Loop
1. **Ingest Intent** → 2. **Pareto Sweep** → 3. **Smart Netlist Export** → 4. **SPICE/nspice Validation** → 5. **Self-Critique**.

---

## 📊 Current Status: Ready for Milestone #6
*   **Enterprise EDA**: Support for Smart Netlist Pruning and Physics Injection established.
*   **Standards**: Integrated UCIe 2.0 A/S and BoW.
*   **Hybrid Model**: Local JEPA head calibrated for ETH heating effects.
