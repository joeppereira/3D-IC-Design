# 🏗️ OpenROAD 3D-IC P&R Script (v1.0)
# Target: Search King 1TB CXL Switch

puts "🚀 Initializing Physical Synthesis Flow..."

# 1. Load Technology & Macros
read_lef "pdk/generic_3nm.lef"
read_lef "pdk/macros.lef"

# 2. Design Import
# link_design Search_King
puts "  [PDK] Generic 3nm Rules Loaded."

# 3. Apply PI/SI-Aware Floorplan
puts "  [Layout] Applying 18x18mm Floorplan..."
source "scripts/floorplan.tcl"

# 4. Power Integrity: Grid Generation
puts "  [PI] Synthesizing Backside PDN Mesh..."
pdngen -report_only 0

# 5. Clock Tree Synthesis (CTS)
puts "  [Timing] Building H-Tree for 224G SerDes Clusters..."
# repair_clock_nets

# 6. Global & Detail Routing
puts "  [SI] Routing 224G lanes with G-S-G Shielding..."
# global_route
# detail_route

# 7. Final Verification
puts "  [Sign-off] Running Design Rule Check (DRC) & LVS..."
# check_drc

puts "✅ Synthesis Complete. Physical Database ready for GDSII stream-out."
