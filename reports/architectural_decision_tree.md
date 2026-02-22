# 🧠 Architectural Decision Tree: 3D IC Designer

This guide enables designers to make "Investor-Grade" trade-off decisions based on the Pareto Matrix results.

## 1. The Reach vs. Material Decision
*   **Is Reach < 50mm?**
    *   *Choice*: Standard **FR4/Megtron 7**.
    *   *Result*: Lowest cost, manageable loss.
*   **Is Reach > 300mm?**
    *   *Choice*: **Flyover Twinax**.
    *   *Result*: Required for 224G to avoid 0.00 UI eye closure. Adds $1.5x$ assembly cost.

## 2. The Power vs. Cooling Decision
*   **Is Total Power > 150W?**
    *   *Choice*: **Backside PDN (BSPDN) + Liquid Cooling**.
    *   *Result*: Fixes 3000C thermal runaway. Mandatory for 3nm GAA high-density logic.
*   **Is Cost the primary driver?**
    *   *Choice*: Reduce Speed to 64G NRZ and use Air Cooling.

## 3. The Security vs. EM Isolation Decision
*   **Is Caliptra RoT near a 224G cluster?**
    *   *Choice*: **250um Keep-out Zone**.
    *   *Result*: Reduces EM side-channel leak risk. If area is too tight, use **Ground Shielding Walls**.
