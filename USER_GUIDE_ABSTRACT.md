# 🧭 User Guide Abstract: The Autonomous Architect Journey

Welcome to the **Autonomous 3D-IC Designer**. If you are a Silicon Architect who does not know what to expect, follow this 4-step path to move from a high-level idea to a validated GDSII stream-out.

## 1. The Entry Point: Setting Intent
The system starts with your "Intent." You do not need to be an EDA expert to begin.
*   **Where to look**: Read the [README.md](README.md) and [GEMINI.md](GEMINI.md).
*   **What to do**: Edit or provide a new intent (e.g., "128G AI Retimer") to the Gemini CLI. The system will autonomously generate a [configs/formal_spec.json](configs/formal_spec.json).
*   **User Experience**: You define the *what* (Bandwidth, Reach, Thermal Cap), the Agent determines the *how* (Package type, Material, Voltage).

## 2. The Creative Phase: Exploring Trade-offs
Once the spec is locked, the agent sweeps the design space to find the optimal balance of cost, power, and physics.
*   **Where to look**: Open [reports/pareto_dashboard.html](reports/pareto_dashboard.html) in your browser.
*   **What to expect**: You will see a 5D "Parallel Coordinates" chart. It allows you to "scrub" through variables (like Diamond vs. Silicon interposers) to see the impact on Thermal Jitter and Manufacturing Cost.
*   **Decision Support**: Consult the [reports/architectural_decision_tree.md](reports/architectural_decision_tree.md) to understand why the agent prefers one architecture over another.

## 3. The Ground Truth: Reviewing the Sign-off
This is the most critical step for a Bring-up or Tape-out engineer. You must verify that the physics actually work.
*   **Where to look**: The [reports/comprehensive_signoff_dossier.md](reports/comprehensive_signoff_dossier.md).
*   **What to expect**: A rigorous, industrial-grade report. It breaks down the area of every digital and analog block and calculates the **IR-drop** and **Eye Margins** using post-layout RC parasitics.
*   **Transparency**: If a design fails, the agent explains why in the [reports/design_reasoning.md](reports/design_reasoning.md) and provides the math in the [reports/physical_learning_proof.md](reports/physical_learning_proof.md).

## 4. The Handover: Manufacturing & Test
The system provides everything needed for the fab and the test house.
*   **Physical**: [serdes_architect/scripts/gds_export.tcl](serdes_architect/scripts/gds_export.tcl) for layout stream-out.
*   **Testing**: [reports/manufacturing_boot_plan.md](reports/manufacturing_boot_plan.md) defines the boot sequence, DICE attestation, and manufacturing test vectors.

---

# 🕵️ Critical User Review: "Is this trustworthy?"

As a new user, here is a critical critique of the current documentation suite:

### 🟢 Strengths (The "Aha!" Moments)
1.  **Explainability**: The system doesn't just say "Fail." It explains that 224G signals die over 300mm of copper due to **Skin Depth** math. This builds immediate trust with senior engineers.
2.  **Breadth**: The [DOCUMENTATION_INDEX.md](reports/DOCUMENTATION_INDEX.md) is a master-map that ensures you never lose track of the 15+ generated artifacts.
3.  **Correctness**: The transition from 0% IR-drop (ghost) to a realistic 0.42% droop (via Power Die) shows that the tool respects the laws of physics.

### 🔴 Weaknesses (What to watch out for)
1.  **Complexity Wall**: A user who has never designed a 3D-SoP might find the [assembly_packaging_spec.md](reports/assembly_packaging_spec.md) overwhelming. The system assumes a basic understanding of Hybrid Bonding.
2.  **Tool Dependencies**: The P&R steps are "Virtual" unless OpenROAD is installed. A user might expect a GDS file instantly, but they must realize the system is currently an **Architectural Sign-off Engine**, not a full physical implementation farm.
3.  **Stochastic Variance**: Thermal peaks can vary slightly between runs due to random hotspot placement in training. Users should look at **average trends** in the Pareto dashboard rather than single-point spikes.

**Final Verdict**: For a designer who "does not know what to expect," this system provides a high-fidelity, transparent, and educational environment. It acts more like a **Senior Design Partner** than a simple CAD script.
