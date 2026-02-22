// 🚀 Search King Top Testbench
// Function: Verifies the "Request-to-Return" logic cycle.

module tb_top;
    logic clk;
    logic rst_n;
    
    // PBR IO
    logic [511:0] host_rx_flit;
    logic         host_rx_valid;
    logic [31:0]  sram_pointer_out;
    logic         sram_resp_valid;
    logic         dram_tx_valid;
    
    // Instantiate DUT
    cxl_pbr_manager dut (
        .clk(clk), .rst_n(rst_n),
        .host_rx_flit(host_rx_flit), .host_rx_valid(host_rx_valid),
        .sram_pointer_out(sram_pointer_out), .sram_resp_valid(sram_resp_valid),
        .dram_tx_valid(dram_tx_valid)
    );

    // Clock Gen
    always #2.5 clk = ~clk; // 200MHz simulation clock

    initial begin
        clk = 0; rst_n = 0;
        host_rx_valid = 0; sram_resp_valid = 0;
        
        #20 rst_n = 1;
        #10;
        
        // 1. Send Host Request
        $display("T=%0t [TB] Sending CXL.cache Key request...", $time);
        host_rx_flit = 512'hDEADBEEF_CAFE;
        host_rx_valid = 1;
        #5 host_rx_valid = 0;
        
        // 2. Wait for Lookup
        wait(dut.state == 1); // LOOKUP state
        #15;
        
        // 3. Simulate SRAM Response (Vertical 3D path)
        $display("T=%0t [TB] SRAM Response received (Pointer: 0x7).", $time);
        sram_pointer_out = 32'h7;
        sram_resp_valid = 1;
        #5 sram_resp_valid = 0;
        
        // 4. Verify DRAM Trigger
        wait(dram_tx_valid == 1);
        $display("T=%0t [TB] SUCCESS: CXL flit routed to DRAM Die %0d.", $time, dut.dram_die_sel);
        
        #50 $finish;
    end

endmodule
