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

## 🧠 Hybrid Model Architecture (v2.5)
The system utilizes a dual-lobed architecture optimized for 10GB VRAM hardware.

### Lobe A: Reasoning Engine
*   **Global**: Gemini 3.1 Pro (Multi-protocol orchestration).
*   **Local**: **Phi-3.5 (3.8B)** 4-bit NF4 quantized.
*   **QLoRA Config**:
    *   **Rank/Alpha**: 64 / 128 (Scaling: 2.0).
    *   **Learning Rate**: $5 \times 10^{-5}$ (Precision Focus).
    *   **Optimization**: Paged AdamW with Cosine Warmup.
*   **Role**: Handles architectural policy and RLPF fine-tuning.

### Lobe B: Physics Intuition (JEPA-12L)
*   **Structure**: 12-Layer CNN-MLP Encoder-Predictor.
*   **Parameters**: ~420k (Real-time inference).
*   **Role**: Zero-latency spatial prediction of 3D-FDM thermal and droop maps.

---

## 🔄 Self-Learning Execution Loop (RLPF)
1.  **Ingest Spec** → 2. **Pareto Sweep** → 3. **Physical Verification** (FDM/SI).
4.  **Failure Ingestion**: `agent/rlpf_ingestor.py` extracts numerical failures from real simulations.
5.  **Fine-tune**: Phi-3.5 learns the [Failure] -> [Mitigation] pair via local QLoRA.

---

## 📊 Current Status: Ready for Milestone #6
*   **Enterprise EDA**: Support for Smart Netlist Pruning and Physics Injection established.
*   **Standards**: Integrated UCIe 2.0 A/S and BoW.
*   **Hybrid Model**: Local JEPA head calibrated for ETH heating effects.
