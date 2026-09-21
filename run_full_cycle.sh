#!/bin/bash
# 3D IC Designer Orchestrator v3.1 (Architectural Verification)
set -e 

SPEC_FILE=${1:-"configs/cxl_switch_sop_v4.json"}
echo "🚀 Initializing v3.1 Silicon Architect (Architectural Pass Flow): $SPEC_FILE"

# 1. RTL & SPEC PRE-FLIGHT
python3 serdes_architect/scripts/rtl_analyzer.py --config $SPEC_FILE

# 2. PHASE 1: PHYSICS FACTORY
# Training maps are drawn as a superset of what the search in Phase 3 explores
# and labelled by the reference solver's direct solve. The old data_gen.py drew
# discs and single cells -- a distribution the optimiser could not express a
# single design in -- and labelled by relaxation; see reports/surrogate_retraining.md.
echo "📂 [Phase 1] Training set + solver self-check..."
cd physics_accelerated/src
python3 dataset.py --distribution mixed --train ${SAMPLES:-3000} --val 400 --test 400 \
    --config ../../$SPEC_FILE
cd ../..
cd serdes_architect
python3 src/thermal/solver.py --verify --mode 3d_6neighbor 
cd ..

# 3. PHASE 2: SURROGATE TRAINING
echo "🧠 [Phase 2] PINO Surrogate Training..."
cd physics_accelerated
rm -rf data && ln -sf ../serdes_architect/data data
python3 src/train.py --epochs ${EPOCHS:-40} --lambda_physics 0.1 --seed ${SEED:-2} \
    --dataset ../serdes_architect/data/manifest_mixed.json --tag mixed \
    --config ../$SPEC_FILE
# Old vs new surrogate, held out. Only runs if a legacy model is still around.
if [ -f results/fno_model_lam0p1.pt ]; then
    python3 src/surrogate_benchmark.py --config ../$SPEC_FILE
fi
cd ..

# 4. PHASE 3: MULTI-OBJECTIVE SEARCH (NSGA-II, then re-solved)
# gepa.py -- 50 random placements ranked by peak temperature, no dominance test --
# is superseded by pareto_search.py, which ends by re-solving every front member
# on the reference solver through the trust guard.
echo "📈 [Phase 3] NSGA-II search + trust guard..."
cd physics_accelerated
python3 src/pareto_search.py --generations ${GENERATIONS:-80} --config ../$SPEC_FILE
python3 src/validate_surrogate.py
cd ..

# 5. PHASE 4: PHYSICAL & ELECTRICAL QUALIFICATION (Closed Loop)
echo "🏗️  [Phase 4] Execution of Layout & Extraction..."
cd serdes_architect
GOLDEN="../physics_accelerated/results/golden_config.json"

# A. Generate Initial Layout
python3 src/layout/gen_def.py --golden_config $GOLDEN

# B. Extract Parasitics (Crucial for SI/PI feedback)
python3 src/layout/rc_extractor.py --config $GOLDEN

# C. Feedback-Driven Qualification Gates
echo "📊 [Phase 4b] Data-Driven Verification Checklist..."
python3 src/si_analyzer_v3.py --config $GOLDEN
python3 scripts/avs_optimizer.py --config $GOLDEN
python3 src/thermal/ir_drop_solver.py --config $GOLDEN
python3 src/security_analyzer.py --config $GOLDEN
python3 src/thermal/transient_solver.py --config $GOLDEN --write_config

# Comprehensive Silicon & Package Architectural Verification Dossier
python3 scripts/generate_design_checklist.py --config $GOLDEN

# --- HYBRID AGENTIC GRAPH GATE (Milestone #15) ---
echo "🛡️  [Graph] Verifying Architectural Pass Gate..."
python3 ../agent/graph_orchestrator.py

echo "✅ v3.1 Architectural Pass Complete. Post-Layout parasitics integrated into status checklist."
cd ..

# 6. PHASE 5: EDA HANDOFF (vendor-neutral interchange)
echo "🔌 [Phase 5] Emitting vendor-neutral interchange artifacts..."
python3 -m integrations.cli emit --target neutral:all --golden "physics_accelerated/results/golden_config.json"
echo "   -> results/handoff/<run_id>/  (DEF/LEF, GDSII, SPEF, Liberty, Touchstone, IBIS, SPICE)"
echo "   Vendor decks:  python3 -m integrations.cli emit --target cadence:celsius"
echo "   Results back:  python3 -m integrations.cli correlate --thermal <celsius_export>.csv"
