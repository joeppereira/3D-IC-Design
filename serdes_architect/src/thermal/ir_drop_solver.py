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
        self.vdd_nominal = self.config['packaging'].get('vddq_v', 0.8) # Nominal Vdd
        
        # PDN Conductivity (S/m) proxy
        # Higher for Metal Stack, Lower for Package
        # BSPDN significantly increases conductivity in Layer 0/1
        self.sigma_map = {
            "Die": 1.0,
            "Metal_Stack": 50.0,
            "C4_BGA": 10.0,
            "Package": 0.1,
            "BSPDN": 100.0 # Backside power is highly conductive
        }
        
        cooling = self.config['packaging'].get('cooling', '')
        use_bspdn = "BSPDN" in cooling
        
        # Build Conductivity Tensor [1, Layers, 1, 1]
        sigmas = [self.sigma_map["Die"]] * self.layers
        if use_bspdn:
            sigmas[0] = self.sigma_map["BSPDN"] # Power enters from backside (Layer 0)
            
        self.sigma_tensor = torch.tensor(sigmas, dtype=torch.float32).view(1, self.layers, 1, 1)

    def solve_ir_drop(self, power_map, iterations=500):
        """
        Solves for Voltage distribution using Jacobi iteration.
        Laplacian(V) = Current / Sigma
        """
        batch_size = power_map.shape[0]
        # Current = Power / Voltage (Simplified)
        current_map = power_map / self.vdd_nominal
        
        # Initialize Voltage map at nominal Vdd
        V = torch.ones((batch_size, self.layers, self.grid_size, self.grid_size)) * self.vdd_nominal
        
        alpha = 0.05 # Relaxation factor
        
        for _ in range(iterations):
            V_pad = F.pad(V, (1, 1, 1, 1, 1, 1), mode='replicate')
            
            # 3D Laplacian for Potential
            d2V_dz2 = (V_pad[:, 2:, 1:-1, 1:-1] - 2*V + V_pad[:, :-2, 1:-1, 1:-1])
            d2V_dx2 = (V_pad[:, 1:-1, 1:-1, 2:] - 2*V + V_pad[:, 1:-1, 1:-1, :-2])
            d2V_dy2 = (V_pad[:, 1:-1, 2:, 1:-1] - 2*V + V_pad[:, 1:-1, :-2, 1:-1])
            
            laplacian = d2V_dx2 + d2V_dy2 + d2V_dz2
            
            # Update V: V_new = V + alpha * (Laplacian - Current/Sigma)
            # Voltage drops where current is consumed
            V = V + alpha * (laplacian - (current_map / (self.sigma_tensor + 1e-6)))
            
            # Boundary Condition: Vdd is fixed at the supply entry (Layer 0 for BSPDN, Layer 4 for standard)
            cooling = self.config['packaging'].get('cooling', '')
            if "BSPDN" in cooling:
                V[:, 0, :, :] = self.vdd_nominal # Supply entry at backside
            else:
                V[:, 4, :, :] = self.vdd_nominal # Supply entry at BGA
                
        return V

    def analyze_stability(self, V):
        v_min = V.min().item()
        droop_pct = (self.vdd_nominal - v_min) / self.vdd_nominal * 100
        
        status = "✅ PASS" if droop_pct < 5.0 else "❌ FAIL"
        
        return {
            "min_voltage": v_min,
            "droop_percentage": droop_pct,
            "status": status,
            "threshold": 5.0
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    
    solver = IRDropSolver(args.config)
    
    # Load last power map for analysis
    if os.path.exists('serdes_architect/data/x_physics.pt'):
        power_maps = torch.load('serdes_architect/data/x_physics.pt')
        V_out = solver.solve_ir_drop(power_maps[:1]) # Analyze first sample
        res = solver.analyze_stability(V_out)
        
        print(f"📊 IR-Drop Analysis for {args.config}:")
        print(f"  - Nominal Vdd: {solver.vdd_nominal}V")
        print(f"  - Min Voltage: {res['min_voltage']:.3f}V")
        print(f"  - Droop:       {res['droop_percentage']:.2f}% (Limit: {res['threshold']}%)")
        print(f"  - PI Status:   {res['status']}")
        
        # Save to config
        with open(args.config, 'r') as f: config = json.load(f)
        config['ir_drop_signoff'] = res
        with open(args.config, 'w') as f: json.dump(config, f, indent=2)
