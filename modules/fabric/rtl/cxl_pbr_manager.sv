// 🚀 Search King CXL 3.1 PBR Manager
// Function: Routes CXL flits between Host, SRAM Tags, and DRAM Pool.

module cxl_pbr_manager (
    input  logic        clk,
    input  logic        rst_n,
    
    // Host CXL Interface
    input  logic [511:0] host_rx_flit,
    input  logic         host_rx_valid,
    output logic         host_rx_ready,
    
    // SRAM KV-Interface (Vertical 3D)
    output logic [63:0]  sram_key_hash,
    output logic         sram_req_valid,
    input  logic [31:0]  sram_pointer_out,
    input  logic         sram_resp_valid,
    
    // DRAM Interface (UCIe 2.0)
    output logic [511:0] dram_tx_flit,
    output logic [3:0]   dram_die_sel, // Select 1 of 8 DRAMs
    output logic         dram_tx_valid
);

    typedef enum logic [1:0] {IDLE, LOOKUP, FETCH, RETURN} state_t;
    state_t state;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            sram_req_valid <= 0;
            dram_tx_valid <= 0;
        end else begin
            case (state)
                IDLE: begin
                    if (host_rx_valid) begin
                        sram_key_hash <= host_rx_flit[63:0]; // Extract Key
                        sram_req_valid <= 1;
                        state <= LOOKUP;
                    end
                end
                
                LOOKUP: begin
                    if (sram_resp_valid) begin
                        sram_req_valid <= 0;
                        dram_die_sel <= sram_pointer_out[3:0]; // Use pointer to select die
                        dram_tx_flit <= host_rx_flit; // Forward flit
                        dram_tx_valid <= 1;
                        state <= FETCH;
                    end
                end
                
                FETCH: begin
                    dram_tx_valid <= 0;
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule
