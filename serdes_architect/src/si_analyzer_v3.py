import argparse
import json
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import materials as M

class AdvancedSIAnalyzer:
    # Loss tables in materials.py are anchored at the Nyquist of a 224G PAM4
    # link (112 GBd -> 56 GHz).
    ANCHOR_NYQUIST_GHZ = 56.0
    BITS_PER_SYMBOL = {"PAM4": 2.0, "PAM2": 1.0, "NRZ": 1.0}

    def __init__(self, target_bw_gbps=224, modulation="PAM4"):
        # Nyquist is half the *symbol* rate, not half the bit rate: 224 Gbps
        # PAM4 is 112 GBd -> 56 GHz, not 112 GHz.
        bits = self.BITS_PER_SYMBOL.get(str(modulation).upper(), 2.0)
        self.baud_gbd = target_bw_gbps / bits
        self.nyquist = self.baud_gbd * 0.5
        self.ref_freq = self.ANCHOR_NYQUIST_GHZ
        
        # Single source of truth, shared with si_analyzer.py and the
        # integrations layer (serdes_architect/src/materials.py).
        self.materials = M.MATERIALS
        
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
        # Keep the analyser's Nyquist in step with the modulation in the config.
        bits = self.BITS_PER_SYMBOL.get(str(mod).upper(), 2.0)
        self.baud_gbd = self.baud_gbd if bits == 0 else (self.baud_gbd)
        
        clock_mode = config.get('constraints', {}).get('clock_mode', 'CDR')
        use_fec = config.get('constraints', {}).get('fec_preference', 'none') != 'none'
        proto = config.get('constraints', {}).get('protocol', '')
        
        # 1. Channel loss at Nyquist.
        #
        # This used to be a DC voltage divider on the extracted on-die
        # resistance: 20*log10(100/(100+112500)) = 61 dB, which is not an
        # insertion loss at all -- it was the on-die escape geometry applied to
        # a 300 mm channel. Insertion loss now comes from the channel material,
        # and the escape contributes as the series resistance it actually is.
        material_key, resolved = M.resolve_or_default(material_key)
        if not resolved:
            print(f"  ⚠️  unknown material {material_key!r}; using {M.DEFAULT}")
        ref_loss = self.materials[material_key]["loss_per_inch"]
        scaler = (self.nyquist / self.ref_freq) ** 0.7
        channel_loss = distance_in * ref_loss * scaler

        # 2. On-die escape: series R into the differential load.
        rc = config.get('rc_extraction', {})
        z_diff = 100.0
        r_escape = float(rc.get('escape_r_ohm_diff', rc.get('m7_signal_r_ohm', 0.0)))
        escape_loss = abs(20 * np.log10(z_diff / (z_diff + r_escape))) if r_escape else 0.0

        total_loss = channel_loss + escape_loss
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
            "status": status,
            "loss_breakdown_db": {
                "channel": round(float(channel_loss), 3),
                "on_die_escape": round(float(escape_loss), 3),
                "package_connector": 6.0,
                "interface_xtk": round(float(total_loss - channel_loss
                                             - escape_loss - 6.0), 3),
            },
            "material": material_key,
            "baud_gbd": self.baud_gbd,
            "nyquist_ghz": self.nyquist,
        }

def run_analysis(args):
    with open(args.config, 'r') as f: config = json.load(f)
    reach_mm = config.get('reach_mm', 50.0)
    material = config.get('packaging', {}).get('material_name', M.DEFAULT)
    analyzer = AdvancedSIAnalyzer(
        target_bw_gbps=config.get('target_bandwidth_gbps', 224),
        modulation=config.get('constraints', {}).get('modulation', 'PAM4'))
    result = analyzer.evaluate_link(reach_mm / 25.4, material, config)
    config['si_analysis_v3'] = result
    with open(args.config, 'w') as f: json.dump(config, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    run_analysis(args)