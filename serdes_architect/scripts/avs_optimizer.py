import json
import argparse
import os
import numpy as np
import subprocess

def run_si_with_voltage(config_path, voltage):
    # Update config with test voltage
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    config['packaging']['vddq_v'] = voltage
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    # Run SI Analyzer
    cmd = f"python3 serdes_architect/src/si_analyzer_v3.py --config {config_path}"
    subprocess.run(cmd, shell=True, capture_output=True)
    
    # Read result
    with open(config_path, 'r') as f:
        res = json.load(f)
    
    return res.get('si_analysis_v3', {})

def optimize_avs(config_path):
    print(f"⚡ Starting Adaptive Voltage Scaling (AVS) Optimization for {config_path}...")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    v_range = config.get('packaging', {}).get('vddq_range', [0.8, 1.0])
    target_margin = 0.20 # 20% Eye Width UI
    
    voltages = np.linspace(v_range[0], v_range[1], 5)
    best_v = v_range[1]
    best_eye = 0.0
    
    print(f"  - Searching Range: {v_range[0]}V to {v_range[1]}V")
    
    for v in sorted(voltages, reverse=True):
        res = run_si_with_voltage(config_path, round(v, 3))
        eye = res.get('eye_width_ui', 0.0)
        
        print(f"    - Testing {v:.3f}V: Eye Width = {eye:.3f} UI")
        
        if eye >= target_margin:
            best_v = v
            best_eye = eye
        else:
            # If we fall below margin, stop searching lower
            break
            
    print(f"  ✅ AVS Optimal Point: {best_v:.3f}V (Eye: {best_eye:.3f} UI)")
    
    # Update Final Config
    config['packaging']['vddq_v'] = round(float(best_v), 3)
    config['si_analysis_v3']['eye_width_ui'] = best_eye
    config['avs_optimized'] = True
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    optimize_avs(args.config)
