import json
import os
import itertools
import copy

configs_dir = "configs"
os.makedirs(configs_dir, exist_ok=True)

# 1. Link Sweep Matrix
speeds = [16, 32, 64, 112, 224]
clocking_options = ["Forwarded", "CDR"]
fec_options = ["None", "Inner"]

# Helper to determine modulation based on speed (typical industry standards)
def get_mod(speed):
    if speed <= 16: return "NRZ"
    if speed <= 32: return "PAM2" # Explicit request
    return "PAM4"

def get_material_reach(speed):
    # Recommend materials that will PASS SI checks
    if speed <= 32: 
        return "FR4", 100.0, 10.0 # Standard Reach
    elif speed <= 64:
        return "Megtron7", 150.0, 12.0 # Medium Reach
    elif speed <= 112:
        return "Megtron7", 100.0, 15.0 # Shorter Reach for higher speed
    else: # 224G
        return "Flyover", 500.0, 12.0 # Long Reach with Twinax (Low Loss)

count = 0
for speed, clock, fec in itertools.product(speeds, clocking_options, fec_options):
    mod = get_mod(speed)
    material, reach, loss = get_material_reach(speed)
    
    # Calculate realistic power for thermal simulation
    # Assume a 4 Tbps Switch filled with these links
    # pJ/b heuristic
    eff = 2.0 # Baseline NRZ
    if "PAM4" in mod: eff += 3.0
    if "CDR" in clock: eff += 2.0
    if speed >= 112: eff += 3.0 # DSP penalty
    
    total_throughput_gbps = 4096.0
    power_w = (total_throughput_gbps * eff) / 1000.0
    
    filename = f"sweep_{speed}g_{mod}_{clock}_{fec}.json".lower()
    
    spec = {
        "project_name": f"LinkSweep_{speed}G_{mod}",
        "reach_mm": reach,
        "loss_db": loss,
        "target_bandwidth_gbps": float(speed),
        "max_power_budget_w": power_w, # Differentiated Thermal Load
        "packaging": {"topology": "Side_by_Side_2.5D", "material_name": material},
        "die_hierarchy": {"die_0": {"name": "Test_Die", "type": "5nm", "size_mm": [5, 5]}},
        "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
        "constraints": {
            "min_isolation_db": 30, 
            "modulation": mod,
            "fec_preference": fec.lower(),
            "clock_mode": clock
        }
    }
    
    with open(os.path.join(configs_dir, filename), 'w') as f:
        json.dump(spec, f, indent=2)
    count += 1

print(f"Generated {count} Link Sweep configurations.")

# 2. CXL Switch SoP (The "Thermal Chimney") - Must use High-End Material
sop_spec = {
    "project_name": "CXL_Switch_SoP_1TB",
    "reach_mm": 300.0, # Mid-board reach
    "loss_db": 18.0,
    "target_bandwidth_gbps": 224.0, # RDMA Return
    "max_power_budget_w": 200.0, # 150W Switch + 40W SRAM
    "packaging": {
        "topology": "Face_to_Face", # SRAM on Switch
        "material_name": "Megtron7", # High Quality Laminate
        "interposer": "Silicon_Interposer"
    },
    "die_hierarchy": {
        "die_0": {"name": "CXL_Switch_Logic", "type": "3nm_FinFET", "size_mm": [15, 15]}, # Base (Calculated)
        "die_1": {"name": "SRAM_Search_Die", "type": "Stacked_SRAM", "size_mm": [12, 12]}  # Top (Smaller)
    },
    "voxel_stack_params": {
        "layers": 5,
        "grid_size": 16,
        "k_map": {
            "Die": 140.0, # Silicon
            "Metal_Stack": 380.0, # Copper
            "C4_BGA": 50.0,
            "Package": 0.3
        }
    },
    "constraints": {
        "min_isolation_db": 40,
        "reliability_years": 10,
        "fec_preference": "inner",
        "modulation": "PAM4"
    }
}

with open(os.path.join(configs_dir, "cxl_switch_sop_1tb.json"), 'w') as f:
    json.dump(sop_spec, f, indent=2)

print("Generated CXL Switch SoP configuration.")

# 2b. CXL Switch SoP (Mitigated with BSPDN)
# Deep copy to avoid reference issues
sop_mitigated = copy.deepcopy(sop_spec)
sop_mitigated["project_name"] = "CXL_Switch_SoP_Mitigated"
sop_mitigated["packaging"]["cooling"] = "BSPDN_Liquid" # Active cooling
sop_mitigated["voxel_stack_params"]["k_map"]["Package"] = 100.0 # Boost package k to simulate backside copper

with open(os.path.join(configs_dir, "cxl_switch_sop_mitigated.json"), 'w') as f:
    json.dump(sop_mitigated, f, indent=2)

print("Generated CXL Switch SoP (Mitigated) configuration.")

# 3. Specific Scenarios (A, B, C, D) - Tuned for demonstration
scenarios = [
    {
        "filename": "scenario_a_64g_2.5d.json",
        "spec": {
            "project_name": "Scenario_A_Baseline",
            "reach_mm": 50.0,
            "loss_db": 5.0,
            "target_bandwidth_gbps": 64.0,
            "packaging": {"topology": "Side_by_Side_2.5D", "material_name": "FR4"}, # 50mm FR4 is OK
            "die_hierarchy": {"die_0": {"name": "Logic_64G", "type": "5nm", "size_mm": [10, 10]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 30, "modulation": "PAM4"}
        }
    },
    {
        "filename": "scenario_b_112g_f2f.json",
        "spec": {
            "project_name": "Scenario_B_3D_Hotspot",
            "reach_mm": 10.0, # Very Short Reach
            "loss_db": 4.0,
            "target_bandwidth_gbps": 112.0,
            "packaging": {"topology": "Face_to_Face", "material_name": "FR4"}, # 3D Stacking -> Thermal Concern
            "die_hierarchy": {"die_0": {"name": "Logic_112G", "type": "3nm", "size_mm": [12, 12]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 35, "modulation": "PAM4"}
        }
    },
    {
        "filename": "scenario_c_224g_lr_fr4_fail.json",
        "spec": {
            "project_name": "Scenario_C_Physics_Wall",
            "reach_mm": 800.0, # Long Reach
            "loss_db": 35.0,
            "target_bandwidth_gbps": 224.0,
            "packaging": {"topology": "Side_by_Side_2.5D", "material_name": "FR4"}, # FR4 at 800mm -> FAIL
            "die_hierarchy": {"die_0": {"name": "Switch_224G", "type": "3nm", "size_mm": [15, 15]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 40, "modulation": "PAM4"}
        }
    },
    {
        "filename": "scenario_d_224g_lr_meg7_fix.json",
        "spec": {
            "project_name": "Scenario_D_Material_Fix",
            "reach_mm": 800.0, # Long Reach
            "loss_db": 12.0,   
            "target_bandwidth_gbps": 224.0,
            "packaging": {"topology": "Side_by_Side_2.5D", "material_name": "Flyover"}, # Flyover Fix
            "die_hierarchy": {"die_0": {"name": "Switch_224G", "type": "3nm", "size_mm": [15, 15]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 40, "modulation": "PAM4"}
        }
    },
    {
        "filename": "test_xsr_fwd_gain.json",
        "spec": {
            "project_name": "Test_XSR_Fwd_Gain",
            "reach_mm": 20.0, # < 1 inch. Should get Fwd Clock Bonus.
            "loss_db": 2.0,
            "target_bandwidth_gbps": 112.0,
            "packaging": {"topology": "Face_to_Face", "material_name": "Megtron7"},
            "die_hierarchy": {"die_0": {"name": "Test", "type": "3nm", "size_mm": [5, 5]}},
            "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}},
            "constraints": {"min_isolation_db": 40, "modulation": "PAM4", "clock_mode": "Forwarded", "fec_preference": "none"}
        }
    }
]

for s in scenarios:
    path = os.path.join(configs_dir, s["filename"])
    with open(path, 'w') as f:
        json.dump(s["spec"], f, indent=2)
    print(f"Generated: {path}")