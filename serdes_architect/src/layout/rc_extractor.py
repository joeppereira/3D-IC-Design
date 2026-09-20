import json
import os
import sys
import math
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import materials as M

# Copper resistivity. On-die thin metal suffers surface/grain scattering at 3nm
# (~3.0e-8); off-die conductors are bulk copper (1.72e-8).
RHO_CU_ONDIE = 3.0e-8
RHO_CU_BULK = 1.72e-8
EPS0 = 8.854e-12
C0 = 299_792_458.0


class RCExtractor:
    """Two-scale parasitic extraction.

    The previous version applied on-die Metal-7 geometry (0.2um x 0.4um) over the
    full `reach_mm`, so a 300 mm host-to-XPU channel came out at 112.5 kOhm --
    47 Ohm/mm, where a controlled-impedance link is 0.1-1 Ohm/mm. Downstream,
    si_analyzer_v3 turned that number into a 61 dB "insertion loss" via a DC
    voltage divider and declared the link dead.

    These are two different conductors and they are now modelled separately:

      on-die escape : SerDes macro -> bump, on thick top metal, ~1 mm
      off-die channel: bump -> connector -> far end, `reach_mm` of `material`
    """

    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        # On-die escape route (top thick metal, not M7 signal pitch).
        self.escape_width_um = 4.0
        self.escape_thickness_um = 1.0
        self.escape_pitch_um = 8.0

        # PDN trunk (Metal 10 mesh).
        self.m10_width = 2.0
        self.m10_thickness = 1.0
        self.m10_pitch_um = 50.0

        self.eps_rel = 3.9          # SiO2 inter-metal dielectric

    # -- geometry helpers ----------------------------------------------------
    def _escape_length_um(self):
        """Macro-to-bump distance implied by the floorplan.

        gen_def.py places the SerDes macros 1500 um inside the die edge, so that
        is the escape length unless the config overrides it.
        """
        return float(self.config.get('on_die_escape_um', 1500.0))

    def _die_width_um(self):
        die0 = self.config.get('die_hierarchy', {}).get('die_0', {})
        size = die0.get('size_mm', [18, 18])
        return float(size[0]) * 1000.0

    # -- extraction ----------------------------------------------------------
    def calculate_parasitics(self):
        print("🔌 Starting Post-Layout RC Extraction (3nm Node)...")

        reach_mm = float(self.config.get('reach_mm', 300.0))
        raw_material = self.config.get('packaging', {}).get('material_name')
        material, resolved = M.resolve_or_default(raw_material)
        if not resolved:
            print(f"  ⚠️  unknown channel material {raw_material!r}; "
                  f"falling back to {material}")
        props = M.MATERIALS[material]
        z0_diff = 100.0             # differential characteristic impedance

        # 1. On-die escape: macro -> bump, per leg of the differential pair.
        esc_len_m = self._escape_length_um() * 1e-6
        esc_area = (self.escape_width_um * 1e-6) * (self.escape_thickness_um * 1e-6)
        r_escape_leg = RHO_CU_ONDIE * esc_len_m / esc_area
        r_escape_diff = 2.0 * r_escape_leg          # both legs in the loop

        dist_m = self.escape_pitch_um * 1e-6
        c_escape = (self.eps_rel * EPS0 *
                    (self.escape_thickness_um * 1e-6) * esc_len_m / dist_m) * 2.0

        print(f"  - On-die escape ({self._escape_length_um():.0f}um): "
              f"R={r_escape_diff:.2f} Ohm diff, C={c_escape * 1e12:.3f} pF")

        # 2. Off-die channel over `reach_mm` of the named material.
        chan_len_m = reach_mm / 1000.0
        r_channel = 2.0 * RHO_CU_BULK * chan_len_m / props["conductor_area_m2"]
        velocity = C0 / math.sqrt(props["dk"])
        c_channel = chan_len_m / (z0_diff * velocity) * 1e12      # pF
        ohm_per_mm = r_channel / reach_mm if reach_mm else 0.0

        print(f"  - Channel ({reach_mm:.0f}mm {material}): "
              f"R={r_channel:.3f} Ohm ({ohm_per_mm:.3f} Ohm/mm), C={c_channel:.2f} pF")

        # 3. PDN trunk: a mesh, not a single wire. Stripes run the die width on
        #    a fixed pitch, so they carry current in parallel.
        die_w_m = self._die_width_um() * 1e-6
        area_m10 = (self.m10_width * 1e-6) * (self.m10_thickness * 1e-6)
        r_stripe = RHO_CU_ONDIE * die_w_m / area_m10
        n_parallel = max(1.0, self._die_width_um() / self.m10_pitch_um)
        r_pdn = r_stripe / n_parallel

        print(f"  - PDN (M10 mesh, {n_parallel:.0f} stripes): R={r_pdn:.4f} Ohm")

        extraction = {
            "model": "two-scale: on-die thick-metal escape + off-die channel",
            "material": material,
            "material_input": raw_material,
            "on_die_escape_um": self._escape_length_um(),
            "escape_r_ohm_diff": round(r_escape_diff, 4),
            "escape_c_pf": round(c_escape * 1e12, 4),
            "channel_length_mm": reach_mm,
            "channel_r_ohm": round(r_channel, 4),
            "channel_c_pf": round(c_channel, 4),
            "channel_ohm_per_mm": round(ohm_per_mm, 5),
            "m10_pdn_r_ohm": round(r_pdn, 4),
            "pdn_stripes_parallel": int(n_parallel),
            # Backwards-compatible keys: these now mean the *escape*, which is
            # what an on-die signal parasitic actually is.
            "m7_signal_r_ohm": round(r_escape_diff, 4),
            "m7_signal_c_pf": round(c_escape * 1e12, 4),
        }
        extraction["plausibility"] = self._plausibility(extraction)
        extraction["extraction_status"] = (
            "✅ VERIFIED" if extraction["plausibility"]["ok"] else "❌ IMPLAUSIBLE")

        for warn in extraction["plausibility"]["warnings"]:
            print(f"  ⚠️  {warn}")

        self.config['rc_extraction'] = extraction
        with open(self.config_path_current, 'w') as f:
            json.dump(self.config, f, indent=2)

        return extraction

    @staticmethod
    def _plausibility(ex):
        """Guard against the class of error this rewrite fixes."""
        warnings = []
        opm = ex["channel_ohm_per_mm"]
        if ex["channel_length_mm"] > 0 and not (0.001 <= opm <= 2.0):
            warnings.append(
                f"channel is {opm:.3f} Ohm/mm; a controlled-impedance link is "
                "0.001-2 Ohm/mm. Check that on-die geometry is not being applied "
                "to an off-die reach.")
        if ex["escape_r_ohm_diff"] > 200.0:
            warnings.append(
                f"on-die escape is {ex['escape_r_ohm_diff']:.1f} Ohm differential; "
                "above ~200 Ohm the escape dominates the link budget.")
        if ex["m10_pdn_r_ohm"] > 10.0:
            warnings.append(
                f"PDN trunk is {ex['m10_pdn_r_ohm']:.2f} Ohm; a die-wide mesh "
                "should be well under 10 Ohm.")
        return {"ok": not warnings, "warnings": warnings}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()

    extractor = RCExtractor(args.config)
    extractor.config_path_current = args.config
    extractor.calculate_parasitics()
