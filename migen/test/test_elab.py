import random
import subprocess
import sys
import unittest

from migen import *
from migen.fhdl import verilog
from migen.fhdl.namer import Namespace, build_namespace
from migen.fhdl.structure import _Assign, _Operator, _Part, _Slice
from migen.fhdl.tools import (
    _Lowerer,
    group_by_targets,
    list_targets,
    lower_basics,
    lower_complex_slices,
)
from migen.fhdl.visit import NodeTransformer, NodeVisitor
from migen.util.misc import flat_iteration


def _ref_group_by_targets(sl):
    groups = []
    seen = set()
    for order, stmt in enumerate(flat_iteration(sl)):
        targets = set(list_targets(stmt))
        group = [(order, stmt)]
        disjoint = targets.isdisjoint(seen)
        seen |= targets
        if not disjoint:
            groups, old_groups = [], groups
            for old_targets, old_group in old_groups:
                if targets.isdisjoint(old_targets):
                    groups.append((old_targets, old_group))
                else:
                    targets |= old_targets
                    group += old_group
        groups.append((targets, group))
    return [(targets, [s for _, s in sorted(stmts, key=lambda x: x[0])])
            for targets, stmts in groups]


class ElabOptimizationCase(unittest.TestCase):
    def _assert_groups_equal(self, sl):
        ref = _ref_group_by_targets(sl)
        got = group_by_targets(sl)
        self.assertEqual(len(got), len(ref))
        for (gt, gs), (rt, rs) in zip(got, ref):
            self.assertEqual(gt, rt)
            self.assertEqual(len(gs), len(rs))
            for s1, s2 in zip(gs, rs):
                self.assertIs(s1, s2)

    def test_group_by_targets_bridge_and_random(self):
        a, b, c, d, src = [Signal(4) for _ in range(5)]
        # Multi-root bridge merge where earlier group has multiple statements
        sl = [
            a.eq(src),
            b.eq(src + 1),
            a.eq(src + 2),
            Cat(a, b).eq(0),
            c.eq(1),
            If(src[0], d.eq(2)).Else(Cat(c, a).eq(3)),
        ]
        self._assert_groups_equal(sl)

        rng = random.Random(42)
        sigs = [Signal(8) for _ in range(18)]
        for _ in range(25):
            stmts = []
            for _ in range(60):
                k = rng.randrange(4)
                if k == 0:
                    t = rng.choice(sigs)
                    stmts.append(t.eq(1))
                elif k == 1:
                    t1, t2 = rng.sample(sigs, 2)
                    stmts.append(Cat(t1, t2).eq(2))
                elif k == 2:
                    t1, t2 = rng.sample(sigs, 2)
                    stmts.append(If(sigs[0][0], t1[:4].eq(3)).Else(t2.eq(4)))
                else:
                    t1, t2 = rng.sample(sigs, 2)
                    stmts.append(Case(sigs[0][:2], {0: t1.eq(5), "default": t2.eq(6)}))
            self._assert_groups_equal(stmts)

    def test_visitor_vs_transformer_method_cache_isolation(self):
        seen_visitor = []
        seen_transformer = []

        class V(NodeVisitor):
            def visit_Part(self, node):
                seen_visitor.append("Part")

            def visit_unknown(self, node):
                seen_visitor.append("unknown")

        class T(NodeTransformer):
            def visit_Part(self, node):
                seen_transformer.append("Part")
                return super().visit_Part(node)

        s = Signal(8)
        off = Signal(2)
        p = _Part(s, off, 2)

        V().visit(p)
        res = T().visit(p)
        # Historical contract: NodeVisitor routes _Part to visit_unknown,
        # whereas NodeTransformer routes _Part to visit_Part.
        self.assertEqual(seen_visitor, ["unknown"])
        self.assertEqual(seen_transformer, ["Part"])
        self.assertIs(res, p)

    def test_transformer_and_lowerer_copy_on_write(self):
        a, b, c = Signal(8), Signal(8), Signal(8)
        u_op = ~a
        b_op = a + b
        m_op = Mux(a[0], b, c)
        assign = c.eq(b_op + u_op + m_op)
        stmts = [assign, a.eq(1)]

        t = NodeTransformer()
        self.assertIs(t.visit(stmts), stmts)
        self.assertIs(t.visit(assign), assign)

        low = _Lowerer()
        self.assertIs(low.visit(stmts), stmts)
        self.assertIs(low.visit(assign), assign)

    def test_nested_lhs_array_proxy_lowering(self):
        s0 = Signal(4)
        s1 = Signal(4)
        s2 = Signal(4)
        s3 = Signal(4)
        sel0 = Signal()
        sel1 = Signal()
        src = Signal(4)
        nested = Array([Array([s0, s1])[sel0], Array([s2, s3])[sel0]])
        m = Module()
        m.sync += nested[sel1].eq(src)
        out = verilog.convert(m, ios={s0, s1, s2, s3, sel0, sel1, src})
        self.assertIn("case (sel1)", out.main_source)
        self.assertIn("case (sel0)", out.main_source)

    def test_lowered_proxy_backtrace_names_unsplit_in_operators_and_statements(self):
        a = Signal(8)
        b = Signal(8)
        c = Signal(8)
        out1 = Signal(8)
        out2 = Signal(8)
        f = Module()
        # Two complex slices inside a binary operator + multiple statements
        f.comb += [
            out1.eq((a + b)[:4] + (b + c)[:4]),
            out2.eq((a ^ c)[:4]),
        ]
        frag = lower_complex_slices(f.get_fragment())
        ns = build_namespace(set(verilog.list_signals(frag)))
        proxy_names = sorted(
            ns.get_name(s) for s in ns.pnd if s not in {a, b, c, out1, out2}
        )
        self.assertEqual(proxy_names, ["slice_proxy0", "slice_proxy1", "slice_proxy2"])

    def test_signal_reset_property_and_fast_len(self):
        s = Signal(8, reset=3)
        self.assertIsInstance(s.reset, Constant)
        self.assertEqual(s.reset.value, 3)
        s.reset = 7
        self.assertIsInstance(s.reset, Constant)
        self.assertEqual(s.reset.value, 7)

        c = Constant(-2, (5, True))
        sl = s[2:6]
        pt = _Part(s, Signal(2), 3)
        self.assertEqual(len(s), 8)
        self.assertEqual(len(c), 5)
        self.assertEqual(len(sl), 4)
        self.assertEqual(len(pt), 3)
        self.assertEqual(len(Cat(sl, pt)), 7)

    def test_namespace_clock_and_reset_signal_lookup(self):
        cd_sync = ClockDomain("sync")
        cd_nr = ClockDomain("no_rst", reset_less=True)
        ns = build_namespace({cd_sync.clk, cd_sync.rst, cd_nr.clk})
        ns.clock_domains = {"sync": cd_sync, "no_rst": cd_nr}

        self.assertEqual(ns.get_name(ClockSignal("sync")), "sync_clk")
        self.assertEqual(ns.get_name(ResetSignal("sync")), "sync_rst")
        # Second lookup hits cache cleanly
        self.assertEqual(ns.get_name(ClockSignal("sync")), "sync_clk")
        with self.assertRaises(ValueError):
            ns.get_name(ResetSignal("no_rst"))

    def test_cold_import_order(self):
        for mod in ("migen.fhdl.bitcontainer", "migen.fhdl.structure"):
            proc = subprocess.run(
                [sys.executable, "-c", f"import {mod}; from migen import Signal; assert len(Signal(4)) == 4"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
