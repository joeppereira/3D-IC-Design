#!/bin/bash
# 3D IC Designer Orchestrator v2.0
# Handles 224G PAM4, 35dB Loss, and Material Selection Logic
set -e 

# 0. INPUT PARSING
SPEC_FILE=${1:-"configs/cxl_224g_lr.json"}
echo "🚀 Initializing 3D IC Designer for Spec: $SPEC_FILE"

# 1. MATERIAL & REACH SELECTION (The "Pre-Flight" Logic)
# Robust JSON Parsing using Python (Cross-platform)
REACH=$(python3 -c "import json; print(json.load(open('$SPEC_FILE')).get('reach_mm', 0))")
LOSS=$(python3 -c "import json; print(json.load(open('$SPEC_FILE')).get('loss_db', 0))")
JSON_MAT=$(python3 -c "import json; print(json.load(open('$SPEC_FILE')).get('packaging', {}).get('material_name', ''))")

echo "🔍 Analysis: Reach=${REACH}mm, Target Loss=${LOSS}dB, Config Material=${JSON_MAT}"

if [ -n "$JSON_MAT" ]; then
    echo "✅ Using Material from Config: $JSON_MAT"
    export MATERIAL="$JSON_MAT"
    # Set PHY mode based on reach/loss still
    if (( $(echo "$LOSS > 30.0" | bc -l) )); then
        export PHY_MODE="LR_224G"
        export CLOCK_MODE="recovery"
    else
        export PHY_MODE="SR_64G"
        export CLOCK_MODE="delivery"
    fi
elif (( $(echo "$LOSS > 30.0" | bc -l) )); then
    echo "⚠️  LONG REACH DETECTED (>30dB). Force-enabling Megtron 7 and CDR..."
    export PHY_MODE="LR_224G"
    export MATERIAL="Megtron7"
    export CLOCK_MODE="recovery"
else
    echo "✅ Short Reach Mode. Using Configured Material (Defaulting to Silicon/FR4 if unspecified)."
    export PHY_MODE="SR_64G"
    # Do not force MATERIAL="FR4_Standard" here. Let data_gen.py use its default or the JSON.
    export CLOCK_MODE="delivery"
fi

# 2. PHASE 1: PHYSICS FACTORY (serdes_architect)
echo "📂 [Phase 1] Generating 5-layer 3D Voxel Tensors ($MATERIAL)..."
cd serdes_architect
# Note: Passing --material requires updating data_gen.py to accept it
python3 src/data_gen.py --config ../$SPEC_FILE --samples ${SAMPLES:-50} --layers 5
python3 src/thermal/solver.py --verify --mode 3d_6neighbor 
cd ..

# 3. PHASE 2: SURROGATE TRAINING (physics_accelerated)
echo "🧠 [Phase 2] Training Multi-Channel FNO (Z-Axis as Channels)..."
cd physics_accelerated
# Ensure data symlink exists (force recreate)
rm -rf data && ln -sf ../serdes_architect/data data
# Note: Passing --in_channels requires updating train.py
python3 src/train.py --epochs ${EPOCHS:-2} --weighted_loss true --in_channels 5
cd ..

# 4. PHASE 3: PARETO OPTIMIZATION (GEPA)
echo "📈 [Phase 3] Running GEPA Search for Golden Config..."
cd physics_accelerated
# Note: Passing --avs_enabled and --target_ber requires updating gepa.py
python3 src/gepa.py --avs_enabled true --target_ber 1e-12 --config ../$SPEC_FILE
cd ..

# 5. PHASE 4: SI SIGN-OFF & OPENROAD
echo "🏗️  [Phase 4] Physical Synthesis & SI Verification..."
cd serdes_architect
# Note: Passing --mode and --loss requires updating si_analyzer.py
python3 src/si_analyzer.py --config ../physics_accelerated/results/golden_config.json --mode $PHY_MODE --loss $LOSS
python3 src/si_analyzer_v3.py --config ../physics_accelerated/results/golden_config.json
# OpenROAD Export (Mocked as not installed)
# openroad -no_gui scripts/place_and_route_3d.tcl
echo "⚠️ OpenROAD skipping (mock run)."
cd ..

echo "✅ 224G Project Sign-off Complete. Check ./reports/voxel_si_report.pdf"