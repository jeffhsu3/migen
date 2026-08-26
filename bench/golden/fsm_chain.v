/* Machine-generated using Migen */
module top(
	input [7:0] x,
	input start,
	output reg [7:0] y,
	output reg [7:0] y_1,
	output reg [7:0] y_2,
	output reg [7:0] y_3,
	input sys_clk,
	input sys_rst
);

reg prev_done = 1'd1;
wire fsmstage0_start;
wire [7:0] fsmstage0_x;
reg fsmstage0_done;
reg [7:0] fsmstage0_acc = 8'd0;
reg fsmstage0_is_ongoing;
wire fsmstage1_start;
wire [7:0] fsmstage1_x;
reg fsmstage1_done;
reg [7:0] fsmstage1_acc = 8'd0;
reg fsmstage1_is_ongoing;
wire fsmstage2_start;
wire [7:0] fsmstage2_x;
reg fsmstage2_done;
reg [7:0] fsmstage2_acc = 8'd0;
reg fsmstage2_is_ongoing;
wire fsmstage3_start;
wire [7:0] fsmstage3_x;
reg fsmstage3_done;
reg [7:0] fsmstage3_acc = 8'd0;
reg fsmstage3_is_ongoing;
reg [2:0] fsmstage0_state = 3'd0;
reg [2:0] fsmstage0_next_state;
reg [2:0] fsmstage1_state = 3'd0;
reg [2:0] fsmstage1_next_state;
reg [2:0] fsmstage2_state = 3'd0;
reg [2:0] fsmstage2_next_state;
reg [2:0] fsmstage3_state = 3'd0;
reg [2:0] fsmstage3_next_state;

// synthesis translate_off
reg dummy_s;
initial dummy_s <= 1'd0;
// synthesis translate_on

assign fsmstage0_start = (start & prev_done);
assign fsmstage0_x = (x + 8'd0);
assign fsmstage1_start = (start & fsmstage0_done);
assign fsmstage1_x = (x + 8'd1);
assign fsmstage2_start = (start & fsmstage1_done);
assign fsmstage2_x = (x + 8'd2);
assign fsmstage3_start = (start & fsmstage2_done);
assign fsmstage3_x = (x + 8'd3);

// synthesis translate_off
reg dummy_d;
// synthesis translate_on
always @(*) begin
	fsmstage0_done <= 1'd0;
	y <= 8'd0;
	fsmstage0_is_ongoing <= 1'd0;
	fsmstage0_next_state <= 3'd0;
	fsmstage0_next_state <= fsmstage0_state;
	case (fsmstage0_state)
		1'd1: begin
			fsmstage0_next_state <= 2'd2;
			y <= (fsmstage0_acc + 8'd0);
		end
		2'd2: begin
			fsmstage0_next_state <= 2'd3;
			y <= (fsmstage0_acc + 8'd1);
		end
		2'd3: begin
			fsmstage0_next_state <= 3'd4;
			y <= (fsmstage0_acc + 8'd2);
		end
		3'd4: begin
			fsmstage0_next_state <= 3'd5;
			y <= (fsmstage0_acc + 8'd3);
		end
		3'd5: begin
			fsmstage0_next_state <= 3'd6;
			y <= (fsmstage0_acc + 8'd4);
		end
		3'd6: begin
			fsmstage0_next_state <= 1'd0;
			y <= fsmstage0_acc;
		end
		default: begin
			fsmstage0_done <= 1'd1;
			if (fsmstage0_start) begin
				fsmstage0_next_state <= 1'd1;
			end
			fsmstage0_is_ongoing <= 1'd1;
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
	fsmstage1_done <= 1'd0;
	y_1 <= 8'd0;
	fsmstage1_is_ongoing <= 1'd0;
	fsmstage1_next_state <= 3'd0;
	fsmstage1_next_state <= fsmstage1_state;
	case (fsmstage1_state)
		1'd1: begin
			fsmstage1_next_state <= 2'd2;
			y_1 <= (fsmstage1_acc + 8'd0);
		end
		2'd2: begin
			fsmstage1_next_state <= 2'd3;
			y_1 <= (fsmstage1_acc + 8'd1);
		end
		2'd3: begin
			fsmstage1_next_state <= 3'd4;
			y_1 <= (fsmstage1_acc + 8'd2);
		end
		3'd4: begin
			fsmstage1_next_state <= 3'd5;
			y_1 <= (fsmstage1_acc + 8'd3);
		end
		3'd5: begin
			fsmstage1_next_state <= 3'd6;
			y_1 <= (fsmstage1_acc + 8'd4);
		end
		3'd6: begin
			fsmstage1_next_state <= 1'd0;
			y_1 <= fsmstage1_acc;
		end
		default: begin
			fsmstage1_done <= 1'd1;
			if (fsmstage1_start) begin
				fsmstage1_next_state <= 1'd1;
			end
			fsmstage1_is_ongoing <= 1'd1;
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
	fsmstage2_done <= 1'd0;
	y_2 <= 8'd0;
	fsmstage2_is_ongoing <= 1'd0;
	fsmstage2_next_state <= 3'd0;
	fsmstage2_next_state <= fsmstage2_state;
	case (fsmstage2_state)
		1'd1: begin
			fsmstage2_next_state <= 2'd2;
			y_2 <= (fsmstage2_acc + 8'd0);
		end
		2'd2: begin
			fsmstage2_next_state <= 2'd3;
			y_2 <= (fsmstage2_acc + 8'd1);
		end
		2'd3: begin
			fsmstage2_next_state <= 3'd4;
			y_2 <= (fsmstage2_acc + 8'd2);
		end
		3'd4: begin
			fsmstage2_next_state <= 3'd5;
			y_2 <= (fsmstage2_acc + 8'd3);
		end
		3'd5: begin
			fsmstage2_next_state <= 3'd6;
			y_2 <= (fsmstage2_acc + 8'd4);
		end
		3'd6: begin
			fsmstage2_next_state <= 1'd0;
			y_2 <= fsmstage2_acc;
		end
		default: begin
			fsmstage2_done <= 1'd1;
			if (fsmstage2_start) begin
				fsmstage2_next_state <= 1'd1;
			end
			fsmstage2_is_ongoing <= 1'd1;
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
	fsmstage3_done <= 1'd0;
	y_3 <= 8'd0;
	fsmstage3_is_ongoing <= 1'd0;
	fsmstage3_next_state <= 3'd0;
	fsmstage3_next_state <= fsmstage3_state;
	case (fsmstage3_state)
		1'd1: begin
			fsmstage3_next_state <= 2'd2;
			y_3 <= (fsmstage3_acc + 8'd0);
		end
		2'd2: begin
			fsmstage3_next_state <= 2'd3;
			y_3 <= (fsmstage3_acc + 8'd1);
		end
		2'd3: begin
			fsmstage3_next_state <= 3'd4;
			y_3 <= (fsmstage3_acc + 8'd2);
		end
		3'd4: begin
			fsmstage3_next_state <= 3'd5;
			y_3 <= (fsmstage3_acc + 8'd3);
		end
		3'd5: begin
			fsmstage3_next_state <= 3'd6;
			y_3 <= (fsmstage3_acc + 8'd4);
		end
		3'd6: begin
			fsmstage3_next_state <= 1'd0;
			y_3 <= fsmstage3_acc;
		end
		default: begin
			fsmstage3_done <= 1'd1;
			if (fsmstage3_start) begin
				fsmstage3_next_state <= 1'd1;
			end
			fsmstage3_is_ongoing <= 1'd1;
		end
	endcase
// synthesis translate_off
	dummy_d_3 <= dummy_s;
// synthesis translate_on
end

always @(posedge sys_clk) begin
	if (fsmstage0_is_ongoing) begin
		fsmstage0_acc <= fsmstage0_x;
	end else begin
		fsmstage0_acc <= (fsmstage0_acc + 8'd1);
	end
	fsmstage0_state <= fsmstage0_next_state;
	if (fsmstage1_is_ongoing) begin
		fsmstage1_acc <= fsmstage1_x;
	end else begin
		fsmstage1_acc <= (fsmstage1_acc + 8'd1);
	end
	fsmstage1_state <= fsmstage1_next_state;
	if (fsmstage2_is_ongoing) begin
		fsmstage2_acc <= fsmstage2_x;
	end else begin
		fsmstage2_acc <= (fsmstage2_acc + 8'd1);
	end
	fsmstage2_state <= fsmstage2_next_state;
	if (fsmstage3_is_ongoing) begin
		fsmstage3_acc <= fsmstage3_x;
	end else begin
		fsmstage3_acc <= (fsmstage3_acc + 8'd1);
	end
	fsmstage3_state <= fsmstage3_next_state;
	if (sys_rst) begin
		fsmstage0_acc <= 8'd0;
		fsmstage1_acc <= 8'd0;
		fsmstage2_acc <= 8'd0;
		fsmstage3_acc <= 8'd0;
		fsmstage0_state <= 3'd0;
		fsmstage1_state <= 3'd0;
		fsmstage2_state <= 3'd0;
		fsmstage3_state <= 3'd0;
	end
end

endmodule

