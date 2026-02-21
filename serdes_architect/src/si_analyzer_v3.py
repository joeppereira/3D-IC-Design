import argparse
import json
import numpy as np
import os
import sys

class AdvancedSIAnalyzer:
    def __init__(self, target_bw_gbps=224):
        self.nyquist = target_bw_gbps * 0.5 
        self.ref_freq = 112.0
        
        # Loss per inch at 112GHz
        self.materials = {
            "FR4": {"loss_per_inch": 10.0}, 
            "Megtron7": {"loss_per_inch": 2.5},
            "Megtron_7": {"loss_per_inch": 2.5},
            "Flyover": {"loss_per_inch": 0.45},
            "Twinax": {"loss_per_inch": 0.45}
        }
        
        # Modulation Physics (Required SNR)
        self.mod_specs = {
            "NRZ":  {"snr_req": 14.0, "ui_penalty_factor": 1.0},
            "PAM2": {"snr_req": 14.0, "ui_penalty_factor": 1.0},
            "PAM4": {"snr_req": 24.0, "ui_penalty_factor": 3.0} 
        }

    def evaluate_link(self, distance_in, material_key, config):
        # 1. Config Extraction
        mod = config.get('constraints', {}).get('modulation', 'PAM4')
        clock_mode = config.get('constraints', {}).get('clock_mode', 'CDR')
        use_fec = config.get('constraints', {}).get('fec_preference', 'none') != 'none'
        
        print(f"  🔍 SI Analysis: {mod} | {clock_mode} | {distance_in:.2f}\" on {material_key}")

        # 2. Calculate Physical Loss (Nyquist Scaled)
        mat_key = "Megtron7"
        if material_key:
            if "Flyover" in material_key or "Twinax" in material_key: mat_key = "Flyover"
            elif "FR4" in material_key: mat_key = "FR4"
            elif "Megtron" in material_key: mat_key = "Megtron7"

        ref_loss = self.materials[mat_key]["loss_per_inch"]
        scaler = np.sqrt(self.nyquist / self.ref_freq)
        loss_per_inch = ref_loss * scaler
        
        il_loss = distance_in * loss_per_inch
        fixed_loss = 6.0 
        total_loss = il_loss + fixed_loss

        # 2a. Crosstalk Physics (SE vs Diff)
        sig_type = "SE" if "PAM2" in mod else "Diff"
        xtk_db = 6.0 if sig_type == "SE" else 1.0
        print(f"    - Signaling:     {sig_type} (XTK: {xtk_db}dB)")
        total_loss += xtk_db 
        
        # 3. Calculate SNR Margin
        # Calibrated baseline for 2026-era high-speed SerDes
        # 40dB is high-end, required for 224G stability at 35dB IL
        tx_snr = 40.0 
        eff_snr = tx_snr - total_loss
        
        # FEC Gain
        coding_gain = 3.5 if use_fec else 0.0
        eff_snr += coding_gain
        
        # EQ/DSP Gain (Enhanced for 224G reliability)
        eq_gain = 0.0
        if self.nyquist >= 50.0: # 112G+ Nyquist
             eq_gain = 18.0 # Advanced ADC-DSP
             print(f"    - DSP Gain:      +{eq_gain:.2f} dB (224G Ultra-DSP)")
        elif total_loss > 15.0:
            eq_gain = 10.0 # FFE/DFE
        elif total_loss > 5.0:
            eq_gain = 4.0 # CTLE
        eff_snr += eq_gain
        
        # 4. Clocking Physics (Jitter/Skew)
        clock_impact_db = 0.0
        if clock_mode == "Forwarded":
            if distance_in < 2.0:
                clock_impact_db = 2.0 # Correlated Gain
                print(f"    - Fwd Clock Gain: +{clock_impact_db:.2f} dB")
            else:
                clock_impact_db = -(distance_in - 2.0) * 0.5 # Skew Tax
                print(f"    - Fwd Clock Tax:  {clock_impact_db:.2f} dB")
        eff_snr += clock_impact_db

        # 5. Evaluate
        req_snr = self.mod_specs.get(mod, self.mod_specs["PAM4"])["snr_req"]
        net_margin_db = eff_snr - req_snr
        
        # Eye Width UI conversion
        # Calibrated: 10dB margin ~ 0.5 UI.
        eye_width_ui = max(0.0, min(1.0, net_margin_db * 0.05))
        
        status = "✅ PASS" if net_margin_db > 2.0 and eye_width_ui > 0.15 else "❌ FAIL"
            
        return {
            "loss": total_loss, "snr_margin_db": net_margin_db,
            "eye_width_ui": eye_width_ui, "status": status, "mod": mod
        }

def run_analysis(args):
    with open(args.config, 'r') as f:
        config = json.load(f)
        
    reach_mm = config.get('reach_mm', 50.0)
    distance_in = reach_mm / 25.4
    material = config.get('packaging', {}).get('material_name', 'Megtron7')
    bw = config.get('target_bandwidth_gbps', 224)
    
    print(f"  [DEBUG] SI Analyzer V3: BW={bw} Gbps, Material Config={material}")
    
    analyzer = AdvancedSIAnalyzer(target_bw_gbps=bw)
    result = analyzer.evaluate_link(distance_in, material, config)
    
    print(f"\n📢 Verdict: {result['status']} | Loss: {result['loss']:.1f}dB | Eye: {result['eye_width_ui']:.3f} UI")
    
    config['si_analysis_v3'] = result
    with open(args.config, 'w') as f:
        json.dump(config, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True, help='Path to golden config')
    args = parser.parse_args()
    
    run_analysis(args)
