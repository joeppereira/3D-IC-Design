# Real placement + real per-instance power from a placed ORFS database.
#
# Notes earned the hard way on this machine:
#   * sta::instance_power segfaults under amd64 emulation; the documented
#     report_power -instances works, so the power comes from its text table.
#   * CTS (TritonCTS) dies with "illegal instruction" under Rosetta, so the
#     flow is stopped at 3_place. Placement is what sets the spatial power
#     distribution, so that is sufficient for a power map.
proc mark {m} { puts "MARK:$m"; flush stdout }
set P /OpenROAD-flow-scripts/flow/platforms/$::env(PLAT)
set R /orfs/results/$::env(PLAT)/$::env(DES)/base
set out /output/$::env(DES)

foreach f [glob -nocomplain $P/lib/NLDM/*_RVT_*_nldm_*.lib*] { read_liberty $f }
read_db $R/3_place.odb
read_sdc $R/3_place.sdc
source $P/setRC.tcl
set_power_activity -input -activity $::env(ACTIVITY)
estimate_parasitics -placement
mark loaded

report_power -instances [get_cells *] -digits 9 > ${out}_inst_power.txt
report_power -digits 9 > ${out}_power_summary.txt
mark power

set blk [ord::get_db_block]
set dbu [$blk getDefUnits]
set fp [open ${out}_placement.csv w]
puts $fp "instance,master,x_um,y_um,w_um,h_um"
foreach inst [$blk getInsts] {
    set b [$inst getBBox]
    puts $fp "[$inst getName],[[$inst getMaster] getName],[expr {[$b xMin]*1.0/$dbu}],[expr {[$b yMin]*1.0/$dbu}],[expr {([$b xMax]-[$b xMin])*1.0/$dbu}],[expr {([$b yMax]-[$b yMin])*1.0/$dbu}]"
}
close $fp
set d [$blk getDieArea]
set fp2 [open ${out}_die.json w]
puts $fp2 "{\"design\":\"$::env(DES)\",\"platform\":\"$::env(PLAT)\",\"stage\":\"3_place\",\"activity\":$::env(ACTIVITY),\"n_instances\":[llength [$blk getInsts]],\"die_um\":\[[expr {[$d xMin]*1.0/$dbu}],[expr {[$d yMin]*1.0/$dbu}],[expr {[$d xMax]*1.0/$dbu}],[expr {[$d yMax]*1.0/$dbu}]\]}"
close $fp2
write_def ${out}_placed.def
mark done
