import matplotlib.pyplot as plt
import numpy as np
import json
import argparse

def plot_eye(config_path, output_path):
    with open(config_path, 'r') as f:
        config = json.load(f)
        
    res = config.get('si_analysis_v3', {})
    if not res:
        print("No SI V3 results found.")
        return

    eye_width = res.get('eye_width_ui', 0.0)
    status = res.get('status', 'UNK')
    mod = config.get('constraints', {}).get('modulation', 'PAM4')
    
    print(f"Plotting Eye: {mod}, Width={eye_width:.2f} UI, Status={status}")
    
    t = np.linspace(0, 2, 200)
    plt.figure(figsize=(10, 6))
    
    levels = [0] if mod == "NRZ" else [-0.66, 0, 0.66]
    colors = ['r', 'g', 'b']
    
    for i, center in enumerate(levels):
        # Open Eye logic
        amp = eye_width / 2.0
        # If eye is 0, amp is 0 (closed)
        
        # Top lid
        y_top = center + 0.1 + amp * np.sin(np.pi * t)
        # Bot lid
        y_bot = center - 0.1 - amp * np.sin(np.pi * t)
        
        # Visual trick: if eye is closed (width < 0), lines cross.
        
        plt.plot(t, y_top, color=colors[i%3], alpha=0.8)
        plt.plot(t, y_bot, color=colors[i%3], alpha=0.8)
        plt.fill_between(t, y_top, y_bot, color=colors[i%3], alpha=0.1)

    plt.title(f"Final Sign-off: 224G {mod} (Flyover) - {status}\nEye Width: {eye_width:.3f} UI")
    plt.xlabel("UI")
    plt.ylabel("Voltage (V)")
    plt.grid(True)
    plt.savefig(output_path)
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    plot_eye("physics_accelerated/results/golden_config.json", "reports/final_224g_eye.png")
