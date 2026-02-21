import argparse
import json
import torch
import numpy as np
import os
import sys

# Ensure we can import from local modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.thermal.solver import ThermalSolver

def generate_data(args):
    print(f"Generating {args.samples} samples with {args.layers} layers...")
    
    # Load Config
    with open(args.config, 'r') as f:
        config = json.load(f)
    
    max_pwr = config.get('max_power_budget_w', 8.0)
    # Scale random power generation to hit ~max_pwr total per sample
    # Assume 75% in Layer 0, 25% in Layer 1
    
    grid_size = config['voxel_stack_params']['grid_size']
    layers = config['voxel_stack_params']['layers']
    
    print("  Creating random Power Maps...")
    # Shape: [Samples, Layers, H, W]
    # Initialize with zeros
    power_maps = torch.zeros((args.samples, layers, grid_size, grid_size))
    
    # Random hot spots on Layer 0 (Logic)
    for i in range(args.samples):
        # Logic Die (Layer 0) - Target 75% of Budget
        current_pwr = 0
        target_l0 = max_pwr * 0.75
        
        while current_pwr < target_l0:
            rx, ry = np.random.randint(0, grid_size, 2)
            spot_pwr = np.random.uniform(target_l0 * 0.1, target_l0 * 0.3)
            y, x = np.ogrid[-rx:grid_size-rx, -ry:grid_size-ry]
            mask = x*x + y*y <= 9.0 # Radius squared increased to 9 (r=3, Area ~ 28 units)
            # Area ~ 28/256 of die ~ 10%. 
            # 8W * 0.3 = 2.4W in 10% area -> 24W/die density equivalent.
            # Real high performance is ~100W/die. So this is reasonable.
            
            if np.sum(mask) > 0:
                power_maps[i, 0, mask] += spot_pwr / np.sum(mask) 
            current_pwr += spot_pwr
            
        # Memory Die (Layer 1) - Target 25% of Budget
        current_pwr_l1 = 0
        target_l1 = max_pwr * 0.25
        
        # Stacked Die is usually aligned or offset slightly
        while current_pwr_l1 < target_l1:
             rx, ry = np.random.randint(2, grid_size-2, 2) # More centered
             spot_pwr = np.random.uniform(target_l1 * 0.2, target_l1 * 0.5)
             power_maps[i, 1, rx, ry] += spot_pwr
             current_pwr_l1 += spot_pwr

    # 2. Solve for Thermal Maps (Y)
    print("  Solving for Thermal Distribution (This may take a while)...")
    solver = ThermalSolver(args.config)
    
    # Process in batches to avoid OOM
    batch_size = 100
    temperature_maps = []
    
    for start in range(0, args.samples, batch_size):
        end = min(start + batch_size, args.samples)
        batch_power = power_maps[start:end]
        
        # Run Solver (simplified iteration count for speed in demo)
        # Real FNO training needs good data, so we'll do enough iterations to see gradients.
        batch_temp = solver.solve_steady_state(batch_power, iterations=200) # 200 is decent for small grid
        temperature_maps.append(batch_temp)
        
        if start % 1000 == 0:
            print(f"    Processed {start}/{args.samples} samples...")
            
    temperature_maps = torch.cat(temperature_maps, dim=0)
    
    # 3. Save Data
    output_dir = 'data'
    os.makedirs(output_dir, exist_ok=True)
    
    torch.save(power_maps, os.path.join(output_dir, 'x_physics.pt'))
    torch.save(temperature_maps, os.path.join(output_dir, 'y_spatial.pt'))
    
    print(f"  Saved x_physics.pt and y_spatial.pt to {output_dir}/")

    # 4. Verify Jitter Tax
    # "Horizontal Jitter Tax (0.01 UI per 10°C)"
    # This is a derived metric, maybe used in analysis or the surrogate model?
    # The prompt implies FNO predicts temperatures, which are then used to calculate Jitter.
    # So the dataset is (Power -> Temp). Jitter is a post-processing step on Temp.
    # I will calculate and print a stat about Jitter for verification.
    
    avg_temp = temperature_maps.mean()
    max_temp = temperature_maps.max()
    jitter_tax = (max_temp - 25.0) / 10.0 * 0.01
    print(f"  Stats: Max Temp = {max_temp:.2f}C, Avg Temp = {avg_temp:.2f}C")
    print(f"  Max Jitter Tax observed: {jitter_tax:.4f} UI")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=int, default=1000, help='Number of samples to generate')
    parser.add_argument('--layers', type=int, default=5, help='Number of vertical layers')
    parser.add_argument('--config', type=str, required=True, help='Path to config JSON')
    parser.add_argument('--material', type=str, default='FR4', help='Material override')
    
    args = parser.parse_args()
    generate_data(args)
