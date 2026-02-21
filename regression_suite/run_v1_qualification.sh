#!/bin/bash
# Regression Suite v1.0 Qualification Script
set -e

echo "🧪 Starting Regression Suite v1.0 Qualification..."

# 1. Physics Verification
echo "[1/5] Verifying 3D FDM Solver..."
source .venv/bin/activate
python3 serdes_architect/src/thermal/solver.py --verify --mode 3d_6neighbor > /dev/null

# 2. Performance-Optimized Iteration (The Baseline)
echo "[2/5] Running Baseline CXL Switch SoP (Mitigated)..."
./run_full_cycle.sh configs/cxl_switch_sop_mitigated.json > regression_suite/baseline_run.log 2>&1

# 3. Capture and Compare
echo "[3/5] Comparing measurements against Baseline v1.0..."
python3 <<EOF
import json
import sys

with open('regression_suite/v1.0_baseline.json') as f:
    baseline = json.load(f)
with open('physics_accelerated/results/golden_config.json') as f:
    current = json.load(f)

res = current.get('si_analysis_v3', {})
temp = current.get('floorplan', {}).get('estimated_max_temp', 0)
eye = res.get('eye_width_ui', 0)

b_temp = baseline['measurements']['thermal_peak_c']
b_eye = baseline['measurements']['eye_margin_ui']

print(f'  - Current Temp: {temp:.1f}C (Baseline: {b_temp}C)')
print(f'  - Current Eye:  {eye:.3f} UI (Baseline: {b_eye} UI)')

t_max = baseline['qualification_thresholds']['thermal_max_c']
e_min = baseline['qualification_thresholds']['min_eye_margin_ui']

if temp <= t_max and eye >= e_min:
    print('✅ QUALIFIED: System meets v1.0 thresholds.')
else:
    print('❌ FAILED: System violates v1.0 thresholds.')
    sys.exit(1)
EOF

# 4. Sensitivity Audit
echo "[4/5] Running Sensitivity Analysis..."
python3 serdes_architect/scripts/generate_sensitivity_report.py > /dev/null

# 5. Pareto Integrity
echo "[5/5] Checking Pareto Visualization Stability..."
python3 serdes_architect/src/pareto_visualizer.py > /dev/null

echo "🏁 Regression Suite v1.0: PASSED"