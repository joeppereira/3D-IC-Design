import torch
import numpy as np
import json
import argparse
import os
import sys
import torch.nn as nn
import torch.nn.functional as F

# --- 2026 SerDes Reach Classification Matrix ---
REACH_MATRIX = {
    "XSR": {"dist_max": 10,  "loss_db": 3,  "std": "UCIe 3.0", "pwr_pj": 0.3, "eq": "None", "clock": "Forwarded"},
    "VSR": {"dist_max": 100, "loss_db": 10, "std": "Chiplet",   "pwr_pj": 0.8, "eq": "CTLE", "clock": "Forwarded"},
    "MR":  {"dist_max": 500, "loss_db": 25, "std": "C2C",      "pwr_pj": 1.5, "eq": "FFE+DFE", "clock": "CDR"},
    "LR":  {"dist_max": 1000,"loss_db": 36, "std": "PCIe 7.0", "pwr_pj": 2.5, "eq": "ADC-DSP", "clock": "CDR"},
    "VLR": {"dist_max": 2000,"loss_db": 45, "std": "Backplane","pwr_pj": 4.0, "eq": "Full-DSP", "clock": "CDR"}
}

# --- FNO Definition (Inference Version) ---
class SpectralConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, modes1, modes2):
        super(SpectralConv2d, self).__init__()
        self.in_channels, self.out_channels = in_channels, out_channels
        self.modes1, self.modes2 = modes1, modes2
        self.scale = (1 / (in_channels * out_channels))
        self.weights1 = nn.Parameter(self.scale * torch.rand(in_channels, out_channels, self.modes1, self.modes2, dtype=torch.cfloat))
        self.weights2 = nn.Parameter(self.scale * torch.rand(in_channels, out_channels, self.modes1, self.modes2, dtype=torch.cfloat))

    def compl_mul2d(self, input, weights):
        return torch.einsum("bixy,ioxy->boxy", input, weights)

    def forward(self, x):
        batchsize = x.shape[0]
        x_ft = torch.fft.rfft2(x)
        out_ft = torch.zeros(batchsize, self.out_channels, x.size(-2), x.size(-1)//2 + 1, dtype=torch.cfloat, device=x.device)
        out_ft[:, :, :self.modes1, :self.modes2] = self.compl_mul2d(x_ft[:, :, :self.modes1, :self.modes2], self.weights1)
        out_ft[:, :, -self.modes1:, :self.modes2] = self.compl_mul2d(x_ft[:, :, -self.modes1:, :self.modes2], self.weights2)
        x = torch.fft.irfft2(out_ft, s=(x.size(-2), x.size(-1)))
        return x

class FNO2d(nn.Module):
    def __init__(self, modes1, modes2, width, layers=5):
        super(FNO2d, self).__init__()
        self.modes1, self.modes2, self.width, self.layers = modes1, modes2, width, layers
        self.fc0 = nn.Linear(layers + 2, width)
        self.conv0 = SpectralConv2d(width, width, modes1, modes2)
        self.conv1 = SpectralConv2d(width, width, modes1, modes2)
        self.conv2 = SpectralConv2d(width, width, modes1, modes2)
        self.conv3 = SpectralConv2d(width, width, modes1, modes2)
        self.w0 = nn.Conv2d(width, width, 1)
        self.w1 = nn.Conv2d(width, width, 1)
        self.w2 = nn.Conv2d(width, width, 1)
        self.w3 = nn.Conv2d(width, width, 1)
        self.fc1 = nn.Linear(width, 128)
        self.fc2 = nn.Linear(128, layers)

    def get_grid(self, shape, device):
        batchsize, size_x, size_y = shape[0], shape[2], shape[3]
        gridx = torch.linspace(0, 1, size_x).reshape(1, 1, size_x, 1).repeat([batchsize, 1, 1, size_y])
        gridy = torch.linspace(0, 1, size_y).reshape(1, 1, 1, size_y).repeat([batchsize, 1, size_x, 1])
        return torch.cat((gridx, gridy), dim=1).to(device)

    def forward(self, x):
        grid = self.get_grid(x.shape, x.device)
        x = torch.cat((x, grid), dim=1).permute(0, 2, 3, 1)
        x = self.fc0(x).permute(0, 3, 1, 2)
        x = F.gelu(self.conv0(x) + self.w0(x))
        x = F.gelu(self.conv1(x) + self.w1(x))
        x = F.gelu(self.conv2(x) + self.w2(x))
        x = self.conv3(x) + self.w3(x)
        x = x.permute(0, 2, 3, 1)
        x = F.gelu(self.fc1(x))
        return self.fc2(x).permute(0, 3, 1, 2)

# --- GEPA Decision Logic ---

def classify_reach(reach_mm):
    """Categorizes link based on physical distance (mm)."""
    if reach_mm <= 10:   return "XSR"
    elif reach_mm <= 100: return "VSR"
    elif reach_mm <= 500: return "MR"
    elif reach_mm <= 1000:return "LR"
    else:                 return "VLR"

def run_gepa(args):
    print("📈 Starting GEPA Multi-Objective Optimization...")
    device = torch.device('cpu') 
    
    # Load Model & Stats
    try:
        model = FNO2d(modes1=8, modes2=8, width=32, layers=5)
        model.load_state_dict(torch.load('results/fno_model.pt', map_location=device))
        norm_stats = torch.load('results/norm_stats.pt')
        print("  Loaded Surrogate Model & Norm Stats.")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return

    # Load Base Config
    config_path = args.config
    with open(config_path, 'r') as f: base_config = json.load(f)

    reach_mm = base_config.get('reach_mm', 1.5)
    category = classify_reach(reach_mm)
    specs = REACH_MATRIX[category]
    
    print(f"\n🌍 Reach Classification: {category} ({reach_mm}mm)")
    print(f"  -> Budget: {specs['loss_db']} dB Loss | {specs['pwr_pj']} pJ/b")
    print(f"  -> Arch: {specs['eq']} EQ | {specs['clock']} Clocking")

    # Optimization Loop (Genetic Algorithm)
    population_size = 50
    generations = 10
    grid_size = 16
    
    print(f"  Exploring design space: {population_size} candidates x {generations} generations...")
    
    best_score = float('inf')
    best_design = None
    
    for gen in range(generations):
        candidates = []
        inputs = torch.zeros((population_size, 5, grid_size, grid_size))
        
        for i in range(population_size):
            lx, ly = np.random.randint(0, grid_size-4, 2)
            mx, my = np.random.randint(0, grid_size-4, 2)
            
            # Construct Power Map (Input X) - Logic (Layer 0) 5W, Memory (Layer 1) 2W
            inputs[i, 0, lx:lx+4, ly:ly+4] = 5.0 
            inputs[i, 1, mx:mx+4, my:my+4] = 2.0
            candidates.append({'lx': int(lx), 'ly': int(ly), 'mx': int(mx), 'my': int(my)})
            
        with torch.no_grad():
            preds_norm = model(inputs) # Ensure inputs are float32
            # De-normalize
            preds = preds_norm * norm_stats['std'] + norm_stats['mean']
            
        for i in range(population_size):
            max_t = preds[i].max().item()
            
            # Distance (Manhattan grid units -> mm? Assume 1 unit = 0.1mm)
            # This is "internal" reach between dies
            dist_units = abs(candidates[i]['lx'] - candidates[i]['mx']) + abs(candidates[i]['ly'] - candidates[i]['my'])
            internal_reach_mm = dist_units * 0.1 
            
            temp_penalty = max(0, max_t - 85.0) * 10.0
            score = max_t + dist_units * 0.5 + temp_penalty
            
            if score < best_score:
                best_score = score
                best_design = candidates[i]
                best_design['estimated_max_temp'] = max_t
                best_design['internal_reach_mm'] = internal_reach_mm

    print(f"  Best Design: Temp={best_design['estimated_max_temp']:.2f}C, Reach={best_design['internal_reach_mm']:.2f}mm")

    # Final Recommendation Logic
    recs = []
    if specs['clock'] == "CDR":
        recs.append("  -> Clocking: Drift detected. Use CDR (Adds ~15% area).")
    else:
        recs.append("  -> Clocking: Use Forwarded Clock (Low Power/Latency).")
        
    if specs['loss_db'] > 30:
        recs.append("  -> PHY: ADC-based DSP mandatory for heavy equalization.")
    elif specs['loss_db'] > 15:
        recs.append("  -> PHY: Analog FFE + DFE required for eye closure.")
    
    if best_design['estimated_max_temp'] > 105:
        recs.append("  -> 🔥 THERMAL ALERT: Material Wall reached. Switch to GaAs.")

    # Update and Save
    base_config['reach_classification'] = category
    base_config['architectural_recs'] = recs
    base_config['floorplan'] = best_design
    
    os.makedirs('results', exist_ok=True)
    with open('results/golden_config.json', 'w') as f:
        json.dump(base_config, f, indent=2)
    print("\n✅ Saved optimized configuration to results/golden_config.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True, help='Path to config JSON')
    parser.add_argument('--target_bw', type=int, default=64)
    parser.add_argument('--max_pwr', type=float, default=8.0)
    parser.add_argument('--avs_enabled', type=str, default='false')
    parser.add_argument('--target_ber', type=float, default=1e-12)
    parser.add_argument('--optimize_for', type=str, default="isolation,aging")
    args = parser.parse_args()
    run_gepa(args)
