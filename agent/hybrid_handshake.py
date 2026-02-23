import torch
import json
import os
from agent.core_jepa.py import JEPABrain # Assuming established path

class HybridExpertOrchestrator:
    def __init__(self, jepa_weights="project_memory/adapters/physics_v1.bin"):
        self.local_brain = JEPABrain()
        if os.path.exists(jepa_weights):
            self.local_brain.load_state_dict(torch.load(jepa_weights))
        self.history = []

    def verify_design_intuition(self, power_voxels):
        """Zero-latency local check before calling heavy solvers."""
        with torch.no_grad():
            thermal_pred = self.local_brain(power_voxels)
            max_t = thermal_pred.max().item()
            
        self.history.append(max_t)
        return max_t

    def detect_stall(self):
        """Checks if the last 3 iterations failed to improve the metric."""
        if len(self.history) < 3: return False
        
        # If the delta between the last 3 runs is < 1%, we are stalled
        recent = self.history[-3:]
        if abs(recent[0] - recent[-1]) < 1.0:
            return True
        return False

    def request_help(self, reason):
        """Formalized Support Request to the User."""
        request = {
            "status": "⏸️ PAUSED (Lack of Progress)",
            "reason": reason,
            "required_resource": "User Guidance / New Constraint",
            "suggestion": "Consider increasing Die Area to 20x20mm or reducing Clock Frequency."
        }
        print(json.dumps(request, indent=2))
        return request

if __name__ == "__main__":
    # Example logic for the Agent
    orchestrator = HybridExpertOrchestrator()
    # Mocking a stall
    orchestrator.history = [115.2, 114.9, 115.0]
    
    if orchestrator.detect_stall():
        orchestrator.request_help("Thermal convergence reached a wall at 115C. I have exhausted all autonomous BSPDN and material levers.")
