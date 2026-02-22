# 🚀 Living Spec: Data Center "Search-Switch" (v2 Unified Expert)

## 🏗️ Expert Domains
*   **Fabric**: PCIe 5-7, CXL 3.1, UCIe 2.0, UALink 200G.
*   **Physical**: OpenROAD, 3D-FDM Thermal, Hardened IR-Drop, MCMM Sign-off.
*   **Security**: SPDM 1.2+, DICE, Caliptra RoT.

---

## 🎯 Hardened Physics Guardrails (Mandatory)

### 1. Power Integrity (IR-Drop Hardening)
*   **Zero-Tolerance**: 0.00% IR-drop results are considered "System Failures."
*   **Resistivity**: All models must use 3nm thin-film copper conductivity ($\sigma ≈ 5.0 \text{ S/m}$) for global PDN.
*   **Scaling**: Voltage droop must account for micron-scale distance traverses and current crowding.

### 2. Signal Integrity (Jitter Ceiling)
*   **Eye Cap**: Maximum Eye Width is capped at **0.65 - 0.70 UI** to account for deterministic jitter ($Dj$) and reference clock noise.
*   **SNR Tax**: Low-voltage signaling (0.3V - 0.8V) must apply a logarithmic SNR tax based on 1.0V reference.

### 3. Industry-Standard Sign-off
*   **Reports**: Every design must output a "Silicon & Package Sign-off" dossier including:
    *   **Assembly**: Bump pitch, hybrid bond alignment, and substrate material.
    *   **Architecture**: Logic-SRAM connectivity and power distribution.
    *   **Link Verification**: Power, Area, and Margin for every discrete link.
    *   **Test Plan**: BIST, Scan, and Loopback coverage.
    *   **Challenged Assumptions**: A critical self-critique of design choices.

---

## 🔄 Self-Learning Execution Loop
1.  **Ingest Spec** → 2. **Pareto Sweep** → 3. **Physics Sign-off** → 4. **Self-Critique & Fix**.

---

## 📊 Current Status: Ready for Milestone #5
*   **Self-Learning Active**: RLPF (Reinforcement Learning from Physical Feedback) loop verified. Agent autonomously detects design failures and triggers QLoRA fine-tuning.
*   **Expert Fine-tuned**: Gemma 3 (4B) intuition updated with SI/PI mitigation policies (Flyover & Power Die).
*   **Core Physics**: 12-layer JEPA latent space established for zero-latency thermal reasoning.
*   **Qualification**: Regression Suite v1.0 PASSED.
