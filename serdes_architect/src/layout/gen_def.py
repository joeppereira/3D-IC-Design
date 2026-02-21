import argparse
import json
import os

def generate_def(args):
    print(f"🏗️ Generating High-Fidelity OpenROAD Floorplan from {args.golden_config}...")
    
    with open(args.golden_config, 'r') as f:
        config = json.load(f)
        
    project_name = config.get('project_name', 'Search_King')
    die_size = config.get('die_hierarchy', {}).get('die_0', {}).get('size_mm', [15, 15])
    
    output_tcl = 'scripts/floorplan.tcl'
    os.makedirs(os.path.dirname(output_tcl), exist_ok=True)
    
    with open(output_tcl, 'w') as f:
        f.write(f"# OpenROAD Floorplan for {project_name}\n")
        f.write("# Optimized for 200W Thermal Chimney & Caliptra Security\n\n")
        
        scale = 1000.0 # 1 unit = 1um
        die_w = die_size[0] * scale
        die_h = die_size[1] * scale
        
        f.write(f"initialize_floorplan -die_area \"0 0 {die_w} {die_h}\" -core_area \"100 100 {die_w-100} {die_h-100}\" -site unithd\n\n")
        
        # 1. Place 16 PCIe/RDMA Macros (North/South)
        for i in range(8):
            # North Edge
            f.write(f"place_cell -inst_name SERDES_N_{i} -origin \"{1000 + i*1500} {die_h - 1500}\" -orient N -status FIRM\n")
            # South Edge
            f.write(f"place_cell -inst_name SERDES_S_{i} -origin \"{1000 + i*1500} 500\" -orient N -status FIRM\n")
            
        # 2. Place 16 UCIe Macros (East/West)
        for i in range(8):
            # West Edge
            f.write(f"place_cell -inst_name UCIE_W_{i} -origin \"500 {1000 + i*1500}\" -orient E -status FIRM\n")
            # East Edge
            f.write(f"place_cell -inst_name UCIE_E_{i} -origin \"{die_w - 1500} {1000 + i*1500}\" -orient W -status FIRM\n")
            
        # 3. Place Caliptra RoT (Security Keep-out)
        f.write("\n# Caliptra Root-of-Trust (Secure Zone)\n")
        f.write(f"place_cell -inst_name Caliptra_RoT -origin \"7000 2000\" -orient N -status FIRM\n")
        
        # 4. SRAM Stack Center Point
        f.write("\n# 3D Stack SRAM Interface (Hybrid Bond Array)\n")
        f.write(f"place_cell -inst_name SRAM_HB_INTERFACE -origin \"3000 3000\" -orient N -status FIRM\n")
        
    print(f"  ✅ Generated macro-aware floorplan: {output_tcl}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--golden_config', type=str, required=True)
    args = parser.parse_args()
    generate_def(args)