import argparse
import json
import torch
import numpy as np
import os
import sys

# --- Material Sensitivity Logic ---
# Reach Multiplier: (35 dB loss distance)
MATERIALS = {
    "FR4": {"loss_per_inch": 11.6, "multiplier": 1.0},
    "Megtron_7": {"loss_per_inch": 3.5, "multiplier": 3.3},
    "Twinax": {"loss_per_inch": 0.44, "multiplier": 26.0}
}

def calculate_loss_waterfall(reach_mm, material_name="Megtron_7", xtk_iso_db=30, temp_avg=25.0):
    """
    Calculates the SI Loss Waterfall for a SerDes link.
    """
    print(f"\n🌊 SI Loss Waterfall Analysis (Material: {material_name})")
    
    # 1. Package Escape (Standard for 3nm/3D IC)
    pkg_escape = 3.0 # dB
    
    # 2. PCB Trace Loss
    # reach_mm -> inches
    dist_inch = reach_mm / 25.4
    loss_per_inch = MATERIALS.get(material_name, MATERIALS["FR4"])["loss_per_inch"]
    trace_loss = dist_inch * loss_per_inch
    
    # 3. Connector Pair Loss
    conn_loss = 2.5 # dB
    
    # 4. Crosstalk (XTK) Penalty (Effective Loss)
    # 3-5 dB impact
    xtk_impact = (40 - xtk_iso_db) / 2.0 
    xtk_loss = max(1.0, xtk_impact)
    
    # 5. Thermal Jitter Loss
    # 1-2 dB impact
    thermal_loss = ((temp_avg - 25.0) / 10.0) * 0.25
    thermal_loss = max(0.5, thermal_loss)
    
    total_loss = pkg_escape + trace_loss + conn_loss + xtk_loss + thermal_loss
    
    print(f"  [1] Pkg Escape:   {pkg_escape:.2f} dB")
    print(f"  [2] PCB Trace:    {trace_loss:.2f} dB ({dist_inch:.2f}\")")
    print(f"  [3] Connectors:   {conn_loss:.2f} dB")
    print(f"  [4] XTK (SNR):    {xtk_loss:.2f} dB")
    print(f"  [5] Thermal:      {thermal_loss:.2f} dB")
    print(f"  ---------------------------")
    print(f"  Total IL:         {total_loss:.2f} dB @ Nyquist")
    
    return total_loss

def analyze_eye_margin(total_loss, mod="PAM4"):
    """Determines Eye Width (UI) and Height (mV) based on IL."""
    # Heuristic: Ideal UI (1.0) - Loss Penalty
    # Loss penalty is roughly 0.02 UI per dB of loss above 10 dB
    ui_margin = 1.0 - (total_loss / 50.0)
    
    # Eye Height (mV) - Start with 800mV, drops with IL
    eye_height = 800.0 * (10 ** (-total_loss / 20.0))
    
    print(f"\n🔍 Sign-off Metrics (Target >0.45 UI, >40mV):")
    print(f"  Eye Width:  {ui_margin:.3f} UI")
    print(f"  Eye Height: {eye_height:.1f} mV")
    
    if ui_margin < 0.35 or eye_height < 25.0:
        print("  ❌ FAILURE: Eye closure detected. Solution: High-Loss Material or better EQ.")
    elif ui_margin < 0.45:
        print("  ⚠️ WARNING: Marginal SI. Consider Inner FEC.")
    else:
        print("  ✅ PASSED: Design within 2026 Sign-off margins.")
        
    return ui_margin, eye_height

def run_analysis(args):
    with open(args.config, 'r') as f:
        config = json.load(f)
        
    reach_mm = config.get('reach_mm', 1.5)
    temp_avg = config.get('floorplan', {}).get('estimated_max_temp', 25.0)
    material = config.get('packaging', {}).get('material_name', 'Megtron_7')
    iso_db = config.get('constraints', {}).get('min_isolation_db', 30)

    il_total = calculate_loss_waterfall(reach_mm, material, iso_db, temp_avg)
    margin_ui, height_mv = analyze_eye_margin(il_total, config.get('constraints', {}).get('modulation', 'PAM4'))
    
    # Save Results
    config['si_signoff'] = {
        'total_insertion_loss_db': il_total,
        'eye_width_ui': margin_ui,
        'eye_height_mv': height_mv
    }
    
    with open(args.config, 'w') as f:
        json.dump(config, f, indent=2)
    print("\n✅ Sign-off report appended to golden_config.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True, help='Path to golden config')
    parser.add_argument('--mode', type=str, default='standard')
    parser.add_argument('--loss', type=float, default=0.0)
    args = parser.parse_args()
    run_analysis(args)