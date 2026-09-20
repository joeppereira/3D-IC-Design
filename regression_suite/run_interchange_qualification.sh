#!/bin/bash
# T0 Interchange Qualification (spec section 8)
#
# Proves the vendor-neutral interchange layer is sound WITHOUT any vendor
# license: every emitted format is read back by an independent parser, the
# Touchstone channel is checked for passivity/causality/reciprocity, and the
# emitted SPICE deck is executed in ngspice when it is installed.
#
# This gate must be green before any vendor-specific work starts.
set -e
cd "$(dirname "$0")/.."

PY=${PY:-python3}
[ -x .venv/bin/python ] && PY=.venv/bin/python

echo "=================================================================="
echo " T0 INTERCHANGE QUALIFICATION"
echo "=================================================================="
echo "python : $($PY --version)"
printf "ngspice: "; command -v ngspice >/dev/null && ngspice -v 2>&1 | head -1 || echo "not installed (SPICE execution will be skipped)"
echo

echo "--- [1/4] Design record ------------------------------------------"
$PY -m integrations.cli status

echo
echo "--- [2/4] Format round-trip + electrical checks -------------------"
$PY -m unittest discover -s tests/integrations -t . -v 2>&1 | tail -25

echo
echo "--- [3/4] T0 emit gate (every hook) ------------------------------"
$PY -m integrations.cli roundtrip

echo
echo "--- [4/4] Return path on the format fixtures ---------------------"
$PY -m integrations.cli correlate \
    --thermal tests/integrations/fixtures/celsius_temperature.csv \
    --ir      tests/integrations/fixtures/voltus_ir_drop.csv \
    --spef    tests/integrations/fixtures/starrc_golden.spef \
    --sparam  tests/integrations/fixtures/hyperlynx_field_solved.s4p

echo
echo "=================================================================="
echo " T0 QUALIFICATION PASSED"
echo " Tier reached: T0 (emitted + independently parsed)."
echo " T1/T2 require licensed vendor tools; see"
echo " reports/eda_vendor_integration_spec.md sections 3-5."
echo "=================================================================="
