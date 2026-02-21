import json
import glob
import csv
import os

results_dir = "reports/pareto_matrix"
output_csv = "reports/pareto_data.csv"

# Cost Heuristics
COST_MAP = {
    "Silicon": 1.0,
    "Glass": 1.5,
    "Diamond": 3.5,
    "Organic": 0.8
}

TOPOLOGY_COST = {
    "Side_by_Side_2.5D": 1.0,
    "Face_to_Face": 1.8, # Hybrid bonding is pricier
    "Wafer_Scale_Integration": 2.5
}

def calculate_cost(config):
    # Base cost from Interposer material
    pkg = config.get('packaging', {})
    mat = pkg.get('interposer', 'Silicon')
    base = COST_MAP.get(mat, 1.0)
    
    # Topology multiplier
    topo = pkg.get('topology', 'Side_by_Side_2.5D')
    mult = TOPOLOGY_COST.get(topo, 1.0)
    
    # Cooling multiplier
    cooling = pkg.get('cooling', 'Passive')
    if "BSPDN" in cooling: mult += 0.5
    
    return base * mult

with open(output_csv, 'w', newline='') as csvfile:
    fieldnames = ['design_name', 'package_type', 'interposer', 'power_efficiency_pjb', 'die_area_mm2', 'thermal_tj_c', 'link_eye_margin_ui', 'relative_cost']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    
    files = sorted(glob.glob(os.path.join(results_dir, "*_result.json")))
    print(f"Harvesting data from {len(files)} simulations...")
    
    for f in files:
        try:
            with open(f, 'r') as json_file:
                data = json.load(json_file)
                
            name = data.get('project_name', 'Unknown')
            
            # 1. Power Efficiency (pJ/b)
            eff = data.get('io_efficiency_pjb', 1.0)
            
            # 2. Area
            die0 = data.get('die_hierarchy', {}).get('die_0', {}).get('size_mm', [10,10])
            area = die0[0] * die0[1]
            
            # 3. Thermal
            temp = data.get('floorplan', {}).get('estimated_max_temp', 25.0)
            
            # 4. Eye Margin
            # Prefer V3 analysis
            si = data.get('si_analysis_v3', {})
            if not si:
                si = data.get('si_signoff', {})
            eye = si.get('eye_width_ui', 0.0)
            
            # 5. Cost
            cost = calculate_cost(data)
            
            # Metadata
            pkg = data.get('packaging', {})
            
            writer.writerow({
                'design_name': name,
                'package_type': pkg.get('topology', 'Unknown'),
                'interposer': pkg.get('interposer', 'Unknown'),
                'power_efficiency_pjb': round(eff, 2),
                'die_area_mm2': area,
                'thermal_tj_c': round(temp, 1),
                'link_eye_margin_ui': round(eye, 3),
                'relative_cost': round(cost, 2)
            })
        except Exception as e:
            print(f"Error processing {f}: {e}")

print(f"Data harvested to {output_csv}")
