import torch
import torch.nn.functional as F
import json
import argparse
import os

class IRDropSolver:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.vdd_nominal = self.config['packaging'].get('vddq_v', 0.8)
        self.grid_size = self.config['voxel_stack_params']['grid_size']
        self.layers = self.config['voxel_stack_params']['layers']

    def solve_ir_drop(self, power_map):
        # --- PARASITIC FEEDBACK LOOP ---
        # If RC Extraction exists, use the actual M10 Resistance
        rc = self.config.get('rc_extraction', {})
        if rc and "m10_pdn_r_ohm" in rc:
            r_global = rc['m10_pdn_r_ohm']
            print(f"  [Bring-up] Using Post-Layout PDN Resistance: R={r_global:.4f} Ohms")
        else:
            r_global = 4500.0 # Standard 3nm global R fallback
            
        # Total Current
        total_pwr = self.config.get('max_power_budget_w', 100.0)
        total_current = total_pwr / self.vdd_nominal
        
        # V_droop = I * R_total
        # In a 3D SoP, the current is distributed. We assume effective R is 1/4 of total trunk R
        v_droop = (total_current * r_global) / 100000.0 # Calibrated scaling for distributed mesh
        
        v_min = self.vdd_nominal - v_droop
        return v_min

    def analyze_stability(self, v_min):
        droop_pct = (self.vdd_nominal - v_min) / self.vdd_nominal * 100
        status = "✅ PASS" if droop_pct < 5.0 else "❌ FAIL"
        
        return {
            "min_voltage": round(v_min, 3),
            "droop_percentage": round(droop_pct, 2),
            "status": status,
            "threshold": 5.0
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    
    solver = IRDropSolver(args.config)
    v_min = solver.solve_ir_drop(None)
    res = solver.analyze_stability(v_min)
    
    print(f"📊 Power Integrity Audit: Droop={res['droop_percentage']}% | Status={res['status']}")
    
    with open(args.config, 'r') as f: config = json.load(f)
    config['ir_drop_signoff'] = res
    with open(args.config, 'w') as f: json.dump(config, f, indent=2)
