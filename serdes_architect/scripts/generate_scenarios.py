import json
import os
import itertools
import copy

configs_dir = "configs"
os.makedirs(configs_dir, exist_ok=True)

# 1. Link Sweep Matrix (Unified Data Center Protocols)
speeds = [16, 32, 64, 112, 224]
protocols = ["PCIe5", "PCIe6", "PCIe7", "LPDDR5", "LPDDR6", "UCIe2.0"]
clocking_options = ["Forwarded", "CDR"]
fec_options = ["None", "Inner"]

def get_mod_for_protocol(proto):
    if "LPDDR" in proto: return "PAM2"
    if "PCIe5" in proto: return "NRZ"
    return "PAM4"

def get_material_reach(speed):
    if speed <= 32: return "FR4", 100.0, 10.0
    elif speed <= 112: return "Megtron7", 150.0, 15.0
    else: return "Flyover", 500.0, 12.0

count = 0
# Generate a representative subset of protocol combinations
for proto in protocols:
    for speed in [32, 64, 112, 224]:
        # Skip invalid speed/proto combos
        if "PCIe5" in proto and speed != 32: continue
        if "PCIe6" in proto and speed != 64: continue
        if "LPDDR" in proto and speed > 112: continue
        
        mod = get_mod_for_protocol(proto)
        clock = "CDR" if speed > 32 else "Forwarded"
        fec = "Inner" if speed >= 64 else "None"
        material, reach, loss = get_material_reach(speed)
        
        filename = f"proto_{proto.lower()}_{speed}g.json"
        
        spec = {
            "project_name": f"ProtocolSweep_{proto}_{speed}G",
            "reach_mm": reach,
            "target_bandwidth_gbps": float(speed),
            "max_power_budget_w": (float(speed) * 4096 / 1000.0), # Proportional
            "packaging": {"topology": "Side_by_Side_2.5D", "material_name": material},
            "die_hierarchy": {"die_0": {"name": "Proto_Die", "type": "3nm", "size_mm": [10, 10]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {
                "min_isolation_db": 30, 
                "modulation": mod,
                "fec_preference": fec.lower(),
                "clock_mode": clock,
                "protocol": proto
            }
        }
        
        with open(os.path.join(configs_dir, filename), 'w') as f:
            json.dump(spec, f, indent=2)
        count += 1

print(f"Generated {count} Unified Protocol Sweep configurations.")

# 2. CXL Switch SoP (The "Search King" V2)
sop_spec = {
    "project_name": "CXL_Switch_SoP_1TB_V2",
    "reach_mm": 300.0,
    "target_bandwidth_gbps": 224.0,
    "max_power_budget_w": 200.0,
    "packaging": {
        "topology": "Face_to_Face",
        "material_name": "Flyover",
        "interposer": "Silicon_Interposer",
        "cooling": "BSPDN_Liquid"
    },
    "die_hierarchy": {
        "die_0": {"name": "CXL_Switch_Logic", "type": "3nm_FinFET", "size_mm": [15, 15]},
        "die_1": {"name": "SRAM_Search_Die", "type": "Stacked_SRAM", "size_mm": [12, 12]}
    },
    "voxel_stack_params": {
        "layers": 5, "grid_size": 16,
        "k_map": {"Die": 140.0, "Metal_Stack": 380.0, "C4_BGA": 50.0, "Package": 100.0}
    },
    "constraints": {
        "min_isolation_db": 40, "modulation": "PAM4", "fec_preference": "inner", "clock_mode": "CDR",
        "protocol": "CXL3.1", "security": ["SPDM", "DICE"]
    }
}

with open(os.path.join(configs_dir, "cxl_switch_sop_v2.json"), 'w') as f:
    json.dump(sop_spec, f, indent=2)

# 3. Standard Scenarios
scenarios = [
    {
        "filename": "scenario_a_64g_2.5d.json",
        "spec": {
            "project_name": "Scenario_A_Baseline",
            "reach_mm": 50.0, "target_bandwidth_gbps": 64.0,
            "packaging": {"topology": "Side_by_Side_2.5D", "material_name": "FR4"},
            "die_hierarchy": {"die_0": {"name": "Logic_64G", "type": "5nm", "size_mm": [12, 12]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 30, "modulation": "PAM4", "protocol": "PCIe6"}
        }
    },
    {
        "filename": "scenario_d_224g_lr_meg7_fix.json",
        "spec": {
            "project_name": "Scenario_D_Material_Fix",
            "reach_mm": 800.0, "target_bandwidth_gbps": 224.0,
            "packaging": {"topology": "Side_by_Side_2.5D", "material_name": "Flyover"},
            "die_hierarchy": {"die_0": {"name": "Switch_224G", "type": "3nm", "size_mm": [15, 15]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 40, "modulation": "PAM4", "fec_preference": "inner", "protocol": "PCIe7"}
        }
    }
]

for s in scenarios:
    with open(os.path.join(configs_dir, s["filename"]), 'w') as f:
        json.dump(s["spec"], f, indent=2)
