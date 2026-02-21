# OpenROAD PI/SI-Aware Floorplan for CXL_Switch_SoP_Mitigated
# Calibrated for 200W SoP with BSPDN support

initialize_floorplan -die_area "0 0 15000.0 15000.0" -core_area "100 100 14900.0 14900.0" -site unithd

# PDN Mesh: M4/M5 for local distribution, M10/M11 for global trunk
pdngen -report_only 0
add_pdn_stripe -grid stdgrid -layer Metal4 -width 0.5 -pitch 10.0 -offset 2.0
add_pdn_stripe -grid stdgrid -layer Metal10 -width 2.0 -pitch 50.0 -offset 5.0

place_cell -inst_name SERDES_N_0 -origin "1000.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_0 -origin "1000.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_1 -origin "2800.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_1 -origin "2800.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_2 -origin "4600.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_2 -origin "4600.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_3 -origin "6400.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_3 -origin "6400.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_4 -origin "8200.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_4 -origin "8200.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_5 -origin "10000.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_5 -origin "10000.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_6 -origin "11800.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_6 -origin "11800.0 500.0" -orient N -status FIRM
place_cell -inst_name SERDES_N_7 -origin "13600.0 13500.0" -orient N -status FIRM
place_cell -inst_name SERDES_S_7 -origin "13600.0 500.0" -orient N -status FIRM
place_cell -inst_name UCIE_W_0 -origin "500.0 1000.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_0 -origin "13500.0 1000.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_1 -origin "500.0 2800.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_1 -origin "13500.0 2800.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_2 -origin "500.0 4600.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_2 -origin "13500.0 4600.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_3 -origin "500.0 6400.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_3 -origin "13500.0 6400.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_4 -origin "500.0 8200.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_4 -origin "13500.0 8200.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_5 -origin "500.0 10000.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_5 -origin "13500.0 10000.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_6 -origin "500.0 11800.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_6 -origin "13500.0 11800.0" -orient W -status FIRM
place_cell -inst_name UCIE_W_7 -origin "500.0 13600.0" -orient E -status FIRM
place_cell -inst_name UCIE_E_7 -origin "13500.0 13600.0" -orient W -status FIRM

# Caliptra RoT Security Keep-out (250um EM Shielding)
place_cell -inst_name Caliptra_RoT -origin "7500.0 2000.0" -orient N -status FIRM
add_keepout_margin -inst_name Caliptra_RoT -margin 250

# Signal Integrity: G-S-G Routing Tracks for 224G lanes
make_tracks Metal7 -x_offset 0.2 -x_pitch 0.4 -y_offset 0.2 -y_pitch 0.4
