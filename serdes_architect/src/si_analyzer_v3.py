import argparse
import json
import numpy as np
import os
import sys

class AdvancedSIAnalyzer:
    def __init__(self, target_bw_gbps=224):
        self.nyquist = target_bw_gbps * 0.5 
        self.ref_freq = 112.0
        self.mod_specs = {"NRZ": {"snr_req": 14.0}, "PAM2": {"snr_req": 14.0}, "PAM4": {"snr_req": 24.0}}

    def evaluate_link(self, distance_in, material_key, config):
        mod = config.get('constraints', {}).get('modulation', 'PAM4')
        clock_mode = config.get('constraints', {}).get('clock_mode', 'CDR')
        use_fec = config.get('constraints', {}).get('fec_preference', 'none') != 'none'
        
        # --- PARASITIC FEEDBACK LOOP ---
        # If RC Extraction exists, use it for Ground Truth Loss
        rc = config.get('rc_extraction', {})
        if rc and "m7_signal_r_ohm" in rc:
            print(f"  [Bring-up] Using Post-Layout Parasitics: R={rc['m7_signal_r_ohm']} Ohms")
            # Calculate Voltage Loss from R
            # IL_db = 20 * log10(V_rx / V_tx). V_rx = V_tx * (Z_load / (Z_load + R_line))
            z_load = 100.0 # Standard Termination
            v_ratio = z_load / (z_load + rc['m7_signal_r_ohm'])
            total_loss = abs(20 * np.log10(v_ratio))
            print(f"    - Layout-Driven IL: {total_loss:.2f} dB")
        else:
            # Fallback to material-based scaling
            total_loss = distance_in * 2.5 # Heuristic
            
        total_loss += 6.0 # Package/Conn Tax
        
        # 3. Calculate SNR
        tx_snr_base = 42.0 
        vddq = config.get('packaging', {}).get('vddq_v', 1.0)
        voltage_penalty = 15 * np.log10(vddq / 1.0) 
        tx_snr = tx_snr_base + voltage_penalty
        
        eff_snr = tx_snr - total_loss
        eff_snr += (3.5 if use_fec else 0.0)
        
        # EQ/DSP Gain
        eq_gain = 18.0 if self.nyquist >= 50.0 else 8.0
        eff_snr += eq_gain
        
        # 4. Clocking
        if clock_mode == "Forwarded":
            eff_snr += (2.0 if distance_in < 2.0 else -(distance_in - 2.0) * 0.5)

        # 5. Result
        req_snr = self.mod_specs.get(mod, {"snr_req": 24.0})["snr_req"]
        net_margin_db = eff_snr - req_snr
        
        # Enforcement of 0.70 UI Ceiling
        eye_width_ui = max(0.0, min(0.70, net_margin_db * 0.05))
        status = "✅ PASS" if net_margin_db > 2.0 and eye_width_ui > 0.20 else "❌ FAIL"
            
        return {"loss": total_loss, "snr_margin_db": net_margin_db, "eye_width_ui": eye_width_ui, "status": status}

def run_analysis(args):
    with open(args.config, 'r') as f: config = json.load(f)
    reach_mm = config.get('reach_mm', 50.0)
    distance_in = reach_mm / 25.4
    material = config.get('packaging', {}).get('material_name', 'Megtron7')
    analyzer = AdvancedSIAnalyzer(target_bw_gbps=config.get('target_bandwidth_gbps', 224))
    result = analyzer.evaluate_link(distance_in, material, config)
    config['si_analysis_v3'] = result
    with open(args.config, 'w') as f: json.dump(config, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    run_analysis(args)
