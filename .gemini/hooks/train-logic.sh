#!/bin/bash
# Gemini CLI Hook: Autonomous Architect v2.5
# Orchestrates JEPA-12L and QLoRA 4B training with self-learning

set -e

# Detect Intent using Python (Cross-platform)
INTENT=$(python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('intent', ''))" <<< "$1")
GOLDEN="physics_accelerated/results/golden_config.json"

# 1. Self-Learning Trigger (RLPF)
# If the previous run failed, force a fine-tuning session to learn the mitigation
if [ -f "$GOLDEN" ]; then
    STATUS=$(python3 -c "import json; d=json.load(open('$GOLDEN')); print(d.get('si_analysis_v3', {}).get('status', 'PASS'))")
    if [[ "$STATUS" == *"FAIL"* ]]; then
        echo "⚠️  RLPF ALERT: Design Failure Detected ($STATUS). Initiating Learning Recovery..." >&2
        INTENT="Fine-tune Step 4" # Override intent to force learning
    fi
fi

if [[ "$INTENT" == *"Train"* || "$INTENT" == *"Fine-tune"* ]]; then
    echo "🧠 [AfterAgent] Starting Local Learning Session..." >&2
    
    if [[ "$INTENT" == *"Step 4"* ]]; then
        echo "🧠 [Local] Training JEPA Physics Head on current repository voxels..." >&2
        # Actual training call to the local model
        python3 serdes_architect/src/train.py --epochs 10 --weighted_loss true
        # Link the weights to the agent's brain
        cp physics_accelerated/results/fno_model.pt project_memory/adapters/physics_v1.bin
        echo "✅ Hybrid Model updated with local physical intuition." >&2
    fi
    
    echo '{"decision": "continue", "systemMessage": "Autonomous Architect has learned from physical failure. V2 Expert intuition updated."}'
else
    echo '{"decision": "continue"}'
fi