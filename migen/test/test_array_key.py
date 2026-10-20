import re
import unittest

from migen import *
from migen.fhdl import verilog


class _ArrayKey(Module):
    """An Array write whose index holds an Array read."""
    def __init__(self):
        self.empty = Signal()
        self.live = Signal()
        self.rd = Signal()
        self.fire = Signal()
        self.ready = Array([Signal(name="ready_{}".format(k)) for k in range(2)])
        self.fifo = Array([Signal(name="fifo_{}".format(k)) for k in range(2)])
        key = Mux(self.empty, self.live, self.fifo[self.rd])
        self.sync += If(self.fire, self.ready[key].eq(0))
        self.rd_val = Signal()
        self.comb += self.rd_val.eq(self.ready[key])


class ArrayKeyCase(unittest.TestCase):
    def test_nested_read_in_write_index_is_not_a_target(self):
        v = verilog.convert(_ArrayKey(), name="dut").main_source
        written = set(re.findall(r"(\w+) <= ", v))
        self.assertIn("ready_0", written)
        self.assertIn("ready_1", written)
        self.assertNotIn("fifo_0", written)
        self.assertNotIn("fifo_1", written)
