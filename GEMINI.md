> # ⚠️ SUPERSEDED — historical document, not a specification
>
> This was the Gemini-CLI-era "living spec". It is **no longer authoritative**
> and is kept only for history. For how this repository actually works see
> [`CLAUDE.md`](CLAUDE.md); for what it has actually measured see
> [`reports/critical_review.md`](reports/critical_review.md).
>
> Claims below that the repository's own measurements contradict:
>
> | Claimed here | Measured |
> | :--- | :--- |
> | "Level 2: 1µm Global", "Level 3: 50nm ROI" (§5) | That mesh **was never run**. The real study is [`mesh_convergence_audit.json`](reports/mesh_convergence_audit.json) — 12/24/48 grid refinement, GCI 0.081%. |
> | ROMs built "from high-fidelity Ansys Icepak data" (§4) | `thermal_rom.py` builds POD from **our own reference solver**. No licensed tool has ever opened an artifact from this repo — T1/T2 are empty. |
> | "Lobe B: JEPA-12L, 12-Layer CNN-MLP, ~420k parameters" | The surrogate is an **FNO**, 534,442 parameters ([`physicsnemo_interop.md`](reports/physicsnemo_interop.md)). |
> | Accuracy "~90% / ~95% / ~98%" (§5) | Unsourced. The house standard is kelvin with a stated basis. |
> | "Physics Injection: automatic injection of local `.TEMP` ... into SPICE sub-circuits" (§3) | `spice_io.write_primesim` emits **one global `.temp`** plus identical comment lines. Per-instance injection needs `dtemp` and is unbuilt. |
> | "RLPF loop verified ... triggers QLoRA fine-tuning" (Status) | `.gemini/hooks/train-logic.sh` calls `serdes_architect/src/train.py`, **which does not exist**. |
> | "Regression Verification: Suite v1.0 PASSED" (Status) | The interchange cross-consistency gate **fails with 1 error**, by documented design decision. |
>
> Everything below this line is unedited.

---

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

### 4. Mathematical Solvers (ROM & PINN)
To achieve millisecond-latency with 95%+ accuracy, the system utilizes two core mathematical technologies:

*   **Reduced-Order Models (ROMs)**: Using **Proper Orthogonal Decomposition (POD)**, we extract the dominant thermal modes from high-fidelity Ansys Icepak data. This "compresses" the complex FEA mesh into a lightweight state-space model that runs in the browser.
*   **PINNs (Physics-Informed Neural Networks)**: Our JEPA head incorporates the **Heat Equation** into its loss function:
    *   $L_{phys} = \| \nabla \cdot (k \nabla T) + q - \rho c_p \frac{\partial T}{\partial t} \|^2$
    *   This ensures that the Architect's "intuition" is physically clamped to the laws of thermodynamics, preventing non-physical heat predictions.

*   **Accuracy Recognition**: Acknowledge that the internal PINN and FDM solvers are surrogates for architectural discovery.
*   **Verification Language**: Use "Exploratory Verification" or "Architectural Pass" instead of "Qualified" or "Sign-off."
### 5. Multi-Level Fidelity Alignment (Ansys Strategy)
3DIC-X utilizes a three-tier solver architecture to balance discovery speed with physical rigor:

| Fidelity Level | Engineering Task | Resolution | Accuracy | Latency |

| :--- | :--- | :--- | :--- | :--- |

| **Level 1: Architectural** | Early-stage Pareto sweeps. | 1mm Tiles | ~90% | **< 5 ms** |

| **Level 2: Exploratory** | Shattered Macro validation. | 1µm Global | ~95% | **~50 ms** |

| **Level 3: Pre-Validation** | Lead Candidate optimization. | 50nm ROI | ~98% | **~150 ms** |



**Note**: Final foundry-certified sign-off (Ansys Production) remains the definitive verification stage after Level 3 completion.



---



## 📊 Current Status: Ready for Milestone #6

*   **Web-Native Pivot**: Architecture defined for WebGPU local inference and Wasm physics (Heatwave-lite).

*   **Self-Learning Active**: RLPF loop verified. Agent autonomously detects design failures and triggers QLoRA fine-tuning.

*   **Expert Fine-tuned**: Gemini 3.1 Pro intuition updated with SI/PI mitigation policies.

*   **Regression Verification**: Suite v1.0 PASSED.
