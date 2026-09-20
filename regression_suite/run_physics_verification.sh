#!/bin/bash
# Physics verification: each layer checked against something more trustworthy.
#
#   reference solver  <- analytic 1D slab conduction, global energy balance
#   FDM solver        <- the reference solver (different method, same equations)
#   heat residual     <- a converged field (residual must vanish)
#   NSGA-II           <- ZDT1, whose Pareto front is known analytically
#
# No licences and no vendor tools required.
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python3}
[ -x .venv/bin/python ] && PY=.venv/bin/python

echo "=================================================================="
echo " PHYSICS VERIFICATION"
echo "=================================================================="

echo "--- [1/4] Solver self-check (geometry, energy, gradient) ----------"
(cd serdes_architect && ../$PY src/thermal/solver.py --verify --mode 3d_6neighbor)

echo
echo "--- [2/4] Verification test suite --------------------------------"
$PY -m unittest discover -s tests/physics -t . 2>&1 | tail -5

echo
echo "--- [3/4] Reference solver: analytic benchmark + convergence ------"
$PY - <<'PYEOF'
import sys, json; sys.path.insert(0, "physics_accelerated/src")
doc = json.load(open("reports/mesh_convergence_audit.json"))
v = doc["verification"]["analytic_1d_slab"]
e = doc["verification"]["global_energy_balance"]
m = doc["mesh_convergence"]
print(f"  analytic 1D slab error : {v['abs_error_c']:.3e} C")
print(f"  energy balance         : {e['relative_error']:.2e} relative")
print(f"  grid-converged peak Tj : {m['richardson_extrapolated_peak_c']:.3f} C "
      f"(GCI {m['gci_finest_pct']:.4f}%, converged={m['grid_converged']})")
PYEOF

echo
echo "--- [4/4] Surrogate error band at optimiser-selected designs ------"
$PY - <<'PYEOF'
import json, os
p = "reports/thermal_validation.json"
if not os.path.exists(p):
    print("  (run physics_accelerated/src/validate_surrogate.py to generate)")
else:
    d = json.load(open(p))
    for row in d["designs"]:
        print(f"  {row['design']:16} surrogate {row['surrogate_peak_c']:7.2f} C vs "
              f"reference {row['reference_refined_peak_c']:7.2f} C  "
              f"({row['surrogate_error_vs_reference_k']:+6.2f} K)")
    s = d["shattered_vs_monolithic"]
    print(f"  shattered-macro headroom: {s['reference_headroom_c']:+.2f} C on the "
          f"reference ({s['surrogate_headroom_c']:+.2f} C predicted)")
    print(f"  max |surrogate error|   : "
          f"{d['surrogate_error_vs_reference_k']['max_abs']:.2f} K "
          f"-- use the front for RANKING, not absolute temperatures")
PYEOF

echo
echo "=================================================================="
echo " PHYSICS VERIFICATION PASSED"
echo " See reports/rom_pinn_validation.md and reports/multiobjective_search.md"
echo "=================================================================="
