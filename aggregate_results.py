import json
import glob
import os

print("\n📊 3D IC Deep Analysis Report: Unified Protocol Breakdown")
print("===============================================================================================================================================")
print(f"{ 'Scenario':<25} | { 'Proto':<8} | { 'Reach':<5} | { 'Mod':<4} | { 'Sig':<4} | { 'Lanes':<8} | { 'Area':<6} | { 'Pwr(W)':<6} | { 'Eye':<6} | { 'Temp':<6} | { 'Status'}")
print(f"{ '':<25} | { '':<8} | { '':<5} | { '':<4} | { '':<4} | { 'D / C':<8} | { '(mm2)':<6} | { '':<6} | { '(UI)':<6} | { '(C)':<6} | { '':<6}")
print("-----------------------------------------------------------------------------------------------------------------------------------------------")

results_dir = "reports/batch_analysis"
files = sorted(glob.glob(os.path.join(results_dir, "*_result.json")))

for f in files:
    with open(f, 'r') as file:
        res = json.load(file)
        
    name = res.get('project_name', os.path.basename(f))
    reach_cls = res.get('reach_classification', 'N/A')
    
    constraints = res.get('constraints', {})
    proto = constraints.get('protocol', '-')
    mod = constraints.get('modulation', '-')
    clock_mode = constraints.get('clock_mode', 'CDR')
    
    # Lanes
    num_data = 1
    if "SoP" in name: num_data = 256
    num_clock = (num_data + 15) // 16 if clock_mode == "Forwarded" else 0
    lane_str = f"{num_data}/{num_clock}"
    
    # Signal Type
    sig_type = "SE" if "PAM2" in mod or "LPDDR" in proto else "Diff"
    
    # Area
    lane_area = 0.06 if sig_type == "SE" else 0.15
    phy_area = (num_data + num_clock) * lane_area
    total_area = 100.0 + phy_area
    
    # Power
    speed = res.get('target_bandwidth_gbps', 0)
    sys_pwr = res.get('max_power_budget_w', 0.0)
    pj_b = 1.5 if "VSR" in reach_cls else 6.5
    if sig_type == "Diff": pj_b += 2.0
    link_pwr = (speed * num_data * pj_b) / 1000.0
    display_pwr = sys_pwr if sys_pwr > 1.0 else link_pwr
    
    # Results
    si_v3 = res.get('si_analysis_v3', {})
    eye_ui = si_v3.get('eye_width_ui', 0.0)
    status = si_v3.get('status', '❌ FAIL')
    temp = res.get('floorplan', {}).get('estimated_max_temp', 0.0)
    
    if "PASS" in status: status = "✅ PASS"
    elif "FAIL" in status: status = "❌ FAIL"
    
    print(f"{name:<25} | {proto:<8} | {reach_cls:<5} | {mod:<4} | {sig_type:<4} | {lane_str:<8} | {total_area:<6.1f} | {display_pwr:<6.2f} | {eye_ui:<6.2f} | {temp:<6.0f} | {status}")

print("===============================================================================================================================================")
