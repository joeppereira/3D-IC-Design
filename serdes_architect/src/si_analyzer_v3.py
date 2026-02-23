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
            "Flyover": {"loss_per_inch": 0.45},
            "Silicon": {"loss_per_inch": 1.2},
            "Glass": {"loss_per_inch": 0.8}
        }
        
        self.mod_specs = {"NRZ": {"snr_req": 14.0}, "PAM2": {"snr_req": 14.0}, "PAM4": {"snr_req": 24.0}}
        
        # Enterprise Interface Specs
        self.interface_specs = {
            "UCIe2.0_A": {"xtk_tax": 1.0, "vtf_baseline": 0.95},
            "UCIe2.0_S": {"xtk_tax": 4.0, "vtf_baseline": 0.85},
            "BoW":       {"xtk_tax": 5.5, "vtf_baseline": 0.80}
        }

    def measure_vtf(self, total_loss):
        return 10 ** (-total_loss / 20.0)

    def evaluate_link(self, distance_in, material_key, config):
        mod = config.get('constraints', {}).get('modulation', 'PAM4')
        clock_mode = config.get('constraints', {}).get('clock_mode', 'CDR')
        use_fec = config.get('constraints', {}).get('fec_preference', 'none') != 'none'
        proto = config.get('constraints', {}).get('protocol', '')
        
        # 1. Base Loss (RC Feedback Loop)
        rc = config.get('rc_extraction', {})
        if rc and "m7_signal_r_ohm" in rc:
            z_load = 100.0
            v_ratio = z_load / (z_load + rc['m7_signal_r_ohm'])
            total_loss = abs(20 * np.log10(v_ratio))
        else:
            if material_key not in self.materials: material_key = "Megtron7"
            ref_loss = self.materials[material_key]["loss_per_inch"]
            scaler = (self.nyquist / self.ref_freq) ** 0.7
            total_loss = distance_in * ref_loss * scaler
            
        total_loss += 6.0 # Package/Conn Tax
        
        # 2. Interface-Specific Noise (Enterprise EDA Mode)
        if "UCIe2.0" in proto:
            flavor = "UCIe2.0_A" if "Silicon" in material_key else "UCIe2.0_S"
            total_loss += self.interface_specs[flavor]["xtk_tax"]
        elif "BoW" in proto:
            total_loss += self.interface_specs["BoW"]["xtk_tax"]
            
        # 3. SNR Calculation
        tx_snr_base = 42.0 
        vddq = config.get('packaging', {}).get('vddq_v', 1.0)
        tx_snr = tx_snr_base + (15 * np.log10(vddq / 1.0))
        
        eff_snr = tx_snr - total_loss + (3.5 if use_fec else 0.0)
        eff_snr += (18.0 if self.nyquist >= 50.0 else 8.0) # DSP Gain
        
        if clock_mode == "Forwarded":
            eff_snr += (2.0 if distance_in < 2.0 else -(distance_in - 2.0) * 0.5)

        # 4. VTF & Eye Verification
        vtf = self.measure_vtf(total_loss)
        req_snr = self.mod_specs.get(mod, {"snr_req": 24.0})["snr_req"]
        net_margin_db = eff_snr - req_snr
        eye_width_ui = max(0.0, min(0.70, net_margin_db * 0.05))
        
        status = "✅ PASS" if net_margin_db > 2.0 and eye_width_ui > 0.20 else "❌ FAIL"
            
        return {
            "loss": total_loss, "vtf": round(vtf, 3), 
            "snr_margin_db": net_margin_db, "eye_width_ui": eye_width_ui, 
            "status": status
        }

def run_analysis(args):
    with open(args.config, 'r') as f: config = json.load(f)
    reach_mm = config.get('reach_mm', 50.0)
    material = config.get('packaging', {}).get('material_name', 'Megtron7')
    analyzer = AdvancedSIAnalyzer(target_bw_gbps=config.get('target_bandwidth_gbps', 224))
    result = analyzer.evaluate_link(reach_mm / 25.4, material, config)
    config['si_analysis_v3'] = result
    with open(args.config, 'w') as f: json.dump(config, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    run_analysis(args)