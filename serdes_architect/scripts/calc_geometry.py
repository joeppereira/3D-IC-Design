import json
import math

def calculate_die_geometry():
    print("📐 3D SoP Geometry & Connectivity Calculator")
    print("==================================================")
    
    # 1. IO Requirement Analysis
    # Internal (DRAM) Links: 8x UCIe x16
    num_dram_dies = 8
    ucie_macro_width_mm = 2.0 # Assuming 25um pitch optimized
    
    # External (Host/Network) Links: 
    # Prompt says "16 UCIe macros and 16 PCIe/RDMA macros"
    # Let's assume 16 High-Speed SerDes macros for escape.
    num_serdes_macros = 16
    serdes_macro_width_mm = 1.5 # Standard high-speed SerDes
    
    # 2. Beachfront Calculation
    total_ucie_width = num_dram_dies * ucie_macro_width_mm
    total_serdes_width = num_serdes_macros * serdes_macro_width_mm
    
    # Add spacing/overhead (20%)
    required_perimeter = (total_ucie_width + total_serdes_width) * 1.2
    
    print(f"  - DRAM Beachfront: {total_ucie_width:.1f} mm (8 x {ucie_macro_width_mm}mm)")
    print(f"  - Host/Net Beachfront: {total_serdes_width:.1f} mm (16 x {serdes_macro_width_mm}mm)")
    print(f"  - Min Perimeter (with overhead): {required_perimeter:.1f} mm")
    
    # 3. Die Size Derivation
    # Square Die Side Length
    min_side = required_perimeter / 4.0
    
    # Round up to realistic integer
    die_side = math.ceil(min_side)
    if die_side < 15: die_side = 15 # Minimum logic area constraint for 200W?
    
    die_area = die_side * die_side
    
    print(f"  -> Recommended Switch Die Size: {die_side}mm x {die_side}mm ({die_area} mm²)")
    
    # 4. Thermal Density Check
    total_power = 200.0 # W
    power_density = total_power / die_area
    print(f"  -> Avg Power Density: {power_density:.2f} W/mm²")
    
    if power_density > 1.0:
        print("     ⚠️ High Density! Requires Liquid Cooling/BSPDN.")
    else:
        print("     ✅ Manageable Density (<1 W/mm²).")

    # 5. Connectivity Pin-Out Map Generation
    # We will arrange DRAMs on Left/Right and SerDes on Top/Bottom for flow
    # Top: 8 SerDes
    # Bottom: 8 SerDes
    # Left: 4 DRAMs
    # Right: 4 DRAMs
    
    pinout = {
        "die_size": [die_side, die_side],
        "edges": {
            "TOP": [{"type": "RDMA/PCIe", "id": i} for i in range(8)],
            "BOTTOM": [{"type": "RDMA/PCIe", "id": i} for i in range(8, 16)],
            "LEFT": [{"type": "DRAM_UCIe", "id": i} for i in range(4)],
            "RIGHT": [{"type": "DRAM_UCIe", "id": i} for i in range(4, 8)]
        },
        "center": {
            "type": "Hybrid_Bond_Array",
            "target": "SRAM_Search_Die",
            "count": 8192,
            "pitch_um": 5.0
        }
    }
    
    return pinout, die_side

if __name__ == "__main__":
    pinout, side = calculate_die_geometry()
    
    # Save to a file for the main generator to use
    with open("serdes_architect/scripts/switch_geometry.json", "w") as f:
        json.dump(pinout, f, indent=2)
    print("\n✅ Geometry saved to serdes_architect/scripts/switch_geometry.json")
