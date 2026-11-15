import unittest

from migen import *
from migen.fhdl import verilog
from migen.fhdl.namer import build_namespace
from migen.genlib.fsm import FSM


class _UART(Module):
    def __init__(self):
        self.pad = Signal(name_override="uart")
        self.tx = Signal()
        self.rx = Signal()
        self.cnt = Signal(8)
        self.sync += (
            self.cnt.eq(self.cnt + 1),
            self.tx.eq(self.rx ^ self.cnt[0]),
            self.pad.eq(self.tx),
        )


class _Blinker(Module):
    def __init__(self):
        self.led = Signal()
        self.cnt = Signal(4)
        self.sync += self.cnt.eq(self.cnt + 1), self.led.eq(self.cnt[-1])


class _Sub(Module):
    def __init__(self):
        self.x = Signal()
        self.sync += self.x.eq(~self.x)


class NamerCase(unittest.TestCase):
    def test_name_override_matching_toplevel_module_does_not_prefix_siblings(self):
        out = verilog.convert(_UART())
        src = out.main_source
        self.assertIn("reg tx ", src)
        self.assertIn("reg rx ", src)
        self.assertIn("reg [7:0] cnt ", src)
        self.assertNotIn("uart_tx", src)
        self.assertNotIn("uart_cnt", src)

    def test_name_override_collision_uses_namespace_suffix(self):
        # Override created before internal signal
        pad1 = Signal(name_override="led")
        b1 = _Blinker()
        ns1 = build_namespace({pad1, b1.led, b1.cnt})
        self.assertEqual(ns1.get_name(pad1), "led")
        self.assertEqual(ns1.get_name(b1.led), "led_1")

        # Internal signal created before override
        b2 = _Blinker()
        pad2 = Signal(name_override="led")
        ns2 = build_namespace({pad2, b2.led, b2.cnt})
        self.assertEqual(ns2.get_name(pad2), "led")
        self.assertEqual(ns2.get_name(b2.led), "led_1")

    def test_traced_io_preserves_submodule_qualification(self):
        class Top(Module):
            def __init__(self):
                self.submodules.u0 = _Sub()
                self.submodules.u1 = _Sub()

        t = Top()
        out = verilog.convert(t, ios={t.u0.x})
        self.assertEqual(out.ns.get_name(t.u0.x), "x")
        self.assertEqual(out.ns.get_name(t.u1.x), "u1_x")

    def test_related_signal_with_name_override(self):
        class Top(Module):
            def __init__(self):
                self.a = Signal(8, name_override="custom")
                self.b = Signal(8, name_override="custom")
                fsm = FSM(reset_state="IDLE")
                self.submodules += fsm
                fsm.act("IDLE",
                        NextValue(self.a, 1),
                        NextValue(self.b, 2),
                        NextState("DONE"))
                fsm.act("DONE",
                        NextState("IDLE"))

        out = verilog.convert(Top())
        names = {out.ns.get_name(s) for s in out.ns.pnd}
        self.assertTrue(any(n.startswith("custom_") and not n.startswith("custom_1_")
                            for n in names))
        self.assertTrue(any(n.startswith("custom_1_") for n in names))

        # Related target not in the signals set passed to build_namespace
        orphan = Signal(name_override="ext_sig")
        rel = Signal(related=orphan)
        ns = build_namespace({rel})
        self.assertEqual(ns.get_name(rel), "ext_sig_rel")

    def test_clock_domain_rename_updates_repr_and_backtrace(self):
        cd = ClockDomain("old")
        self.assertIn("old_clk", repr(cd.clk))
        cd.rename("new")
        self.assertIn("new_clk", repr(cd.clk))
        self.assertIn("new_rst", repr(cd.rst))
        self.assertEqual(cd.clk.backtrace[-1][0], "new_clk")
        self.assertEqual(cd.rst.backtrace[-1][0], "new_rst")

        # Empty backtrace does not crash repr()
        s = Signal()
        s.backtrace = []
        self.assertIn("anonymous", repr(s))
