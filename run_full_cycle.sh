#!/bin/bash
# 3D IC Designer Orchestrator v3.0 (Closed-Loop Sign-off)
set -e 

SPEC_FILE=${1:-"configs/cxl_switch_sop_v2.json"}
echo "🚀 Initializing v3.0 Silicon Architect (Closed-Loop): $SPEC_FILE"

# 1. RTL & SPEC PRE-FLIGHT
python3 serdes_architect/scripts/rtl_analyzer.py --config $SPEC_FILE

# 2. PHASE 1: PHYSICS FACTORY
echo "📂 [Phase 1] Physics Simulation..."
cd serdes_architect
python3 src/data_gen.py --config ../$SPEC_FILE --samples ${SAMPLES:-50} --layers 5
python3 src/thermal/solver.py --verify --mode 3d_6neighbor 
cd ..

# 3. PHASE 2: SURROGATE TRAINING
echo "🧠 [Phase 2] FNO Surrogate Training..."
cd physics_accelerated
rm -rf data && ln -sf ../serdes_architect/data data
python3 src/train.py --epochs ${EPOCHS:-2} --weighted_loss true --in_channels 5
cd ..

# 4. PHASE 3: GEPA SEARCH
echo "📈 [Phase 3] Multi-Objective Pareto Search..."
cd physics_accelerated
python3 src/gepa.py --avs_enabled true --target_ber 1e-12 --config ../$SPEC_FILE
cd ..

# 5. PHASE 4: PHYSICAL & ELECTRICAL SIGN-OFF (Closed Loop)
echo "🏗️  [Phase 4] Execution of Layout & Extraction..."
cd serdes_architect
GOLDEN="../physics_accelerated/results/golden_config.json"

# A. Generate Initial Layout
python3 src/layout/gen_def.py --golden_config $GOLDEN

# B. Extract Parasitics (Crucial for SI/PI feedback)
python3 src/layout/rc_extractor.py --config $GOLDEN

# C. Feedback-Driven Sign-off Gates
echo "📊 [Phase 4b] Data-Driven Sign-off..."
python3 src/si_analyzer_v3.py --config $GOLDEN
python3 scripts/avs_optimizer.py --config $GOLDEN
python3 src/thermal/ir_drop_solver.py --config $GOLDEN
python3 src/security_analyzer.py --config $GOLDEN
python3 src/thermal/transient_solver.py --config $GOLDEN

# D. Final Summary
python3 scripts/generate_final_summary.py --config $GOLDEN
python3 scripts/generate_comprehensive_signoff.py --config $GOLDEN

echo "✅ v3.0 Sign-off Complete. Post-Layout parasitics integrated into margins."
cd ..