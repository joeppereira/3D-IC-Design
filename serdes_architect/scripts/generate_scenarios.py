import json
import os

configs_dir = "configs"
os.makedirs(configs_dir, exist_ok=True)

# Master Protocol Lookup Table (Calibrated for Low-Voltage Signaling)
PROTOCOL_LUT = [
    # {proto, speed, mod, sig, reach, vddq, v_range, fec, term, material}
    {"p": "PCIe5",   "s": 32.0,  "m": "NRZ",  "sg": "Diff", "r": 500, "v": 1.0, "vr": [0.95, 1.05], "f": "none",  "t": 100, "mat": "Megtron7"},
    {"p": "PCIe6",   "s": 64.0,  "m": "PAM4", "sg": "Diff", "r": 500, "v": 0.8, "vr": [0.75, 0.85], "f": "inner", "t": 100, "mat": "Megtron7"},
    {"p": "PCIe7",   "s": 128.0, "m": "PAM4", "sg": "Diff", "r": 800, "v": 0.8, "vr": [0.75, 0.85], "f": "both",  "t": 100, "mat": "Flyover"},
    {"p": "PCIe7",   "s": 224.0, "m": "PAM4", "sg": "Diff", "r": 1000,"v": 0.8, "vr": [0.75, 0.85], "f": "both",  "t": 100, "mat": "Flyover"},
    {"p": "LPDDR5",  "s": 6.4,   "m": "PAM2", "sg": "SE",   "r": 25,  "v": 1.1, "vr": [1.0, 1.2],   "f": "none",  "t": 48,  "mat": "FR4"},
    {"p": "LPDDR5X", "s": 8.3,   "m": "PAM2", "sg": "SE",   "r": 25,  "v": 0.3, "vr": [0.28, 0.35], "f": "none",  "t": 48,  "mat": "FR4"},
    {"p": "LPDDR6",  "s": 12.8,  "m": "PAM2", "sg": "SE",   "r": 20,  "v": 0.3, "vr": [0.28, 0.35], "f": "none",  "t": 40,  "mat": "FR4"},
    {"p": "UCIe2.0", "s": 32.0,  "m": "NRZ",  "sg": "SE",   "r": 10,  "v": 0.4, "vr": [0.38, 0.45], "f": "none",  "t": 0,   "mat": "FR4"},
    {"p": "UCIe2.0", "s": 64.0,  "m": "PAM4", "sg": "Diff", "r": 10,  "v": 0.4, "vr": [0.38, 0.45], "f": "none",  "t": 100, "mat": "Silicon"},
    {"p": "UALink",  "s": 128.0, "m": "PAM4", "sg": "Diff", "r": 500, "v": 0.8, "vr": [0.75, 0.85], "f": "both",  "t": 100, "mat": "Flyover"},
    {"p": "UALink",  "s": 200.0, "m": "PAM4", "sg": "Diff", "r": 500, "v": 0.8, "vr": [0.75, 0.85], "f": "both",  "t": 100, "mat": "Flyover"}
]

for row in PROTOCOL_LUT:
    spd_label = f"{row['s']}" if row['s'] % 1 != 0 else f"{int(row['s'])}"
    filename = f"proto_{row['p'].lower()}_{spd_label}g.json"
    
    spec = {
        "project_name": f"{row['p']}_{spd_label}G_Std",
        "reach_mm": float(row['r']),
        "target_bandwidth_gbps": float(row['s']),
        "max_power_budget_w": (float(row['s']) * 4096 / 1000.0) * (row['v'] * row['v']), # V^2 scaling
        "packaging": {
            "topology": "Side_by_Side_2.5D" if row['r'] > 50 else "Face_to_Face",
            "material_name": row['mat'],
            "termination": row['t'],
            "vddq_v": row['v'],
            "vddq_range": row['vr']
        },
        "constraints": {
            "modulation": row['m'],
            "signaling": row['sg'],
            "fec_preference": row['f'],
            "protocol": row['p']
        },
        "die_hierarchy": {"die_0": {"name": "Logic", "type": "3nm", "size_mm": [10, 10]}},
        "voxel_stack_params": {"layers": 5, "grid_size": 16, "k_map": {"Die": 140.0, "Package": 0.3}}
    }
    
    with open(os.path.join(configs_dir, filename), 'w') as f:
        json.dump(spec, f, indent=2)

print(f"Generated {len(PROTOCOL_LUT)} configurations with Low-Voltage (0.8V) awareness.")
