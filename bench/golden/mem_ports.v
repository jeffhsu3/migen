/* Machine-generated using Migen */
module top(
	input [5:0] we_adr,
	input [31:0] we_dat,
	input we,
	output [31:0] dat_r,
	input [5:0] adr,
	input re,
	output [31:0] dat_r_1,
	input [5:0] adr_1,
	input re_1,
	input sys_clk,
	input sys_rst
);

wire [5:0] wrport_adr;
wire [31:0] wrport_dat_r;
wire wrport_we;
wire [31:0] wrport_dat_w;
wire [5:0] port_adr0;
wire port_re0;
wire [5:0] port_adr1;
wire port_re1;

// synthesis translate_off
reg dummy_s;
initial dummy_s <= 1'd0;
// synthesis translate_on

assign wrport_adr = we_adr;
assign wrport_dat_w = we_dat;
assign wrport_we = we;
assign port_adr0 = adr;
assign port_re0 = re;
assign port_adr1 = adr_1;
assign port_re1 = re_1;

reg [31:0] mem[0:63];
reg [5:0] memadr;
reg [5:0] memadr_1;
reg [5:0] memadr_2;
always @(posedge sys_clk) begin : mem_write_block
	if (wrport_we)
		mem[wrport_adr] <= wrport_dat_w;
	memadr <= wrport_adr;
end

always @(posedge sys_clk) begin : mem_write_block_1
	if (port_re0)
		memadr_1 <= port_adr0;
end

always @(posedge sys_clk) begin : mem_write_block_2
	if (port_re1)
		memadr_2 <= port_adr1;
end

assign wrport_dat_r = mem[memadr];
assign dat_r = mem[memadr_1];
assign dat_r_1 = mem[memadr_2];

endmodule

