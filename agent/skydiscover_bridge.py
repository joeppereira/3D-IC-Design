import json
import os
import numpy as np

class CXLSwitchDiscoveryTask:
    """
    🚀 Skydiscover Bridge: 1TB CXL Switch 3D-IC Optimization
    Objective: Find the 'Golden Pareto Front' for Thermal vs. SI vs. IR-Drop
    """
    def __init__(self, config_template="configs/formal_spec.json"):
        with open(config_template, 'r') as f:
            self.base_config = json.load(f)
        self.iteration = 0

    def get_search_space(self):
        """Defines the DNA of the 3D-IC design for Skydiscover evolution."""
        return {
            "macro_spacing_um": [10, 500],
            "hybrid_bond_pitch_um": [3.0, 10.0],
            "pdd_voltage_mv": [700, 850],
            "die_0_x_offset": [-5, 5],
            "die_0_y_offset": [-5, 5]
        }

    def evaluate(self, params):
        """
        The 'Reward' Function: Called by Skydiscover (AdaEvolve/EvoX).
        Executes our local physics brawn and returns the fitness.
        """
        self.iteration += 1
        
        # 1. Update design from evolved params
        test_config = self.base_config.copy()
        test_config['packaging']['pitch_um'] = params.get('hybrid_bond_pitch_um', 5.0)
        
        # 2. Trigger Local Physics Solvers (Mocked for integration test)
        # In production, this calls run_full_cycle.sh
        tj_max = 105.0 - (params['macro_spacing_um'] * 0.02) # Wider = Cooler
        eye_opening = 0.48 + (params['pdd_voltage_mv'] * 0.0001) # Higher V = Better Eye
        ir_drop = 0.42 * (5.0 / params['hybrid_bond_pitch_um']) # Tighter pitch = Less droop
        
        # 3. Calculate Normalized Fitness (0.0 to 1.0)
        # We want to minimize Tj and IR-drop, maximize Eye
        thermal_score = max(0, (110 - tj_max) / 40)
        si_score = min(1.0, eye_opening / 0.6)
        pi_score = max(0, (2.0 - ir_drop) / 2.0)
        
        aggregate_reward = (thermal_score * 0.4) + (si_score * 0.4) + (pi_score * 0.2)
        
        print(f"🧬 [Skydiscover] Iteration {self.iteration}: Reward={aggregate_reward:.4f}")
        return {
            "reward": aggregate_reward,
            "metrics": {
                "tj_max": tj_max,
                "eye_opening": eye_opening,
                "ir_drop": ir_drop
            }
        }

if __name__ == "__main__":
    # Test execution
    task = CXLSwitchDiscoveryTask()
    dummy_params = {"macro_spacing_um": 250, "hybrid_bond_pitch_um": 5.0, "pdd_voltage_mv": 750}
    result = task.evaluate(dummy_params)
    print("Test Evaluation:", json.dumps(result, indent=2))
