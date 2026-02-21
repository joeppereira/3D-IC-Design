#!/bin/bash
# Batch Analysis Runner v2
set -e

# Source venv if exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Default to robust training if not set
export SAMPLES=${SAMPLES:-50}
export EPOCHS=${EPOCHS:-5}

# Ensure all scenarios are generated
python3 serdes_architect/scripts/generate_scenarios.py > /dev/null

CONFIGS=($(ls configs/*.json | xargs -n 1 basename))
TOTAL=${#CONFIGS[@]}
COUNT=1

RESULTS_DIR="reports/batch_analysis"
mkdir -p $RESULTS_DIR

echo "🚀 Starting Comprehensive Batch Analysis across $TOTAL Scenarios..."
echo "---------------------------------------------------------------"

for conf in "${CONFIGS[@]}"; do
    echo "[Progress $COUNT/$TOTAL] Processing: $conf"
    
    # Run Pipeline (redirect full output to log, show errors on stderr if any)
    ./run_full_cycle.sh "configs/$conf" > "$RESULTS_DIR/${conf%.json}.log" 2>&1
    
    # Check for failure
    if [ $? -ne 0 ]; then
        echo "❌ FAILED: $conf. Check log: $RESULTS_DIR/${conf%.json}.log"
    else
        # Capture the Golden Config Result
        cp physics_accelerated/results/golden_config.json "$RESULTS_DIR/${conf%.json}_result.json"
        echo "✅ COMPLETED: $conf"
    fi
    
    COUNT=$((COUNT + 1))
done

echo "---------------------------------------------------------------"
echo "🏁 Batch Analysis Complete. Results in $RESULTS_DIR"