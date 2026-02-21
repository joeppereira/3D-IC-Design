import json
import glob
import os

print("\n📊 3D IC Deep Analysis Report: Standards Compliance Matrix")
print("===============================================================================================================================================")
print(f"{ 'Scenario':<20} | { 'Proto':<8} | { 'Reach':<5} | { 'Mod':<4} | { 'Sig':<4} | { 'Term':<4} | { 'FEC':<5} | { 'Lanes':<8} | { 'Pwr(W)':<6} | { 'Eye':<6} | { 'Status'}")
print(f"{ '':<20} | { '':<8} | { '':<5} | { '':<4} | { '':<4} | { '(Ohm)':<4} | { '':<5} | { 'D / C':<8} | { '':<6} | { '(UI)':<6} | { '':<6}")
print("-----------------------------------------------------------------------------------------------------------------------------------------------")

results_dir = "reports/batch_analysis"
files = sorted(glob.glob(os.path.join(results_dir, "proto_*_result.json")))

for f in files:
    with open(f, 'r') as file:
        res = json.load(file)
        
    name = res.get('project_name', os.path.basename(f))
    reach_cls = res.get('reach_classification', 'N/A')
    
    constraints = res.get('constraints', {})
    proto = constraints.get('protocol', '-')
    mod = constraints.get('modulation', '-')
    sig_type = constraints.get('signaling', 'Diff')
    fec = constraints.get('fec_preference', 'none')
    term = res.get('packaging', {}).get('termination', 100)
    
    # Lanes
    num_data = 1
    num_clock = 0 # CDR default
    lane_str = f"{num_data}/{num_clock}"
    
    # Power
    display_pwr = res.get('max_power_budget_w', 0.0)
    
    # Results
    si_v3 = res.get('si_analysis_v3', {})
    eye_ui = si_v3.get('eye_width_ui', 0.0)
    status = si_v3.get('status', '❌ FAIL')
    
    if "PASS" in status: status = "✅ PASS"
    elif "FAIL" in status: status = "❌ FAIL"
    
    print(f"{name:<20} | {proto:<8} | {reach_cls:<5} | {mod:<4} | {sig_type:<4} | {term:<4} | {fec:<5} | {lane_str:<8} | {display_pwr:<6.2f} | {eye_ui:<6.2f} | {status}")

print("===============================================================================================================================================")