#!/bin/bash
# Pareto Matrix Batch Runner
set -e

# Source venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Generate Matrix
python3 serdes_architect/scripts/generate_pareto_matrix.py

CONFIGS=($(ls configs/pareto_matrix/*.json | xargs -n 1 basename))
TOTAL=${#CONFIGS[@]}
COUNT=1

RESULTS_DIR="reports/pareto_matrix"
mkdir -p $RESULTS_DIR

echo "🚀 Starting 20-Point Pareto Simulation..."
echo "---------------------------------------------------------------"

# Faster run settings for the matrix
export SAMPLES=10
export EPOCHS=1

for conf in "${CONFIGS[@]}"; do
    echo "[Progress $COUNT/$TOTAL] Simulating: $conf"
    
    # Run Pipeline using the full path
    ./run_full_cycle.sh "configs/pareto_matrix/$conf" > "$RESULTS_DIR/${conf%.json}.log" 2>&1
    
    if [ $? -ne 0 ]; then
        echo "❌ FAILED: $conf"
    else
        cp physics_accelerated/results/golden_config.json "$RESULTS_DIR/${conf%.json}_result.json"
        echo "✅ COMPLETED: $conf"
    fi
    
    COUNT=$((COUNT + 1))
done

echo "---------------------------------------------------------------"
echo "🏁 Pareto Matrix Complete. Results in $RESULTS_DIR"
