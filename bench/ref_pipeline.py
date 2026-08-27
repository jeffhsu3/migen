"""Frozen reference implementation of the conversion pipeline.

This file vendors today's (pre-optimization) lowering logic so that,
as migen/fhdl/tools.py etc. get optimized, the Z3 equivalence tests can
prove that the live pipeline still produces hardware equivalent to this
reference on all benchmark designs.

DO NOT "optimize" anything here - correctness of the whole scheme relies
on this file staying semantically frozen.
"""

from migen.fhdl.structure import *
from migen.fhdl.structure import _Slice, _Part, _Assign
from migen.fhdl.visit import NodeTransformer
from migen.fhdl.bitcontainer import value_bits_sign


# ------------------------------------------------------------------ resets

def _generate_reset(rst, sl):
    from migen.fhdl.tools import _TargetLister
    lister = _TargetLister()
    lister.visit(sl)
    targets = lister.output_list
    return [t.eq(t.reset) for t in sorted(targets, key=lambda x: x.duid)
            if not t.reset_less]


def insert_resets(f):
    def insert_reset(rst, sl):
        return sl + [If(rst, *_generate_reset(rst, sl))]

    newsync = dict()
    for k, v in f.sync.items():
        if f.clock_domains[k].rst is not None:
            newsync[k] = insert_reset(ResetSignal(k), v)
        else:
            newsync[k] = v
    f.sync = newsync


# ---------------------------------------------------------------- lowerers

class _Lowerer(NodeTransformer):
    def __init__(self):
        self.target_context = False
        self.extra_stmts = []
        self.comb = []

    def visit_Assign(self, node):
        old_target_context, old_extra_stmts = \
            self.target_context, self.extra_stmts
        self.extra_stmts = []

        self.target_context = True
        lhs = self.visit(node.l)
        self.target_context = False
        rhs = self.visit(node.r)
        r = _Assign(lhs, rhs)
        if self.extra_stmts:
            r = [r] + self.extra_stmts

        self.target_context, self.extra_stmts = \
            old_target_context, old_extra_stmts
        return r


class _BasicLowerer(_Lowerer):
    def __init__(self, clock_domains):
        self.clock_domains = clock_domains
        _Lowerer.__init__(self)

    def visit_ArrayProxy(self, node):
        array_muxed = Signal(value_bits_sign(node), variable=True)
        if self.target_context:
            k = self.visit(node.key)
            cases = {}
            for n, choice in enumerate(node.choices):
                cases[n] = [self.visit_Assign(_Assign(choice, array_muxed))]
            self.extra_stmts.append(Case(k, cases).makedefault())
        else:
            cases = dict((n, _Assign(array_muxed, self.visit(choice)))
                         for n, choice in enumerate(node.choices))
            self.comb.append(Case(self.visit(node.key),
                                  cases).makedefault())
        return array_muxed

    def visit_ClockSignal(self, node):
        return self.clock_domains[node.cd].clk

    def visit_ResetSignal(self, node):
        rst = self.clock_domains[node.cd].rst
        if rst is None:
            if node.allow_reset_less:
                return 0
            raise ValueError("Attempted to get reset signal of resetless"
                             " domain '{}'".format(node.cd))
        return rst


class _ComplexSliceLowerer(_Lowerer):
    def visit_Slice(self, node):
        if not isinstance(node.value, Signal):
            slice_proxy = Signal(value_bits_sign(node.value))
            if self.target_context:
                a = _Assign(node.value, slice_proxy)
            else:
                a = _Assign(slice_proxy, node.value)
            self.comb.append(self.visit_Assign(a))
            node = _Slice(slice_proxy, node.start, node.stop)
        return NodeTransformer.visit_Slice(self, node)


class _ComplexPartLowerer(_Lowerer):
    def visit_Part(self, node):
        value_proxy = node.value
        offset_proxy = node.offset
        if not isinstance(node.value, Signal):
            value_proxy = Signal(value_bits_sign(node.value))
            if self.target_context:
                a = _Assign(node.value, value_proxy)
            else:
                a = _Assign(value_proxy, node.value)
            self.comb.append(self.visit_Assign(a))
        if not isinstance(node.offset, Signal):
            offset_proxy = Signal(value_bits_sign(node.offset))
            if self.target_context:
                a = _Assign(node.offset, offset_proxy)
            else:
                a = _Assign(offset_proxy, node.offset)
            self.comb.append(self.visit_Assign(a))
        node = _Part(value_proxy, offset_proxy, node.width)
        return NodeTransformer.visit_Part(self, node)


def _apply_lowerer(l, f):
    assert not f.specials, \
        "reference pipeline only supports fragments without specials"
    f = l.visit(f)
    f.comb += l.comb
    return f


def run_reference_pipeline(f):
    """Apply the full pre-optimization conversion pipeline to fragment f.

    Only supports fragments whose specials have already been lowered away
    (the Z3-checked designs use no Memory/other specials).
    """
    f = _apply_lowerer(_ComplexSliceLowerer(), f)
    insert_resets(f)
    f = _apply_lowerer(_BasicLowerer(f.clock_domains), f)
    f = _apply_lowerer(_BasicLowerer(f.clock_domains), f)
    return f
