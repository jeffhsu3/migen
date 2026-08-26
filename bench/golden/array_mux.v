/* Machine-generated using Migen */
module top(
	input [2:0] sel,
	input [11:0] data,
	output [11:0] a0out,
	output [11:0] a1out,
	output [11:0] a2out,
	output [11:0] a3out,
	output reg [11:0] dst0,
	output reg [11:0] dst1,
	output reg [11:0] dst2,
	output reg [11:0] dst3,
	output reg [11:0] dst4,
	output reg [11:0] dst5,
	output reg [11:0] dst6,
	output reg [11:0] dst7,
	input en,
	input sys_clk,
	input sys_rst
);

reg [11:0] a0c0 = 12'd0;
reg [11:0] a0c1 = 12'd0;
reg [11:0] a0c2 = 12'd0;
reg [11:0] a0c3 = 12'd0;
reg [11:0] a0c4 = 12'd0;
reg [11:0] a0c5 = 12'd0;
reg [11:0] a0c6 = 12'd0;
reg [11:0] a0c7 = 12'd0;
reg [11:0] a1c0 = 12'd0;
reg [11:0] a1c1 = 12'd0;
reg [11:0] a1c2 = 12'd0;
reg [11:0] a1c3 = 12'd0;
reg [11:0] a1c4 = 12'd0;
reg [11:0] a1c5 = 12'd0;
reg [11:0] a1c6 = 12'd0;
reg [11:0] a1c7 = 12'd0;
reg [11:0] a2c0 = 12'd0;
reg [11:0] a2c1 = 12'd0;
reg [11:0] a2c2 = 12'd0;
reg [11:0] a2c3 = 12'd0;
reg [11:0] a2c4 = 12'd0;
reg [11:0] a2c5 = 12'd0;
reg [11:0] a2c6 = 12'd0;
reg [11:0] a2c7 = 12'd0;
reg [11:0] a3c0 = 12'd0;
reg [11:0] a3c1 = 12'd0;
reg [11:0] a3c2 = 12'd0;
reg [11:0] a3c3 = 12'd0;
reg [11:0] a3c4 = 12'd0;
reg [11:0] a3c5 = 12'd0;
reg [11:0] a3c6 = 12'd0;
reg [11:0] a3c7 = 12'd0;
reg [11:0] comb_self0;
reg [11:0] comb_self1;
reg [11:0] comb_self2;
reg [11:0] comb_self3;
reg [11:0] sync_self = 12'd0;

// synthesis translate_off
reg dummy_s;
initial dummy_s <= 1'd0;
// synthesis translate_on

assign a0out = comb_self0;
assign a1out = comb_self1;
assign a2out = comb_self2;
assign a3out = comb_self3;

// synthesis translate_off
reg dummy_d;
// synthesis translate_on
always @(*) begin
	comb_self0 <= 12'd0;
	case (sel)
		1'd0: begin
			comb_self0 <= a0c0;
		end
		1'd1: begin
			comb_self0 <= a0c1;
		end
		2'd2: begin
			comb_self0 <= a0c2;
		end
		2'd3: begin
			comb_self0 <= a0c3;
		end
		3'd4: begin
			comb_self0 <= a0c4;
		end
		3'd5: begin
			comb_self0 <= a0c5;
		end
		3'd6: begin
			comb_self0 <= a0c6;
		end
		default: begin
			comb_self0 <= a0c7;
		end
	endcase
// synthesis translate_off
	dummy_d <= dummy_s;
// synthesis translate_on
end

// synthesis translate_off
reg dummy_d_1;
// synthesis translate_on
always @(*) begin
	comb_self1 <= 12'd0;
	case (sel)
		1'd0: begin
			comb_self1 <= a1c0;
		end
		1'd1: begin
			comb_self1 <= a1c1;
		end
		2'd2: begin
			comb_self1 <= a1c2;
		end
		2'd3: begin
			comb_self1 <= a1c3;
		end
		3'd4: begin
			comb_self1 <= a1c4;
		end
		3'd5: begin
			comb_self1 <= a1c5;
		end
		3'd6: begin
			comb_self1 <= a1c6;
		end
		default: begin
			comb_self1 <= a1c7;
		end
	endcase
// synthesis translate_off
	dummy_d_1 <= dummy_s;
// synthesis translate_on
end

// synthesis translate_off
reg dummy_d_2;
// synthesis translate_on
always @(*) begin
	comb_self2 <= 12'd0;
	case (sel)
		1'd0: begin
			comb_self2 <= a2c0;
		end
		1'd1: begin
			comb_self2 <= a2c1;
		end
		2'd2: begin
			comb_self2 <= a2c2;
		end
		2'd3: begin
			comb_self2 <= a2c3;
		end
		3'd4: begin
			comb_self2 <= a2c4;
		end
		3'd5: begin
			comb_self2 <= a2c5;
		end
		3'd6: begin
			comb_self2 <= a2c6;
		end
		default: begin
			comb_self2 <= a2c7;
		end
	endcase
// synthesis translate_off
	dummy_d_2 <= dummy_s;
// synthesis translate_on
end

// synthesis translate_off
reg dummy_d_3;
// synthesis translate_on
always @(*) begin
	comb_self3 <= 12'd0;
	case (sel)
		1'd0: begin
			comb_self3 <= a3c0;
		end
		1'd1: begin
			comb_self3 <= a3c1;
		end
		2'd2: begin
			comb_self3 <= a3c2;
		end
		2'd3: begin
			comb_self3 <= a3c3;
		end
		3'd4: begin
			comb_self3 <= a3c4;
		end
		3'd5: begin
			comb_self3 <= a3c5;
		end
		3'd6: begin
			comb_self3 <= a3c6;
		end
		default: begin
			comb_self3 <= a3c7;
		end
	endcase
// synthesis translate_off
	dummy_d_3 <= dummy_s;
// synthesis translate_on
end

always @(posedge sys_clk) begin
	a0c0 <= (data + 12'd0);
	a0c1 <= (data + 12'd0);
	a0c2 <= (data + 12'd0);
	a0c3 <= (data + 12'd0);
	a0c4 <= (data + 12'd0);
	a0c5 <= (data + 12'd0);
	a0c6 <= (data + 12'd0);
	a0c7 <= (data + 12'd0);
	a1c0 <= (data + 12'd0);
	a1c1 <= (data + 12'd1);
	a1c2 <= (data + 12'd2);
	a1c3 <= (data + 12'd3);
	a1c4 <= (data + 12'd4);
	a1c5 <= (data + 12'd5);
	a1c6 <= (data + 12'd6);
	a1c7 <= (data + 12'd7);
	a2c0 <= (data + 12'd0);
	a2c1 <= (data + 12'd2);
	a2c2 <= (data + 12'd4);
	a2c3 <= (data + 12'd6);
	a2c4 <= (data + 12'd8);
	a2c5 <= (data + 12'd10);
	a2c6 <= (data + 12'd12);
	a2c7 <= (data + 12'd14);
	a3c0 <= (data + 12'd0);
	a3c1 <= (data + 12'd3);
	a3c2 <= (data + 12'd6);
	a3c3 <= (data + 12'd9);
	a3c4 <= (data + 12'd12);
	a3c5 <= (data + 12'd15);
	a3c6 <= (data + 12'd18);
	a3c7 <= (data + 12'd21);
	if (en) begin
		sync_self = data;
		case (sel)
			1'd0: begin
				dst0 <= sync_self;
			end
			1'd1: begin
				dst1 <= sync_self;
			end
			2'd2: begin
				dst2 <= sync_self;
			end
			2'd3: begin
				dst3 <= sync_self;
			end
			3'd4: begin
				dst4 <= sync_self;
			end
			3'd5: begin
				dst5 <= sync_self;
			end
			3'd6: begin
				dst6 <= sync_self;
			end
			default: begin
				dst7 <= sync_self;
			end
		endcase
	end
	if (sys_rst) begin
		a0c0 <= 12'd0;
		a0c1 <= 12'd0;
		a0c2 <= 12'd0;
		a0c3 <= 12'd0;
		a0c4 <= 12'd0;
		a0c5 <= 12'd0;
		a0c6 <= 12'd0;
		a0c7 <= 12'd0;
		a1c0 <= 12'd0;
		a1c1 <= 12'd0;
		a1c2 <= 12'd0;
		a1c3 <= 12'd0;
		a1c4 <= 12'd0;
		a1c5 <= 12'd0;
		a1c6 <= 12'd0;
		a1c7 <= 12'd0;
		a2c0 <= 12'd0;
		a2c1 <= 12'd0;
		a2c2 <= 12'd0;
		a2c3 <= 12'd0;
		a2c4 <= 12'd0;
		a2c5 <= 12'd0;
		a2c6 <= 12'd0;
		a2c7 <= 12'd0;
		a3c0 <= 12'd0;
		a3c1 <= 12'd0;
		a3c2 <= 12'd0;
		a3c3 <= 12'd0;
		a3c4 <= 12'd0;
		a3c5 <= 12'd0;
		a3c6 <= 12'd0;
		a3c7 <= 12'd0;
		dst0 <= 12'd0;
		dst1 <= 12'd0;
		dst2 <= 12'd0;
		dst3 <= 12'd0;
		dst4 <= 12'd0;
		dst5 <= 12'd0;
		dst6 <= 12'd0;
		dst7 <= 12'd0;
	end
end

endmodule

