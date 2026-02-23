# 🤝 User Collaboration & Help Protocol

A proper design tool must know its limits. This document defines how the **Autonomous Architect** interacts with you, the designer, when it encounters ambiguity or physical "walls."

## 1. When the Agent Asks for Help
The Agent will pause and request intervention in the following scenarios:
*   **Physics Stall**: When 3 iterations of the Pareto Search fail to improve a metric (e.g., Eye Margin stuck at 0.18 UI).
*   **Resource Lack**: When a protocol is requested (e.g., "UALink 3.0") but no reference LEF/spec exists in the repository.
*   **Security Ambiguity**: When a keep-out zone conflict exists between two high-priority macros.

## 2. How to Provide Help
When the Agent pauses, you can provide the missing "Resource" or "Constraint":
*   **Missing Spec**: `Gemini, read the documentation in /docs/new_protocol.pdf and update your constraints.`
*   **Override**: `Gemini, I accept the 110C thermal risk. Proceed with the current floorplan.`
*   **New Lever**: `Gemini, try adding a Copper-Graphene heat spreader to Layer 1.`

## 3. Local Hybrid Model Training
The Local JEPA is trained on your specific repository data. 
*   **Command**: `Gemini, train your local physics head on the last 50 design attempts.`
*   **Benefit**: This allows the Agent to "remember" the specific parasitics of your custom interposer, making its initial guesses 90% accurate without running a solver.

---
**The goal is not full autonomy, but collaborative mastery.**
