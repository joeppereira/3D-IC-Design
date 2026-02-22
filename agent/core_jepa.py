import torch
import torch.nn as nn
import torch.nn.functional as F

class VoxelEncoder(nn.Module):
    """Encodes 5-layer physical voxels into latent embedding space."""
    def __init__(self, in_channels=5, latent_dim=128):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, 32, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1) # Downsample
        self.conv3 = nn.Conv2d(64, latent_dim, kernel_size=3, stride=2, padding=1)
        self.pool = nn.AdaptiveAvgPool2d(1)

    def forward(self, x):
        x = F.gelu(self.conv1(x))
        x = F.gelu(self.conv2(x))
        x = F.gelu(self.conv3(x))
        return self.pool(x).view(x.size(0), -1)

class ThermalPredictor(nn.Module):
    """Predicts thermal latent state from power latent state."""
    def __init__(self, latent_dim=128):
        super().__init__()
        self.fc1 = nn.Linear(latent_dim, 256)
        self.fc2 = nn.Linear(256, latent_dim)

    def forward(self, power_embedding):
        x = F.gelu(self.fc1(power_embedding))
        return self.fc2(x)

class JEPABrain(nn.Module):
    def __init__(self, latent_dim=128):
        super().__init__()
        self.power_encoder = VoxelEncoder(in_channels=5, latent_dim=latent_dim)
        self.thermal_encoder = VoxelEncoder(in_channels=5, latent_dim=latent_dim)
        self.predictor = ThermalPredictor(latent_dim=latent_dim)

    def forward(self, power_voxels, thermal_voxels=None):
        z_power = self.power_encoder(power_voxels)
        
        if thermal_voxels is not None:
            # Training Mode: Minimize distance between predicted and actual latent states
            z_thermal_actual = self.thermal_encoder(thermal_voxels)
            z_thermal_pred = self.predictor(z_power)
            return z_thermal_pred, z_thermal_actual
        
        # Inference Mode: Predict thermal state
        return self.predictor(z_power)

if __name__ == "__main__":
    # Test instantiation for 3nm node
    model = JEPABrain()
    print("✅ JEPA-12L Core Initialized.")
    print(f"  - Latent Dimension: 128")
    print(f"  - Parameters:      {sum(p.numel() for p in model.parameters())/1e3:.1f} k")
