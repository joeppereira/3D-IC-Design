import argparse
import json
import numpy as np
import os
import sys

class AdvancedSIAnalyzer:
    def __init__(self, target_bw_gbps=224):
        self.nyquist = target_bw_gbps * 0.5 
        self.ref_freq = 112.0
        
        self.materials = {
            "FR4": {"loss_per_inch": 10.0}, 
            "Megtron7": {"loss_per_inch": 2.5},
            "Megtron_7": {"loss_per_inch": 2.5},
            "Flyover": {"loss_per_inch": 0.45},
            "Twinax": {"loss_per_inch": 0.45},
            "Silicon": {"loss_per_inch": 1.2} # Interposer
        }
        
        self.mod_specs = {
            "NRZ":    {"snr_req": 14.0},
            "PAM2":   {"snr_req": 14.0},
            "PAM4":   {"snr_req": 24.0}
        }

    def evaluate_link(self, distance_in, material_key, config):
        mod = config.get('constraints', {}).get('modulation', 'PAM4')
        clock_mode = config.get('constraints', {}).get('clock_mode', 'CDR')
        use_fec = config.get('constraints', {}).get('fec_preference', 'none') != 'none'
        
        # 2. Calculate Physical Loss
        if material_key not in self.materials: material_key = "Megtron7"
        ref_loss = self.materials[material_key]["loss_per_inch"]
        
        # Frequency Scaling (f^0.7 for dielectric+skin effect)
        scaler = (self.nyquist / self.ref_freq) ** 0.7
        loss_per_inch = ref_loss * scaler
        il_loss = distance_in * loss_per_inch
        
        fixed_loss = 6.0 
        total_loss = il_loss + fixed_loss

        # 2a. Crosstalk Tax (SE vs Diff)
        sig_type = config.get('constraints', {}).get('signaling', 'Diff')
        xtk_db = 7.0 if sig_type == "SE" else 1.5
        total_loss += xtk_db 
        
        # 3. Calculate SNR Margin
        tx_snr_base = 42.0 # Standard 2026 Tx Quality
        vddq = config.get('packaging', {}).get('vddq_v', 1.0)
        # Recalibrated Voltage Scaling (15*log10 heuristic for low-V noise floor)
        voltage_penalty = 15 * np.log10(vddq / 1.0) 
        tx_snr = tx_snr_base + voltage_penalty
        
        eff_snr = tx_snr - total_loss
        coding_gain = 3.5 if use_fec else 0.0
        eff_snr += coding_gain
        
        # EQ/DSP Gain
        eq_gain = 0.0
        if self.nyquist >= 50.0: eq_gain = 18.0 # ADC-DSP
        elif total_loss > 15.0:  eq_gain = 10.0 # FFE/DFE
        elif total_loss > 5.0:   eq_gain = 4.0  # CTLE
        eff_snr += eq_gain
        
        # 4. Clocking Impact
        clock_impact_db = 0.0
        if clock_mode == "Forwarded":
            if distance_in < 2.0: clock_impact_db = 2.0
            else: clock_impact_db = -(distance_in - 2.0) * 0.5
        eff_snr += clock_impact_db

        # 5. Evaluate
        req_snr = self.mod_specs.get(mod, {"snr_req": 24.0})["snr_req"]
        net_margin_db = eff_snr - req_snr
        
        # Physical Realism: Even with infinite SNR, jitter caps the eye
        # Residual Jitter Floor: 0.15 UI
        max_theoretical_eye = 0.75
        eye_width_ui = max(0.0, min(max_theoretical_eye, net_margin_db * 0.05))
        
        # Deduct residual thermal jitter
        eye_width_ui = max(0.0, eye_width_ui - 0.05) 
        
        status = "✅ PASS" if net_margin_db > 2.0 and eye_width_ui > 0.20 else "❌ FAIL"
            
        return {"loss": total_loss, "snr_margin_db": net_margin_db, "eye_width_ui": eye_width_ui, "status": status}

def run_analysis(args):
    with open(args.config, 'r') as f: config = json.load(f)
    reach_mm = config.get('reach_mm', 50.0)
    distance_in = reach_mm / 25.4
    material = config.get('packaging', {}).get('material_name', 'Megtron7')
    bw = config.get('target_bandwidth_gbps', 224)
    analyzer = AdvancedSIAnalyzer(target_bw_gbps=bw)
    result = analyzer.evaluate_link(distance_in, material, config)
    config['si_analysis_v3'] = result
    with open(args.config, 'w') as f: json.dump(config, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    run_analysis(args)