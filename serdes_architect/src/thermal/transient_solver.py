import torch
import torch.nn.functional as F
import json
import argparse
import numpy as np
import os

class TransientThermalSolver:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.grid_size = self.config['voxel_stack_params']['grid_size']
        self.layers = self.config['voxel_stack_params']['layers']
        self.k_tensor = torch.tensor([140.0, 380.0, 50.0, 100.0, 0.3]).view(1, 5, 1, 1) # Simplified K
        
        # Specific Heat Capacity (J/kg*K) and Density (kg/m3) proxy for Thermal Mass
        # Si: ~700 J/kgK, 2330 kg/m3. Product ~ 1.6e6
        # We use a normalized Alpha (Thermal Diffusivity)
        self.diffusivity = 0.01 

    def solve_transient(self, power_map, burst_duration_ms=10, dt_ms=0.5):
        """
        Solves the transient heat equation: dT/dt = alpha * Laplacian(T) + Source
        """
        steps = int(burst_duration_ms / dt_ms)
        batch_size = power_map.shape[0]
        
        # Start from steady state or ambient?
        # Let's assume start from a pre-heated 50C state (baseline activity)
        T = torch.ones((batch_size, self.layers, self.grid_size, self.grid_size)) * 50.0
        
        T_history = []
        
        PHYSICAL_SCALE = 500.0 # Match steady state calibration
        
        print(f"🌡️ Simulating {burst_duration_ms}ms RDMA Burst ({steps} steps)...")
        
        for i in range(steps):
            T_pad = F.pad(T, (1, 1, 1, 1, 1, 1), mode='replicate')
            
            # Laplacian
            d2T_dz2 = (T_pad[:, 2:, 1:-1, 1:-1] - 2*T + T_pad[:, :-2, 1:-1, 1:-1])
            d2T_dx2 = (T_pad[:, 1:-1, 1:-1, 2:] - 2*T + T_pad[:, 1:-1, 1:-1, :-2])
            d2T_dy2 = (T_pad[:, 1:-1, 2:, 1:-1] - 2*T + T_pad[:, 1:-1, :-2, 1:-1])
            
            laplacian = d2T_dx2 + d2T_dy2 + d2T_dz2
            
            # Update: T_new = T + dt * (alpha * Laplacian + Source)
            T = T + self.diffusivity * (laplacian + (power_map * PHYSICAL_SCALE / self.k_tensor))
            
            # Boundary Conditions (Heatsinks)
            T[:, 4, :, :] = T[:, 4, :, :] * 0.98 + 25.0 * 0.02 # Board
            T[:, 0, :, :] = T[:, 0, :, :] * 0.95 + 25.0 * 0.05 # Top Cooler
            
            if i % 5 == 0:
                T_history.append(T.max().item())
                
        return T, T_history

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    
    solver = TransientThermalSolver(args.config)
    
    # Load power map
    if os.path.exists('serdes_architect/data/x_physics.pt'):
        power_maps = torch.load('serdes_architect/data/x_physics.pt')
        # Simulate a 150W peak burst (scale the 100W baseline)
        burst_power = power_maps[:1] * 1.5
        
        T_final, history = solver.solve_transient(burst_power)
        
        print(f"📈 Transient Analysis Results:")
        print(f"  - Initial Temp: 50.0 C")
        print(f"  - Peak Burst Temp: {T_final.max().item():.2f} C")
        print(f"  - Thermal Headroom: {105.0 - T_final.max().item():.2f} C")
        
        if T_final.max().item() > 105.0:
            print("  ❌ FAIL: Burst exceeds thermal cap! Increase thermal mass or active cooling.")
        else:
            print("  ✅ PASS: Stack handles 10ms burst safely.")
            
        # Write to config
        with open(args.config, 'r') as f: config = json.load(f)
        config['transient_thermal_signoff'] = {
            "peak_burst_temp": T_final.max().item(),
            "duration_ms": 10,
            "status": "PASS" if T_final.max().item() <= 105.0 else "FAIL"
        }
        with open(args.config, 'w') as f: json.dump(config, f, indent=2)
