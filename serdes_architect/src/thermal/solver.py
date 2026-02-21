import torch
import torch.nn.functional as F
import json
import argparse

class ThermalSolver:
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        self.layers = self.config['voxel_stack_params']['layers']
        self.grid_size = self.config['voxel_stack_params']['grid_size']
        self.base_k_map = self.config['voxel_stack_params']['k_map']
        
        # Load Packaging Specifics
        self.pkg_config = self.config.get('packaging', {})
        self.topology = self.pkg_config.get('topology', 'Face_to_Face')
        
        # Merge extra material properties if present
        if 'material_properties' in self.pkg_config:
            self.base_k_map.update(self.pkg_config['material_properties'])

        # Build Layer Stack based on Topology
        self.layer_materials = self._build_stack_materials()
        print(f"  [Solver] Built {self.topology} Stack: {self.layer_materials}")
        
        # Thermal Conductivity Tensor (k) - Shape: [1, Layers, 1, 1]
        k_values = [self.base_k_map.get(mat, 1.0) for mat in self.layer_materials]
        self.k_tensor = torch.tensor(k_values, dtype=torch.float32).view(1, self.layers, 1, 1)

    def _build_stack_materials(self):
        """Constructs the vertical material stack based on topology."""
        # Mapping to generic keys in base_k_map or pkg_config
        # We need 5 layers to match FNO input channels.
        
        if self.topology == "Face_to_Face":
            # Logic (Bottom) -> Hybrid Bond -> Memory (Top) -> Heat Sink?
            # Or usually: Logic (Bottom) -> Bond -> Memory -> ...
            # Let's assume Logic is Layer 1, Memory is Layer 0 (Top)
            # 0: Memory (Die)
            # 1: Hybrid_Bond (High density, good thermal)
            # 2: Logic (Die) - Primary Heat Source
            # 3: C4_BGA
            # 4: Package/Substrate
            return ['Die', 'Hybrid_Bond', 'Die', 'C4_BGA', 'Package']
            
        elif self.topology == "Back_to_Face":
            # Traditional 3D Stacking with TSVs
            # 0: Memory (Die)
            # 1: Underfill/Microbump (Poor thermal path compared to Hybrid)
            # 2: Logic (Die)
            # 3: C4_BGA
            # 4: Package
            return ['Die', 'Microbump', 'Die', 'C4_BGA', 'Package']
            
        elif self.topology == "Side_by_Side_2.5D":
            # Interposer based
            # 0: Dies (Logic + Memory side-by-side)
            # 1: Microbump
            # 2: Interposer (Silicon or Organic)
            # 3: C4_BGA
            # 4: Package
            interposer_type = self.pkg_config.get('interposer', 'Silicon_Interposer')
            # Normalize key
            if "Silicon" in interposer_type: mat = "Silicon_Interposer"
            elif "Organic" in interposer_type: mat = "Organic_Interposer"
            else: mat = "Die" # Fallback
            
            return ['Die', 'Microbump', mat, 'C4_BGA', 'Package']
            
        else:
            # Default / Fallback
            return ['Die', 'Metal_Stack', 'C4_BGA', 'Package', 'PCB_Board']

    def solve_steady_state(self, power_map, iterations=1000):
        """
        Solves for steady-state temperature distribution given a power map.
        Uses a finite difference method (Jacobi iteration) on the heat equation:
        k * Laplacian(T) = -Power
        """
        batch_size = power_map.shape[0]
        # Initialize Temperature map (Ambient 25C)
        T = torch.ones((batch_size, self.layers, self.grid_size, self.grid_size), dtype=torch.float32) * 25.0
        
        # Grid spacing (dx, dy, dz assumed 1.0 for simplicity in this demo, or derived from size_mm)
        
        for _ in range(iterations):
            # Pad for neighbor access
            T_pad = F.pad(T, (1, 1, 1, 1, 1, 1), mode='replicate') # Pad D, H, W
            
            # Laplacian Components
            # Vertical (Z-axis) - Key for 3D heat stack!
            dz_sq = 1.0 # Normalized Z-step
            d2T_dz2 = (T_pad[:, 2:, 1:-1, 1:-1] - 2*T + T_pad[:, :-2, 1:-1, 1:-1]) / dz_sq
            
            # Horizontal (X, Y axes)
            dx_sq = 1.0 # Normalized XY-step
            d2T_dx2 = (T_pad[:, 1:-1, 1:-1, 2:] - 2*T + T_pad[:, 1:-1, 1:-1, :-2]) / dx_sq
            d2T_dy2 = (T_pad[:, 1:-1, 2:, 1:-1] - 2*T + T_pad[:, 1:-1, :-2, 1:-1]) / dx_sq
            
            alpha = 0.01 # Time step / Diffusivity
            
            laplacian = d2T_dx2 + d2T_dy2 + d2T_dz2
            
            # Apply update
            # Scaling Factor: To model a ~10mm chip on 16x16 grid (dx ~ 0.6mm) using k in W/mK
            # Scaling Factor: Calibrated for 100W on 10mm die -> ~85C with Heatsink
            PHYSICAL_SCALE = 500.0
            
            T = T + alpha * (laplacian + (power_map * PHYSICAL_SCALE) / self.k_tensor)
            
            # Enforce Boundary Conditions
            # 1. Bottom Heat Sink (PCB/Board)
            T[:, 4, :, :] = T[:, 4, :, :] * 0.95 + 25.0 * 0.05
            
            # 2. Top Heat Sink (Convective Fan/Heatsink)
            # This is critical! Without this, 100W has nowhere to go.
            h_coeff = 0.1 # Heat transfer coefficient proxy
            T[:, 0, :, :] = T[:, 0, :, :] * (1.0 - h_coeff) + 25.0 * h_coeff
            
            # 3. Active Cooling / BSPDN Check
            cooling = self.pkg_config.get('cooling', 'Passive')
            if "BSPDN" in cooling or "Liquid" in cooling:
                # BSPDN adds a secondary direct path to the sink
                T[:, 0, :, :] = T[:, 0, :, :] * 0.8 + 25.0 * 0.2
            
        return T

    def verify(self):
        print("Running Nodal Laplacian Check...")
        print(f"  Topology: {self.topology}")
        # Create a dummy single sample
        dummy_power = torch.zeros((1, self.layers, self.grid_size, self.grid_size))
        # Add a hotspot in the center of Die (Layer 0)
        dummy_power[0, 0, 8, 8] = 10.0 # 10 Watts localized
        
        T_out = self.solve_steady_state(dummy_power, iterations=500)
        
        max_t = T_out.max().item()
        min_t = T_out.min().item()
        print(f"  Test Hotspot (10W): Max T = {max_t:.2f}C, Min T = {min_t:.2f}C")
        
        # Check Gradient: Layer 0 should be hotter than Layer 1 (Metal/Bond/Interposer)
        l0_center = T_out[0, 0, 8, 8].item()
        l1_center = T_out[0, 1, 8, 8].item()
        print(f"  Gradient Check: Layer 0 ({l0_center:.2f}C) vs Layer 1 ({l1_center:.2f}C)")
        
        if l0_center > l1_center:
            print("  ✅ Gradient Correct: Heat flowing from Source to Sink.")
        else:
            print("  ❌ Gradient Error: Physics violation.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true', help='Run physics verification')
    parser.add_argument('--mode', type=str, default='standard', help='Solver mode')
    args = parser.parse_args()
    
    # Assuming config is at ../../configs/cxl_64g.json relative to this script if run from src/thermal
    # But usually run from root or serdes_architect
    # Let's try to find the config or assume a default path for verification
    config_path = 'configs/cxl_64g.json' 
    import os
    if not os.path.exists(config_path):
        # Try relative to serdes_architect root
        config_path = '../configs/cxl_64g.json'
        
    if args.verify:
        solver = ThermalSolver(config_path)
        solver.verify()