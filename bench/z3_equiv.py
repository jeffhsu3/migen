"""Formal equivalence checking of Migen fragments using Z3.

Translates a lowered FHDL fragment into a symbolic transition system:

- every Signal becomes a Z3 BitVec sized by ``value_bits_sign``
- comb statements execute sequentially (blocking semantics) starting from
  reset defaults for their targets, mirroring both the Migen simulator and
  the Verilog backend's per-group defaults
- sync statements compute next-state values concurrently from
  end-of-cycle values (non-blocking semantics), for all clock domains at
  once
- input signals receive a fresh free BitVec each cycle

``fragments_equivalent`` unrolls both systems for N cycles with the *same*
symbolic inputs and asks the solver whether any observable signal
(registered state or combinational output) can ever differ.  ``unsat``
means the fragments are provably equivalent to depth N.

This guards elaboration-time optimizations: run the old and new pipeline
on clones of the same raw fragment and prove equivalence.
"""

import z3

from migen.fhdl.structure import (
    Signal, Constant, ClockSignal, ResetSignal,
    _Operator, _Slice, _Part, _Assign, _ArrayProxy)
from migen.fhdl.structure import If, Case, Cat, Replicate
from migen.fhdl.bitcontainer import value_bits_sign


class EquivalenceError(Exception):
    pass


def clone_fragment(f):
    """Deep-copy fragment statements, keeping Signal objects shared."""
    from copy import copy
    from migen.fhdl.visit import NodeTransformer
    from migen.fhdl.structure import _ClockDomainList

    class _Cloner(NodeTransformer):
        def visit_Fragment(self, node):
            r = copy(node)
            r.comb = self.visit(list(node.comb))
            r.sync = {cd: self.visit(list(stmts))
                      for cd, stmts in node.sync.items()}
            r.clock_domains = _ClockDomainList(node.clock_domains)
            return r

    return _Cloner().visit_Fragment(f)


def _ext(bv, width, signed):
    w = bv.size()
    if w == width:
        return bv
    if w > width:
        raise AssertionError("cannot shrink {} to {}".format(w, width))
    return z3.SignExt(width - w, bv) if signed else z3.ZeroExt(width - w, bv)


def _const_bv(c):
    v = c.value & ((1 << c.nbits) - 1)
    return z3.BitVecVal(v, c.nbits)


class _EnvSink:
    """Blocking-assignment sink: writes are visible to later reads."""
    def read(self, env, sig):
        return env[sig]

    def write(self, env, sig, val):
        env[sig] = val


class _ShadowSink:
    """Non-blocking-assignment sink: reads see pre-state, writes deferred."""
    def __init__(self, shadow):
        self.shadow = shadow

    def read(self, env, sig):
        return env[sig]

    def write(self, env, sig, val):
        self.shadow[sig] = val


class FragmentTranslator:
    def __init__(self, fragment):
        self.f = fragment
        self.env = {}
        self._regs_state = {}
        self.comb_targets = self._collect_comb_targets()
        self.regs = self._collect_regs()
        self.init_state()

    def init_state(self):
        self._regs_state = {s: _const_bv(s.reset) for s in self.regs}

    # ------------------------------------------------------------- analysis

    def _collect_comb_targets(self):
        targets = set()

        def walk(st):
            if isinstance(st, list):
                walk_list(st)
            elif isinstance(st, _Assign):
                targets.update(_lvalue_signals(st.l))
            elif isinstance(st, If):
                walk(st.t)
                walk(st.f)
            elif isinstance(st, Case):
                for v in st.cases.values():
                    walk(v)

        def walk_list(stmts):
            try:
                it = iter(stmts)
            except TypeError:
                walk(stmts)
                return
            for s in it:
                walk(s)

        walk_list(list(self.f.comb))
        return targets

    def _collect_regs(self):
        regs = set()

        def walk(st):
            if isinstance(st, list):
                walk_list(st)
            elif isinstance(st, _Assign):
                regs.update(s for s in _lvalue_signals(st.l)
                            if isinstance(s, Signal))
            elif isinstance(st, If):
                walk(st.t)
                walk(st.f)
            elif isinstance(st, Case):
                for v in st.cases.values():
                    walk(v)

        def walk_list(stmts):
            try:
                it = iter(stmts)
            except TypeError:
                walk(stmts)
                return
            for s in it:
                walk(s)

        for stmts in self.f.sync.values():
            walk_list(stmts)
        return regs

    # ------------------------------------------------------------ expressions

    def expr(self, node):
        if isinstance(node, Constant):
            return _const_bv(node)
        if isinstance(node, Signal):
            if node not in self.env:
                self.env[node] = self._regs_state.get(
                    node, _const_bv(node.reset))
            return self.env[node]
        if isinstance(node, (ClockSignal, ResetSignal)):
            raise EquivalenceError(
                "{} survived lowering; fragment must be fully lowered "
                "before translation".format(type(node).__name__))
        if isinstance(node, _Operator):
            return self._op(node)
        if isinstance(node, _Slice):
            return z3.Extract(node.stop - 1, node.start, self.expr(node.value))
        if isinstance(node, _Part):
            return self._part(node)
        if isinstance(node, Cat):
            return z3.Concat(*[self.expr(e) for e in reversed(node.l)])
        if isinstance(node, Replicate):
            v = self.expr(node.v)
            return z3.Concat(*([v] * node.n))
        if isinstance(node, _ArrayProxy):
            return self._array_proxy(node)
        raise EquivalenceError("unsupported expression node {!r}".format(node))

    def _op(self, node):
        op = node.op
        ops = [self.expr(o) for o in node.operands]
        signs = [getattr(o, "signed", False) for o in node.operands]
        if op == "~":
            return ~ops[0]
        if op == "-":
            return -ops[0]
        if op == "m":
            cond = ops[0] != 0
            width = max(ops[1].size(), ops[2].size())
            return z3.If(cond, _ext(ops[1], width, signs[1]),
                         _ext(ops[2], width, signs[2]))
        a, b = ops
        sa, sb = signs
        if op in ("<<<", ">>>"):
            if b.size() < a.size():
                b = z3.ZeroExt(a.size() - b.size(), b)
            elif b.size() > a.size():
                b = z3.Extract(a.size() - 1, 0, b)
            if op == "<<<":
                return a << b
            return a >> b if sa else z3.LShR(a, b)
        if op in ("==", "!=", "<", "<=", ">", ">="):
            width = max(a.size(), b.size())
            signed = sa or sb
            a2, b2 = _ext(a, width, signed), _ext(b, width, signed)
            fn = {
                "==": lambda x, y: x == y,
                "!=": lambda x, y: x != y,
                "<": (lambda x, y: x < y) if signed else z3.ULT,
                "<=": (lambda x, y: x <= y) if signed else z3.ULE,
                ">": (lambda x, y: x > y) if signed else z3.UGT,
                ">=": (lambda x, y: x >= y) if signed else z3.UGE,
            }[op]
            return z3.If(fn(a2, b2), z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))
        width = max(a.size(), b.size())
        a = _ext(a, width, sa)
        b = _ext(b, width, sb)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "&":
            return a & b
        if op == "|":
            return a | b
        if op == "^":
            return a ^ b
        if op == "/":
            return a / b if (sa or sb) else z3.udiv(a, b)
        if op == "%":
            return a % b if (sa or sb) else z3.urem(a, b)
        raise EquivalenceError("unsupported operator '{}'".format(op))

    def _part(self, node):
        v = self.expr(node.value)
        w = v.size()
        off = self.expr(node.offset)
        off = _ext(off, w, False)
        off = z3.URem(off, z3.BitVecVal(w, w))
        rotated = (v << off) | z3.LShR(v, w - off)
        if node.width == w:
            return rotated
        return z3.Extract(w - 1, w - node.width, rotated)

    def _array_proxy(self, node):
        choices = node.choices
        width = max(value_bits_sign(c)[0] for c in choices)
        key = self.expr(node.key)
        r = _ext(self.expr(choices[-1]), width, False)
        for i in range(len(choices) - 2, -1, -1):
            choice = _ext(self.expr(choices[i]), width, False)
            nbits = max(key.size(), 1)
            val = i & ((1 << nbits) - 1)
            cond = key == z3.BitVecVal(val, nbits) if i < (1 << nbits) \
                else z3.BoolVal(False)
            r = z3.If(cond, choice, r)
        return r

    # ------------------------------------------------------------- statements

    def exec_stmts(self, stmts, sink, guard=None):
        """Execute statements with blocking semantics.

        Reads come from ``self.env``; writes go through ``sink``.
        ``guard`` is None (always true) or a Z3 BoolRef condition.
        """
        if isinstance(stmts, (_Assign, If, Case)):
            stmts = [stmts]
        for st in stmts:
            g = guard
            if isinstance(st, list):
                self.exec_stmts(st, sink, g)
            elif isinstance(st, _Assign):
                if isinstance(st.l, _ArrayProxy):
                    # dst[key].eq(v) == conditional writes to each choice
                    key = self.expr(st.l.key)
                    ksz = max(1, key.size())
                    choices = st.l.choices
                    for i, choice in enumerate(choices[:-1]):
                        cond = key == z3.BitVecVal(i, ksz)
                        g2 = cond if g is None else z3.And(g, cond)
                        self.exec_stmts([_Assign(choice, st.r)], sink, g2)
                    gg = z3.UGT(key, z3.BitVecVal(len(choices) - 2, ksz)) \
                        if len(choices) > 1 else z3.BoolVal(True)
                    g2 = gg if g is None else z3.And(g, gg)
                    self.exec_stmts([_Assign(choices[-1], st.r)], sink, g2)
                else:
                    val = self._fit_assign_value(st.r, st.l)
                    for sig, updater in _assign_effects(st.l, val):
                        old = sink.read(self.env, sig)
                        new = updater(old)
                        if g is not None:
                            new = z3.If(g, new, old)
                        sink.write(self.env, sig, new)
            elif isinstance(st, If):
                c = self.expr(st.cond)
                self.exec_stmts(st.t, sink,
                                c != 0 if g is None else z3.And(g, c != 0))
                self.exec_stmts(st.f, sink,
                                c == 0 if g is None else z3.And(g, c == 0))
            elif isinstance(st, Case):
                t = self.expr(st.test)
                remaining = None
                for k, sub in sorted(st.cases.items(),
                                     key=lambda kv: isinstance(kv[0], str)):
                    if isinstance(k, str):   # default case
                        gg = remaining
                    else:
                        kb = _const_bv(k)
                        width = max(t.size(), kb.size())
                        eq = (_ext(t, width, False) == _ext(kb, width, False))
                        gg = eq if remaining is None else z3.And(remaining, eq)
                        not_eq = z3.Not(eq) if remaining is None \
                            else z3.And(remaining, z3.Not(eq))
                        remaining = not_eq
                    if gg is None:
                        self.exec_stmts(sub, sink, None)
                    else:
                        self.exec_stmts(sub, sink, gg)
            else:
                raise EquivalenceError("unsupported statement {!r}"
                                       .format(st))

    def _fit_assign_value(self, rhs_node, lhs_node):
        v = self.expr(rhs_node)
        if isinstance(lhs_node, Signal):
            n = lhs_node.nbits
        elif isinstance(lhs_node, _Slice):
            n = lhs_node.stop - lhs_node.start
        elif isinstance(lhs_node, _ArrayProxy):
            n = value_bits_sign(lhs_node)[0]
        elif _lvalue_signals(lhs_node):
            n = sum(value_bits_sign(e)[0]
                    for e in _cat_leaves(lhs_node)
                    if not isinstance(e, _Slice))
            n += sum(e.stop - e.start for e in _cat_leaves(lhs_node)
                     if isinstance(e, _Slice))
        else:
            n = v.size()
        if n <= 0:
            n = v.size()
        if v.size() >= n:
            return z3.Extract(n - 1, 0, v)
        return _ext(v, n, getattr(rhs_node, "signed", False))

    # ---------------------------------------------------------------- cycles

    def begin_cycle(self, inputs):
        """Set up environment for a new cycle.

        ``inputs``: dict Signal -> BitVec (fresh free vars, shared between
        the two systems being compared).
        """
        self.env = {}
        for s, bv in self._regs_state.items():
            self.env[s] = bv
        for s, bv in inputs.items():
            self.env[s] = bv
        # comb targets start from reset/default, like the simulator and the
        # Verilog backend do at the top of each always block
        for t in self.comb_targets:
            if t not in self.env:
                self.env[t] = _const_bv(t.reset)

    def eval_comb_and_sync(self):
        self.exec_stmts(list(self.f.comb), _EnvSink())
        nxt = {}
        shadow = _ShadowSink(nxt)
        for stmts in self.f.sync.values():
            self.exec_stmts(list(stmts), shadow)
        self._regs_state = {s: nxt.get(s, self.env[s]) for s in self.regs}


# ------------------------------------------------------------------ lvalues


def _cat_leaves(node):
    out = []

    def rec(n):
        if isinstance(n, Cat):
            for e in n.l:
                rec(e)
        else:
            out.append(n)
    rec(node)
    return out


def _lvalue_signals(node):
    if isinstance(node, Signal):
        return [node]
    if isinstance(node, (_Slice, _Part)):
        return _lvalue_signals(node.value)
    if isinstance(node, Cat):
        out = []
        for e in _cat_leaves(node):
            out.extend(_lvalue_signals(e))
        return out
    if isinstance(node, _ArrayProxy):
        out = []
        for c in node.choices:
            out.extend(_lvalue_signals(c))
        return out
    return []


def _assign_effects(lhs, val):
    """Yield (signal, updater); updater maps the old value to the new."""
    if isinstance(lhs, Signal):
        yield lhs, (lambda old, v=val: v)
    elif isinstance(lhs, _Slice):
        start, stop = lhs.start, lhs.stop
        underlying = lhs.value
        if not isinstance(underlying, Signal):
            raise EquivalenceError("slice lvalue of non-Signal {!r}"
                                   .format(underlying))
        w = underlying.nbits

        def upd(old, start=start, stop=stop, w=w, v=val):
            parts = []
            if w > stop:
                parts.append(z3.Extract(w - 1, stop, old))
            parts.append(v)
            if start > 0:
                parts.append(z3.Extract(start - 1, 0, old))
            return z3.Concat(*parts) if len(parts) > 1 else parts[0]

        yield underlying, upd
    elif isinstance(lhs, Cat):
        offset = 0
        total = sum(value_bits_sign(e)[0] for e in _cat_leaves(lhs))
        for leaf in _cat_leaves(lhs):
            n = value_bits_sign(leaf)[0]
            if val.size() > offset:
                piece = z3.Extract(min(offset + n, val.size()) - 1, offset,
                                   val)
            else:
                piece = z3.BitVecVal(0, min(n, val.size()) or 1)
            if piece.size() < n:
                piece = z3.ZeroExt(n - piece.size(), piece)
            yield from _assign_effects(leaf, piece)
            offset += n
    else:
        raise EquivalenceError("unsupported assignment target {!r}"
                               .format(lhs))


# ------------------------------------------------------------------- public


def collect_shared_signals(f1, f2):
    from migen.fhdl.tools import list_signals
    return list_signals(f1) & list_signals(f2)


def fragments_equivalent(f_ref, f_live, inputs, cycles=5, observe=None,
                         verbose=False):
    """Prove f_ref ~= f_live for `cycles` cycles given identical inputs.

    For each cycle we assert that some observed signal differs; if the
    solver returns ``unsat`` no such input sequence exists and the
    fragments are proven equivalent to depth `cycles`.

    Returns (equivalent, counterexample_model_or_None, stats).
    """
    tr_ref = FragmentTranslator(f_ref)
    tr_live = FragmentTranslator(f_live)

    if observe is None:
        observe = collect_shared_signals(f_ref, f_live) - set(inputs)
    observe = sorted(observe, key=lambda s: s.duid)
    if not observe:
        raise EquivalenceError("no observable signals to compare")

    solver = z3.Solver()
    for cyc in range(cycles):
        in_syms = {}
        for s in inputs:
            in_syms[s] = z3.BitVec("in_{}_cyc{}".format(s.duid, cyc),
                                   max(1, len(s)))
        tr_ref.begin_cycle(in_syms)
        tr_live.begin_cycle(in_syms)
        tr_ref.eval_comb_and_sync()
        tr_live.eval_comb_and_sync()
        diffs = []
        for s in observe:
            a = tr_ref.env.get(s)
            b = tr_live.env.get(s)
            if a is None or b is None:
                # missing on one side means the fragments genuinely differ
                diffs.append(z3.BoolVal(True))
                continue
            if a.size() != b.size():
                diffs.append(z3.BoolVal(True))
                continue
            diffs.append(a != b)
        solver.add(z3.Or(*diffs))

    check = solver.check()
    equivalent = check == z3.unsat
    model = None if equivalent else solver.model()
    stats = {"cycles": cycles, "observed": len(observe),
             "result": str(check)}
    if verbose:
        print(stats)
    return equivalent, model, stats
