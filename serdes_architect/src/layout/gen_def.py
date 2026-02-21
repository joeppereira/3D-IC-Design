import argparse
import json
import os

def generate_def(args):
    print(f"🏗️ Generating PI/SI-Aware OpenROAD Floorplan...")
    
    with open(args.golden_config, 'r') as f:
        config = json.load(f)
        
    project_name = config.get('project_name', 'Search_King')
    die_size = config.get('die_hierarchy', {}).get('die_0', {}).get('size_mm', [15, 15])
    
    output_tcl = 'scripts/floorplan.tcl'
    os.makedirs(os.path.dirname(output_tcl), exist_ok=True)
    
    with open(output_tcl, 'w') as f:
        f.write(f"# OpenROAD PI/SI-Aware Floorplan for {project_name}\n")
        f.write("# Calibrated for 200W SoP with BSPDN support\n\n")
        
        # 1. Grid Awareness: Units in Microns (um)
        scale = 1000.0
        die_w = die_size[0] * scale
        die_h = die_size[1] * scale
        grid = 10.0 # 10um snapping grid
        
        f.write(f"initialize_floorplan -die_area \"0 0 {die_w} {die_h}\" -core_area \"100 100 {die_w-100} {die_h-100}\" -site unithd\n\n")
        
        # 2. Power Integrity (PDN Grid Definition)
        f.write("# PDN Mesh: M4/M5 for local distribution, M10/M11 for global trunk\n")
        f.write("pdngen -report_only 0\n")
        f.write("add_pdn_stripe -grid stdgrid -layer Metal4 -width 0.5 -pitch 10.0 -offset 2.0\n")
        f.write("add_pdn_stripe -grid stdgrid -layer Metal10 -width 2.0 -pitch 50.0 -offset 5.0\n\n")
        
        # 3. Macro Placement (Heat Spread & SI Aware)
        # Snap to grid function
        def snap(val): return round(val / grid) * grid

        # North/South Escape (SerDes)
        for i in range(8):
            nx = snap(1000 + i*1800) # Increased pitch for SI isolation
            ny = snap(die_h - 1500)
            f.write(f"place_cell -inst_name SERDES_N_{i} -origin \"{nx} {ny}\" -orient N -status FIRM\n")
            
            sx = nx
            sy = snap(500)
            f.write(f"place_cell -inst_name SERDES_S_{i} -origin \"{sx} {sy}\" -orient N -status FIRM\n")
            
        # East/West (UCIe DRAM)
        for i in range(8):
            wy = snap(1000 + i*1800)
            wx = snap(500)
            f.write(f"place_cell -inst_name UCIE_W_{i} -origin \"{wx} {wy}\" -orient E -status FIRM\n")
            
            ex = snap(die_w - 1500)
            ey = wy
            f.write(f"place_cell -inst_name UCIE_E_{i} -origin \"{ex} {ey}\" -orient W -status FIRM\n")
            
        # 4. Security & SI Isolation (Keep-out)
        f.write("\n# Caliptra RoT Security Keep-out (250um EM Shielding)\n")
        rot_x, rot_y = snap(die_w/2), snap(2000)
        f.write(f"place_cell -inst_name Caliptra_RoT -origin \"{rot_x} {rot_y}\" -orient N -status FIRM\n")
        f.write(f"add_keepout_margin -inst_name Caliptra_RoT -margin 250\n")
        
        # 5. Routing Grid / Signal Integrity
        f.write("\n# Signal Integrity: G-S-G Routing Tracks for 224G lanes\n")
        f.write("make_tracks Metal7 -x_offset 0.2 -x_pitch 0.4 -y_offset 0.2 -y_pitch 0.4\n")
        
        # 6. Clock Tree Synthesis (CTS) Awareness
        f.write("\n# Clock Tree Synthesis (CTS): H-Tree topology for unified clock distribution\n")
        f.write("create_clock -name sys_clk -period 0.5 [get_ports clk_in]\n")
        f.write("set_clock_tree_exceptions -exclude [get_pins Caliptra_RoT/clk]\n")
        f.write("set_max_skew 0.05 [get_clocks sys_clk]\n")
        
        # 7. Protocol-Specific Routing Constraints
        f.write("\n# Protocol Routing: Differential pairs for PCIe7/RDMA, SE for LPDDR6\n")
        f.write("set_net_routing_rule [get_nets -hier *serdes*] -rule diff_pair_rule\n")
        f.write("set_net_routing_rule [get_nets -hier *lpddr*] -rule single_ended_rule\n")
        
    print(f"  ✅ Generated PI/SI-Aware floorplan: {output_tcl}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--golden_config', type=str, required=True)
    args = parser.parse_args()
    generate_def(args)
