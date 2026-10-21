import itertools
import os
import shutil
import subprocess
import tempfile
import unittest

from migen import *
from migen.fhdl import verilog
from migen.sim.core import Evaluator


def _build_design():
    dut = Module()
    shapes = [("a", 1), ("b", 1), ("w", 4), ("s", (4, True)),
              ("shift", 2)]
    inputs = [Signal(shape, name_override=name) for name, shape in shapes]
    a, b, w, s, shift = inputs
    expressions = [
        ("eq_not", 1, a == ~b),
        ("ne_not", 1, a != ~b),
        ("lt_not", 1, a < ~b),
        ("le_not", 1, a <= ~b),
        ("gt_not", 1, a > ~b),
        ("ge_not", 1, a >= ~b),
        ("wide_not", 2, ~b),
        ("word_not", 4, ~w),
        ("wider_not", 8, ~w),
        ("narrow_not", 2, ~w),
        ("double_not", 8, ~~w),
        ("signed_not", (8, True), ~s),
        ("signed_constant", (8, True), ~C(15, (4, True))),
        ("unsigned_constant", 8, ~C(16, 4)),
        ("wide_comparison", 1, w == ~b),
        ("signed_comparison", 1, s == ~w),
        ("signed_less", 1, s < ~w),
        ("signed_right_comparison", 1, w == ~s),
        ("nested_comparison", 1, (s < ~w) == ~b),
        ("comparison_in_sum", (8, True), ~(s < 0) + s),
        ("comparison_operand", (8, True), ~(s == ~w) + s),
        ("negated_comparison", 1, -(s < 0) < 0),
        ("sum_not", 8, ~(w + b)),
        ("not_sum", 8, ~w + b),
        ("narrow_sum_not", 2, ~(w + b)),
        ("difference_not", 8, ~(w - b)),
        ("product_not", 8, ~(w * w)),
        ("not_product", 8, ~w * w),
        ("mixed_sum", (8, True), ~w + s),
        ("mixed_signed_sum", (8, True), ~s + w),
        ("negated_not", (8, True), -~w),
        ("not_negated", (8, True), ~-w),
        ("right_shift", 4, ~w >> shift),
        ("wide_right_shift", 8, ~w >> shift),
        ("sum_right_shift", 4, (~w + b) >> shift),
        ("left_shift", 8, ~w << shift),
        ("shift_count", 8, w << ~b),
        ("signed_shift", (8, True), ~s >> shift),
        ("signed_count_parent", (8, True), (~w >> s) + s),
        ("mux_branch", 8, Mux(a, ~w, b)),
        ("mux_condition", 4, Mux(~b, w, 0)),
        ("mixed_mux", (8, True), Mux(a, ~w, s)),
        ("comparison_mux", (8, True), Mux(a, ~(s < 0), s)),
        ("concatenation", 8, Cat(~b, ~w)),
        ("sum_concatenation", 8, Cat(~w + b, ~b)),
        ("replication", 8, Replicate(~b, 3)),
        ("sum_replication", 10, Replicate(~w + b, 2)),
        ("slice_not", 2, (~w)[1:3]),
        ("sum_slice", 4, (~w + b)[1:5]),
        ("array_choice", 8, Array([~b, ~w])[a]),
    ]
    outputs = [Signal(shape, name_override=name)
               for name, shape, expression in expressions]
    dut.comb += [output.eq(expression)
                 for output, (_, _, expression) in zip(outputs, expressions)]
    if_not = Signal(name_override="if_not")
    if_sum_not = Signal(name_override="if_sum_not")
    case_not = Signal(2, name_override="case_not")
    case_signed = Signal(2, name_override="case_signed")
    case_mixed = Signal(2, name_override="case_mixed")
    slice_target = Signal(4, name_override="slice_target")
    cat_low = Signal(name_override="cat_low")
    cat_high = Signal(2, name_override="cat_high")
    dut.comb += [
        If(~b, if_not.eq(1)),
        If(~(w + b), if_sum_not.eq(1)),
        Case(~b, {C(2, 2): case_not.eq(1), C(3, 2): case_not.eq(2)}),
        Case(~s, {C(-1, (8, True)): case_signed.eq(1),
                  C(0, (8, True)): case_signed.eq(2)}),
        Case(~s, {C(240, 8): case_mixed.eq(1),
                  C(255, 8): case_mixed.eq(2)}),
        slice_target.eq(0),
        slice_target[1:3].eq(~b),
        Cat(cat_low, cat_high).eq(~b),
    ]
    outputs += [if_not, if_sum_not, case_not, case_signed, case_mixed,
                slice_target, cat_low, cat_high]
    return dut, inputs, outputs


class InvertCase(unittest.TestCase):
    def test_single_bit_comparison_and_widening(self):
        dut = Module()
        a, b = Signal(), Signal()
        equal, wide = Signal(), Signal(2)
        dut.comb += [equal.eq(a == ~b), wide.eq(~b)]

        def check():
            for av, bv in itertools.product(range(2), repeat=2):
                yield a.eq(av)
                yield b.eq(bv)
                yield
                self.assertEqual((yield equal), int(av != bv))
                self.assertEqual((yield wide), 3 - bv)
                self.assertEqual((yield ~b), 1 - bv)

        run_simulation(dut, check())

    def test_unsigned_word(self):
        dut = Module()
        word, inverted = Signal(4), Signal(4)
        dut.comb += inverted.eq(~word)

        def check():
            for value in range(16):
                yield word.eq(value)
                yield
                self.assertEqual((yield ~word), 15 - value)
                self.assertEqual((yield inverted), 15 - value)
                self.assertEqual((yield ~~word), value)

        run_simulation(dut, check())

    def test_signed_word(self):
        dut = Module()
        word, inverted = Signal((4, True)), Signal((8, True))
        dut.comb += inverted.eq(~word)

        def check():
            for value in range(-8, 8):
                yield word.eq(value)
                yield
                self.assertEqual((yield ~word), ~value)
                self.assertEqual((yield inverted), ~value)

        run_simulation(dut, check())

    def test_constants(self):
        evaluator = Evaluator([], {})
        self.assertEqual(evaluator.eval(~C(5, 4)), 10)
        self.assertEqual(evaluator.eval(~C(-3, (4, True))), 2)
        self.assertEqual(evaluator.eval(~C(15, (4, True))), 0)
        self.assertEqual(evaluator.eval(~C(16, 4)), 15)

    def test_postcommit(self):
        evaluator = Evaluator([], {})
        bit = Signal()
        evaluator.assign(bit, 1)
        self.assertEqual(evaluator.eval(~bit), 1)
        self.assertEqual(evaluator.eval(~bit, postcommit=True), 0)

    def test_expression_contexts(self):
        dut, inputs, outputs = _build_design()
        expected = {
            "wider_not": 250,
            "signed_constant": 0,
            "unsigned_constant": 255,
            "mixed_sum": 7,
            "mixed_signed_sum": 7,
            "negated_not": -10,
            "not_negated": 4,
            "right_shift": 5,
            "wide_right_shift": 125,
            "sum_right_shift": 5,
            "left_shift": 244,
            "shift_count": 10,
            "signed_shift": 1,
            "mux_condition": 5,
            "mixed_mux": -3,
            "concatenation": 21,
            "sum_concatenation": 26,
            "replication": 7,
            "sum_replication": 170,
            "sum_slice": 13,
            "array_choice": 15,
            "if_not": 1,
            "case_not": 2,
            "slice_target": 6,
            "cat_low": 1,
            "cat_high": 3,
        }

        def check():
            for signal, value in zip(inputs, (0, 0, 5, -3, 1)):
                yield signal.eq(value)
            yield
            for signal in outputs:
                if signal.name_override in expected:
                    self.assertEqual((yield signal),
                                     expected[signal.name_override],
                                     signal.name_override)

        run_simulation(dut, check())

    def test_memory_write(self):
        dut = Module()
        word = Signal(4, reset=5)
        memory = Memory(8, 2)
        dut.specials += memory

        def check():
            yield memory[0].eq(~word)
            yield
            self.assertEqual((yield memory[0]), 250)

        run_simulation(dut, check())

    def test_synchronous_assignment(self):
        dut = Module()
        bit = Signal()
        inverted = Signal(2)
        dut.sync += inverted.eq(~bit)

        def check():
            for value in (0, 1):
                yield bit.eq(value)
                yield
                yield
                self.assertEqual((yield inverted), 3 - value)

        run_simulation(dut, check())

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"),
                         "requires Icarus Verilog")
    def test_matches_verilog(self):
        # Cover every pair of unsigned/signed four-bit values, both one-bit
        # inputs, and all shift counts across those vectors.
        vectors = [(a, b, w, s, (w + s) % 4)
                   for a, b, w, s in itertools.product(
                       range(2), range(2), range(16), range(-8, 8))]
        dut, inputs, outputs = _build_design()
        simulated = []

        def collect():
            for vector in vectors:
                for signal, value in zip(inputs, vector):
                    yield signal.eq(value)
                yield
                row = []
                for signal in outputs:
                    row.append((yield signal) & (2**len(signal) - 1))
                simulated.append(row)

        run_simulation(dut, collect())
        dut, inputs, outputs = _build_design()
        signals = inputs + outputs
        source = str(verilog.convert(dut, ios=set(signals)))
        tb = ["module tb;"]
        for signal in signals:
            kind = "reg" if signal in inputs else "wire"
            tb.append("{} [{}:0] {};".format(
                kind, len(signal) - 1, signal.name_override))
        tb.append("top dut({});".format(
            ", ".join(".{0}({0})".format(s.name_override) for s in signals)))
        tb.append("initial begin")
        for vector in vectors:
            for signal, value in zip(inputs, vector):
                value &= 2**len(signal) - 1
                tb.append("{} = {}'d{};".format(
                    signal.name_override, len(signal), value))
            tb.append('#1; $display("ROW {}", {});'.format(
                " ".join(["%0d"] * len(outputs)),
                ", ".join(s.name_override for s in outputs)))
        tb.extend(["$finish;", "end", "endmodule"])
        with tempfile.TemporaryDirectory() as directory:
            dut_path = os.path.join(directory, "dut.v")
            tb_path = os.path.join(directory, "tb.v")
            executable = os.path.join(directory, "sim.vvp")
            with open(dut_path, "w") as f:
                f.write(source)
            with open(tb_path, "w") as f:
                f.write("\n".join(tb))
            subprocess.check_output([
                "iverilog", "-g2012", "-gstrict-expr-width", "-s", "tb",
                "-o", executable, dut_path, tb_path], stderr=subprocess.STDOUT)
            result = subprocess.check_output(["vvp", executable]).decode()
        verilog_rows = [list(map(int, line.split()[1:]))
                        for line in result.splitlines()
                        if line.startswith("ROW ")]
        self.assertEqual(len(verilog_rows), len(vectors))
        for vector, actual, expected in zip(vectors, simulated, verilog_rows):
            for signal, sim_value, rtl_value in zip(outputs, actual, expected):
                self.assertEqual(
                    sim_value, rtl_value,
                    "{} at {}".format(signal.name_override, vector))
