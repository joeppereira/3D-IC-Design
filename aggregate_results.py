import json
import glob
import os

print("\n📊 3D IC Deep Analysis Report: Detailed Architectural Breakdown")
print("=======================================================================================================================================")
print(f"{ 'Scenario':<30} | { 'Reach':<5} | { 'Mod':<4} | { 'Sig':<4} | { 'FEC':<5} | { 'Lanes':<8} | { 'Area':<6} | { 'Pwr(W)':<6} | { 'Loss':<6} | { 'Eye':<6} | { 'Temp':<6} | { 'Status'}")
print(f"{ '':<30} | { '':<5} | { '':<4} | { '':<4} | { '':<5} | { 'D / C':<8} | { '(mm2)':<6} | { '':<6} | { '(dB)':<6} | { '(UI)':<6} | { '(C)':<6} | { '':<6}")
print("---------------------------------------------------------------------------------------------------------------------------------------")

results_dir = "reports/batch_analysis"
files = sorted(glob.glob(os.path.join(results_dir, "*_result.json")))

data = {}

for f in files:
    with open(f, 'r') as file:
        res = json.load(file)
        
    name = res.get('project_name', os.path.basename(f))
    reach_cls = res.get('reach_classification', 'N/A')
    
    constraints = res.get('constraints', {})
    mod = constraints.get('modulation', '-')
    clock_mode = constraints.get('clock_mode', 'CDR')
    fec = constraints.get('fec_preference', 'none')
    if fec == "none": fec = "No"
    elif fec == "inner": fec = "In"
    elif fec == "both": fec = "In+Out"
    
    # Heuristics for Architecture
    speed = res.get('target_bandwidth_gbps', 0)
    
    # Lanes
    # Default to 1 data lane for sweeps, higher for SoP
    num_data = 1
    if "SoP" in name: num_data = 256 # Massive bus
    elif "224G" in name and "Sweep" not in name: num_data = 8
    elif "64G" in name and "Sweep" not in name: num_data = 16
    
    # Clock Lanes
    num_clock = 0
    if clock_mode == "Forwarded":
        # 1 clock diff-pair per 16 data lanes (or part thereof)
        num_clock = (num_data + 15) // 16
    
    lane_str = f"{num_data}/{num_clock}"
    
    # Signal Type
    sig_type = "Diff"
    if "PAM2" in mod: sig_type = "SE"
    
    # Area Calculation (Physics-Based)
    # Diff Lane: ~0.15 mm2 (2 pads + SerDes)
    # SE Lane:   ~0.06 mm2 (1 pad + Driver)
    lane_area = 0.06 if sig_type == "SE" else 0.15
    
    phy_area = (num_data + num_clock) * lane_area
    # Add Logic Core Area (fixed)
    core_area = 100.0
    total_area = core_area + phy_area
    
    # Power Calculation
    # System Budget (from config)
    sys_pwr = res.get('max_power_budget_w', 0.0)
    
    # Link Power (Calculated)
    # Heuristic: pJ/b based on Reach/Mod
    pj_b = 0.5 # Default XSR SE
    if "LR" in reach_cls or "MR" in reach_cls: pj_b = 6.5 # DSP Heavy
    elif "VSR" in reach_cls: pj_b = 1.5
    
    if sig_type == "Diff": pj_b += 2.0 # SerDes overhead
    
    # Total Link Power = Speed * Lanes * pJ/b
    link_pwr = (speed * (num_data) * pj_b) / 1000.0
    
    # Use System Power if defined (SoP), else Link Power (Sweeps)
    display_pwr = sys_pwr if sys_pwr > 1.0 else link_pwr
    
    # Results
    si = res.get('si_signoff', {})
    si_v3 = res.get('si_analysis_v3', {})
    
    loss = si.get('total_insertion_loss_db', 0.0)
    status = "UNK"
    if si_v3:
        loss = si_v3.get('loss', loss)
        status = si_v3.get('status', 'Unknown')
        eye_ui = si_v3.get('eye_width_ui', 0.0)
    else:
        eye_ui = si.get('eye_width_ui', 0.0)
        status = "✅ PASS" if eye_ui > 0.35 else "❌ FAIL"

    temp = res.get('floorplan', {}).get('estimated_max_temp', 0.0)
    
    # Formatting Status to save space
    if "PASS" in status: status = "✅ PASS"
    elif "FAIL" in status: status = "❌ FAIL"
    
    print(f"{name:<30} | {reach_cls:<5} | {mod:<4} | {sig_type:<4} | {fec:<5} | {lane_str:<8} | {total_area:<6.1f} | {display_pwr:<6.2f} | {loss:<6.1f} | {eye_ui:<6.2f} | {temp:<6.0f} | {status}")
    
    data[name] = {'status': status}

print("=======================================================================================================================================")