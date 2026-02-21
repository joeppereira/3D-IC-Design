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
            PHYSICAL_SCALE = 25000.0
            
            T = T + alpha * (laplacian + (power_map * PHYSICAL_SCALE) / self.k_tensor)
            
            # Enforce Boundary Conditions
            # PCB (Layer 4) is connected to board/heatsink -> pull towards 25.0
            T[:, 4, :, :] = T[:, 4, :, :] * 0.9 + 25.0 * 0.1 # Soft clamp to 25
            
        return T