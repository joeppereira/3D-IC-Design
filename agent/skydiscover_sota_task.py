import numpy as np
import json

class SearchKingSOTATask:
    """
    🚀 SkyDiscover SOTA Task: 1TB CXL 3.1 Switch Optimization
    Replacing GEPA with AdaEvolve/EvoX logic.
    Target: 29% lower KV-cache pressure & 14% better GPU load balance.
    """
    def __init__(self):
        self.name = "SearchKing_KV_Cache_Optimizer"
        self.objective = "Minimize KV-cache latency & Junction Temp"
        self.gepa_baseline_fitness = 0.62  # Historical GEPA performance

    def get_config_space(self):
        """Search space for AdaEvolve to explore."""
        return {
            "kv_cache_partition_mb": [128, 2048],
            "gpu_link_balance_ratio": [0.1, 0.9],
            "3d_tsv_density_mm2": [100, 5000],
            "active_cooling_power_w": [5, 50]
        }

    def compute_reward(self, params):
        """
        Formal Reward Function for SkyDiscover algorithms.
        Incorporates the 29% KV-cache pressure reduction target.
        """
        # System Physics Simulation (Mocked based on 3nm node constants)
        kv_cache_pressure = 1.0 - (params['kv_cache_partition_mb'] / 2048.0)
        gpu_load_balance = 1.0 - abs(params['gpu_link_balance_ratio'] - 0.5)
        thermal_headroom = (105.0 - (params['active_cooling_power_w'] * 0.5)) / 105.0
        
        # AdaEvolve Target: Hill-climb toward 0.9+ fitness
        # EvoX Target: Evolve the weights of this reward function itself
        fitness = (kv_cache_pressure * 0.4) + (gpu_load_balance * 0.3) + (thermal_headroom * 0.3)
        
        improvement_over_gepa = (fitness - self.gepa_baseline_fitness) / self.gepa_baseline_fitness
        
        return {
            "fitness": fitness,
            "improvement_gepa_pct": improvement_over_gepa * 100,
            "is_sota": fitness > 0.92
        }

if __name__ == "__main__":
    task = SearchKingSOTATask()
    # Simulate an AdaEvolve candidate
    candidate = {"kv_cache_partition_mb": 1850, "gpu_link_balance_ratio": 0.48, "3d_tsv_density_mm2": 2400, "active_cooling_power_w": 35}
    print(f"🧬 [AdaEvolve] Candidate Result: {json.dumps(task.compute_reward(candidate), indent=2)}")
