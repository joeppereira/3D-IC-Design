import json
import os

def ingest_failure_as_training_pair(config_path, output_path="project_memory/training_pairs.jsonl"):
    with open(config_path, 'r') as f:
        config = json.load(f)
        
    si = config.get('si_analysis_v3', {})
    ir = config.get('ir_drop_signoff', {})
    transient = config.get('transient_thermal_signoff', {})
    
    # Identify the primary physical failure
    failure_context = ""
    mitigation_hint = ""
    
    if ir.get('droop_percentage', 0) > 5.0:
        failure_context = f"IR-Drop Failure: {ir['droop_percentage']}% droop detected at {config['max_power_budget_w']}W."
        mitigation_hint = "The 3nm global PDN resistance is too high. Apply a Power Delivery Die (v4.0) to bypass the metal trunk."
        
    elif si.get('eye_width_ui', 1.0) < 0.20:
        failure_context = f"SI Failure: Eye Width {si['eye_width_ui']:.3f} UI at {config['reach_mm']}mm reach."
        mitigation_hint = "Insertion loss exceeds SNR budget. Switch from PCB routing to Flyover Twinax cables."

    if failure_context:
        # Create High-Fidelity Training Pair
        pair = {
            "instruction": f"Analyze this physical failure and propose a 3D-IC mitigation: {failure_context}",
            "response": f"Physical Analysis: The failure is driven by {failure_context.split(':')[0]}. Mitigation: {mitigation_hint}"
        }
        
        # Append to training set
        with open(output_path, 'a') as f:
            f.write(json.dumps(pair) + "\n")
            
        print(f"✅ RLPF: Ingested real simulation failure into {output_path}")
        return True
    return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    ingest_failure_as_training_pair(args.config)
