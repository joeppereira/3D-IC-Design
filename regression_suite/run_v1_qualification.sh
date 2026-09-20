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
echo "[3/5] Comparing measurements against Architectural Baseline v1.0..."
python3 <<EOF
import json
import sys

with open('regression_suite/v1.0_baseline.json') as f:
    baseline = json.load(f)
with open('physics_accelerated/results/golden_config.json') as f:
    current = json.load(f)

# The SI result key is 'si_analysis_v3'. This read 'si_verification', which
# has never existed in golden_config.json, so res was always {} and eye was
# always the 0 default -- the gate compared nothing and failed on a constant.
# Missing keys are now a hard error rather than a silent default.
SI_KEY = 'si_analysis_v3'
if SI_KEY not in current:
    print(f'❌ FAILED: golden_config.json has no {SI_KEY!r}. '
          f'Present keys: {sorted(current)}')
    sys.exit(1)
res = current[SI_KEY]
if 'eye_width_ui' not in res:
    print(f'❌ FAILED: {SI_KEY} has no eye_width_ui: {res}')
    sys.exit(1)

floorplan = current.get('floorplan', {})
if 'estimated_max_temp' not in floorplan:
    print('❌ FAILED: golden_config.json has no floorplan.estimated_max_temp')
    sys.exit(1)
temp = floorplan['estimated_max_temp']
eye = res['eye_width_ui']
print(f"  - SI status: {res.get('status', 'n/a')}")

b_temp = baseline['measurements']['thermal_peak_c']
b_eye = baseline['measurements']['eye_margin_ui']

print(f'  - Current Temp: {temp:.1f}C (Baseline: {b_temp}C)')
print(f'  - Current Eye:  {eye:.3f} UI (Baseline: {b_eye} UI)')

t_max = baseline['qualification_thresholds']['thermal_max_c']
e_min = baseline['qualification_thresholds']['min_eye_margin_ui']

if temp <= t_max and eye >= e_min:
    print('✅ VERIFIED: System meets v1.0 architectural thresholds.')
else:
    print('❌ FAILED: System violates v1.0 architectural thresholds.')
    sys.exit(1)
EOF

# 4. Sensitivity Audit
echo "[4/5] Running Sensitivity Analysis..."
python3 serdes_architect/scripts/generate_sensitivity_report.py > /dev/null

# 5. Pareto Integrity
echo "[5/5] Checking Pareto Visualization Stability..."
python3 serdes_architect/src/pareto_visualizer.py > /dev/null

echo "🏁 Architectural Verification: PASSED"