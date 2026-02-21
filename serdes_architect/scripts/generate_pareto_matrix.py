import json
import os
import random

configs_dir = "configs/pareto_matrix"
os.makedirs(configs_dir, exist_ok=True)

# 2026 Realistic Benchmarks
# XSR: 0.3 pJ/b
# VSR: 0.8 pJ/b
# MR:  1.5 pJ/b
# LR:  2.5 pJ/b

def generate_config(option_id, group_name, pkg_type, interconnect, interposer, pdn, cooling="Passive"):
    # Base params
    reach = 5.0 + (option_id * 50.0) 
    bw = 112.0
    if option_id > 15: bw = 224.0
    
    # 1. Differentiate Die Size (Fixes Area Congestion)
    if "CoWoS" in group_name: side = 12 # 144 mm2
    elif "3D_Hetero" in group_name: side = 10 # 100 mm2
    elif "SoP" in group_name: side = 8 # 64 mm2 (Dense)
    elif "CPO" in group_name: side = 15 # 225 mm2
    elif "Wafer_Scale" in group_name: side = 25 # 625 mm2
    else: side = 10
    
    # Heuristic for IO Efficiency (pJ/b)
    if reach < 10: pjb = 0.3
    elif reach < 100: pjb = 0.8
    elif reach < 500: pjb = 1.5
    else: pjb = 2.5
    
    # Power for Thermal
    logic_pwr = 50.0 + (option_id * 5.0) 
    
    cfg = {
        "project_name": f"Opt_{option_id:02d}_{group_name}",
        "reach_mm": reach,
        "target_bandwidth_gbps": bw,
        "max_power_budget_w": logic_pwr,
        "io_efficiency_pjb": pjb,
        "packaging": {
            "topology": pkg_type,
            "interconnect": interconnect,
            "interposer": interposer,
            "pdn_strategy": pdn,
            "cooling": cooling,
            "material_name": "Megtron7"
        },
        "die_hierarchy": {
            "die_0": {"name": "Logic", "type": "3nm", "size_mm": [side, side]},
            "die_1": {"name": "SRAM", "type": "Stacked", "size_mm": [side, side]}
        },
        "voxel_stack_params": {
            "layers": 5, "grid_size": 16,
            "k_map": {
                "Die": 140.0,
                "Interposer": 140.0 if "Silicon" in interposer else (2000.0 if "Diamond" in interposer else 1.2),
                "Package": 0.3
            }
        },
        "constraints": {"min_isolation_db": 35, "modulation": "PAM4", "fec_preference": "inner"}
    }
    
    if "Backside" in pdn: cfg["packaging"]["cooling"] += "_BSPDN"
    if "Diamond" in interposer: cfg["voxel_stack_params"]["k_map"]["Package"] = 10.0 # Better package integration
        
    return cfg

configs = []
for i in range(1, 5): configs.append(generate_config(i, "CoWoS", "Side_by_Side_2.5D", "Microbumps", "Silicon", "Frontside"))
for i in range(5, 9): configs.append(generate_config(i, "3D_Hetero", "Face_to_Face", "Hybrid_Bond", "Silicon", "Backside"))
for i in range(9, 13): configs.append(generate_config(i, "SoP_Diamond", "Face_to_Face", "Hybrid_Bond", "Diamond", "Backside"))
for i in range(13, 17): configs.append(generate_config(i, "CPO_Optics", "Side_by_Side_2.5D", "Photonics", "Glass", "Frontside"))
for i in range(17, 21): configs.append(generate_config(i, "Wafer_Scale", "Wafer_Scale_Integration", "RDL", "Silicon", "Dual-Side"))

for cfg in configs:
    with open(os.path.join(configs_dir, f"{cfg['project_name']}.json"), 'w') as f:
        json.dump(cfg, f, indent=2)

print(f"Generated {len(configs)} Calibrated Pareto Matrix configurations.")