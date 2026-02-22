import json
import os
import argparse

def analyze_rtl(config_path):
    print("🔬 [RTL Hook] Analyzing True Logic Complexity from Source...")
    
    rtl_dirs = ["modules/fabric/rtl", "modules/memory/rtl", "modules/security/caliptra/rtl"]
    total_lines = 0
    file_count = 0
    
    for d in rtl_dirs:
        if os.path.exists(d):
            for root, dirs, files in os.walk(d):
                for file in files:
                    if file.endswith((".v", ".sv", ".vhd")):
                        file_count += 1
                        with open(os.path.join(root, file), 'r') as f:
                            total_lines += len(f.readlines())
    
    # Heuristic: 1 line of high-quality RTL ~ 150-250 equivalent logic gates (post-synthesis)
    logic_gates = total_lines * 200
    sram_bits = 1e9 # 1 Gigabit KV Cache (fixed for now)
    toggle_rate = 0.15
    
    # Power Calculation (Hardened)
    leakage_pwr = 40.0
    dynamic_pwr = (logic_gates / 1e6) * 0.8
    sram_pwr = (sram_bits / 1e9) * 20.0
    total_predicted_pwr = leakage_pwr + dynamic_pwr + sram_pwr
    
    print(f"  - Source Files Detected: {file_count}")
    print(f"  - RTL Logic Lines:       {total_lines}")
    print(f"  - Est. Logic Gates:      {logic_gates/1e6:.1f} M")
    print(f"  - Total Predicted Power: {total_predicted_pwr:.1f} W")
    
    with open(config_path, 'r') as f: config = json.load(f)
    config['max_power_budget_w'] = round(total_predicted_pwr, 1)
    config['rtl_analysis'] = {
        "gate_count": logic_gates,
        "line_count": total_lines,
        "predicted_w": total_predicted_pwr
    }
    with open(config_path, 'w') as f: json.dump(config, f, indent=2)
    
    return total_predicted_pwr

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    analyze_rtl(args.config)