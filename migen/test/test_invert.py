import unittest

from migen import *
from migen.sim import run_simulation


class _Invert(Module):
    def __init__(self):
        self.a = Signal()
        self.b = Signal()
        self.eq_not = Signal()
        self.w = Signal(4)
        self.inv_w = Signal(4)
        self.comb += [
            self.eq_not.eq(self.a == ~self.b),
            self.inv_w.eq(~self.w),
        ]


class InvertCase(unittest.TestCase):
    def test_invert_is_bounded_to_the_operand_width(self):
        dut = _Invert()
        seen = []

        def tb():
            for a in (0, 1):
                for b in (0, 1):
                    yield dut.a.eq(a)
                    yield dut.b.eq(b)
                    yield dut.w.eq(0b0101)
                    yield
                    seen.append((a, b, (yield dut.eq_not), (yield dut.inv_w)))

        run_simulation(dut, tb())
        for a, b, eq_not, inv_w in seen:
            self.assertEqual(eq_not, int(a != b))
            self.assertEqual(inv_w, 0b1010)
