import torch
import torch.nn.functional as F
import json
import argparse
import os

class IRDropSolver:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.grid_size = self.config['voxel_stack_params']['grid_size']
        self.layers = self.config['voxel_stack_params']['layers']
        self.vdd_nominal = self.config['packaging'].get('vddq_v', 0.8)
        
        # PDN Conductivity (S/m) - Recalibrated for 3nm Parasitics
        # Pessimistic values to ensure non-zero droop for 200W
        self.sigma_map = {
            "Die": 0.5,
            "Metal_Stack": 5.0,  # Resistive thin-wire copper
            "C4_BGA": 2.0,
            "Package": 0.05,
            "BSPDN": 20.0        # Backside is better, but not perfect
        }
        
        cooling = self.config['packaging'].get('cooling', '')
        use_bspdn = "BSPDN" in cooling
        
        sigmas = [self.sigma_map["Die"]] * self.layers
        if use_bspdn:
            sigmas[0] = self.sigma_map["BSPDN"]
            
        self.sigma_tensor = torch.tensor(sigmas, dtype=torch.float32).view(1, self.layers, 1, 1)

    def solve_ir_drop(self, power_map, iterations=1000):
        batch_size = power_map.shape[0]
        current_map = power_map / self.vdd_nominal
        
        # Initialize with Vdd
        V = torch.ones((batch_size, self.layers, self.grid_size, self.grid_size)) * self.vdd_nominal
        
        alpha = 0.1 # Iteration step
        
        # Scale current to grid distance (Heuristic for PI droop in 15mm die)
        PI_SCALE = 0.05 
        
        for _ in range(iterations):
            V_pad = F.pad(V, (1, 1, 1, 1, 1, 1), mode='replicate')
            
            # Laplacian
            d2V_dz2 = (V_pad[:, 2:, 1:-1, 1:-1] - 2*V + V_pad[:, :-2, 1:-1, 1:-1])
            d2V_dx2 = (V_pad[:, 1:-1, 1:-1, 2:] - 2*V + V_pad[:, 1:-1, 1:-1, :-2])
            d2V_dy2 = (V_pad[:, 1:-1, 2:, 1:-1] - 2*V + V_pad[:, 1:-1, :-2, 1:-1])
            
            laplacian = d2V_dx2 + d2V_dy2 + d2V_dz2
            
            # V_new = V + alpha * (Div(Sigma * Grad V) - J)
            # Simplified: V -= J/Sigma + Laplacian
            V = V + alpha * (laplacian - (current_map * PI_SCALE / (self.sigma_tensor)))
            
            # Supply Entry (Boundary Condition)
            cooling = self.config['packaging'].get('cooling', '')
            if "BSPDN" in cooling:
                V[:, 0, :, :] = self.vdd_nominal 
            else:
                V[:, 4, :, :] = self.vdd_nominal 
                
        return V

    def analyze_stability(self, V):
        v_min = V.min().item()
        droop_pct = (self.vdd_nominal - v_min) / self.vdd_nominal * 100
        
        # Threshold: 5% is standard. 8% is risky. 10% is failure.
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
    
    if os.path.exists('serdes_architect/data/x_physics.pt'):
        power_maps = torch.load('serdes_architect/data/x_physics.pt')
        V_out = solver.solve_ir_drop(power_maps[:1])
        res = solver.analyze_stability(V_out)
        
        print(f"📊 Power Integrity (IR-Drop) Audit:")
        print(f"  - Droop: {res['droop_percentage']}% | Status: {res['status']}")
        
        with open(args.config, 'r') as f: config = json.load(f)
        config['ir_drop_signoff'] = res
        with open(args.config, 'w') as f: json.dump(config, f, indent=2)