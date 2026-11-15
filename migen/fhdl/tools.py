from copy import copy
from migen.fhdl.structure import *
from migen.fhdl.structure import _Slice, _Part, _Assign, _Fragment
from migen.fhdl.visit import NodeVisitor, NodeTransformer
from migen.fhdl.bitcontainer import value_bits_sign
from migen.util.misc import flat_iteration


class _SignalLister(NodeVisitor):
    def __init__(self):
        self.output_list = set()

    def visit_Signal(self, node):
        self.output_list.add(node)


class _TargetLister(NodeVisitor):
    def __init__(self):
        self.output_list = set()
        self.target_context = False

    def visit_Signal(self, node):
        if self.target_context:
            self.output_list.add(node)

    def visit_Assign(self, node):
        self.target_context = True
        self.visit(node.l)
        self.target_context = False

    def visit_ArrayProxy(self, node):
        for choice in node.choices:
            self.visit(choice)


class _InputLister(NodeVisitor):
    def __init__(self):
        self.output_list = set()

    def visit_Signal(self, node):
        self.output_list.add(node)

    def visit_Assign(self, node):
        self.visit(node.r)


def list_signals(node):
    lister = _SignalLister()
    lister.visit(node)
    return lister.output_list


def list_targets(node):
    lister = _TargetLister()
    lister.visit(node)
    return lister.output_list


def list_inputs(node):
    lister = _InputLister()
    lister.visit(node)
    return lister.output_list


def group_by_targets(sl):
    lister = _TargetLister()
    group_targets = []
    group_stmts = []
    group_orders = []
    needs_sort = []
    parent = []
    target_owner = {}

    for gid, stmt in enumerate(flat_iteration(sl)):
        if type(stmt) is _Assign and type(stmt.l) is Signal:
            targets = {stmt.l}
        else:
            targets = set()
            lister.output_list = targets
            lister.visit(stmt)

        roots = None
        for t in targets:
            owner = target_owner.get(t)
            if owner is not None:
                while parent[owner] != owner:
                    parent[owner] = parent[parent[owner]]
                    owner = parent[owner]
                if roots is None:
                    roots = {owner}
                else:
                    roots.add(owner)

        if roots is None:
            for t in targets:
                target_owner[t] = gid
            parent.append(gid)
            group_targets.append(targets)
            group_stmts.append([stmt])
            group_orders.append(None)
            needs_sort.append(False)
        elif len(roots) == 1:
            r = next(iter(roots))
            merged_targets = group_targets[r]
            merged_targets |= targets
            for t in targets:
                target_owner[t] = gid
            merged_stmts = group_stmts[r]
            merged_stmts.append(stmt)
            orders = group_orders[r]
            if orders is None:
                orders = [r, gid]
            else:
                orders.append(gid)
            group_targets[r] = None
            group_stmts[r] = None
            group_orders[r] = None
            parent[r] = gid
            parent.append(gid)
            group_targets.append(merged_targets)
            group_stmts.append(merged_stmts)
            group_orders.append(orders)
            needs_sort.append(needs_sort[r])
        else:
            sorted_roots = sorted(roots)
            r0 = sorted_roots[0]
            merged_targets = group_targets[r0]
            merged_stmts = group_stmts[r0]
            orders = group_orders[r0]
            if orders is None:
                orders = [r0]
            group_targets[r0] = None
            group_stmts[r0] = None
            group_orders[r0] = None
            parent[r0] = gid
            for r in sorted_roots[1:]:
                merged_targets |= group_targets[r]
                merged_stmts.extend(group_stmts[r])
                ro = group_orders[r]
                if ro is None:
                    orders.append(r)
                else:
                    orders.extend(ro)
                group_targets[r] = None
                group_stmts[r] = None
                group_orders[r] = None
                parent[r] = gid
            merged_targets |= targets
            for t in targets:
                target_owner[t] = gid
            merged_stmts.append(stmt)
            orders.append(gid)
            parent.append(gid)
            group_targets.append(merged_targets)
            group_stmts.append(merged_stmts)
            group_orders.append(orders)
            needs_sort.append(True)

    result = []
    for targets, stmts, orders, ns in zip(group_targets, group_stmts, group_orders, needs_sort):
        if stmts is None:
            continue
        if ns:
            stmts = [s for _, s in sorted(zip(orders, stmts), key=lambda x: x[0])]
        result.append((targets, stmts))
    return result


def list_special_ios(f, ins, outs, inouts):
    r = set()
    for special in f.specials:
        r |= special.list_ios(ins, outs, inouts)
    return r


class _ClockDomainLister(NodeVisitor):
    def __init__(self):
        self.clock_domains = set()

    def visit_ClockSignal(self, node):
        self.clock_domains.add(node.cd)

    def visit_ResetSignal(self, node):
        self.clock_domains.add(node.cd)

    def visit_clock_domains(self, node):
        for clockname, statements in node.items():
            self.clock_domains.add(clockname)
            self.visit(statements)


def list_clock_domains_expr(f):
    cdl = _ClockDomainLister()
    cdl.visit(f)
    return cdl.clock_domains


def list_clock_domains(f):
    r = list_clock_domains_expr(f)
    for special in f.specials:
        r |= special.list_clock_domains()
    for cd in f.clock_domains:
        r.add(cd.name)
    return r


def is_variable(node):
    if isinstance(node, Signal):
        return node.variable
    elif isinstance(node, _Slice):
        return is_variable(node.value)
    elif isinstance(node, _Part):
        if is_variable(node.offset) != is_variable(node.value):
            raise TypeError
        return is_variable(node.value)
    elif isinstance(node, Cat):
        arevars = list(map(is_variable, node.l))
        r = arevars[0]
        for x in arevars:
            if x != r:
                raise TypeError
        return r
    else:
        raise TypeError


def generate_reset(rst, sl):
    targets = list_targets(sl)
    return [t.eq(t.reset) for t in sorted(targets, key=lambda x: x.duid)
            if not t.reset_less]


def insert_reset(rst, sl):
    return sl + [If(rst, *generate_reset(rst, sl))]


def insert_resets(f):
    newsync = dict()
    for k, v in f.sync.items():
        if f.clock_domains[k].rst is not None:
            newsync[k] = insert_reset(ResetSignal(k), v)
        else:
            newsync[k] = v
    f.sync = newsync


class _Lowerer(NodeTransformer):
    def __init__(self):
        self.target_context = False
        self.extra_stmts = []
        self.comb = []

    def visit_Assign(self, node):
        old_target_context = self.target_context
        old_extra_stmts = self.extra_stmts
        if old_extra_stmts:
            self.extra_stmts = []

        self.target_context = True
        lhs = self.visit(node.l)
        self.target_context = False
        rhs = self.visit(node.r)
        extra = self.extra_stmts
        self.target_context = old_target_context
        if extra:
            self.extra_stmts = old_extra_stmts if old_extra_stmts is not extra else []
            return [_Assign(lhs, rhs)] + extra
        if old_extra_stmts:
            self.extra_stmts = old_extra_stmts
        if lhs is node.l and rhs is node.r:
            return node
        return _Assign(lhs, rhs)


# Basics are FHDL structure elements that back-ends are not required to support
# but can be expressed in terms of other elements (lowered) before conversion.
class _BasicLowerer(_Lowerer):
    def __init__(self, clock_domains):
        self.clock_domains = clock_domains
        _Lowerer.__init__(self)

    def visit_ArrayProxy(self, node):
        # TODO: rewrite without variables
        array_muxed = Signal(value_bits_sign(node), variable=True)
        # The index is read whatever context the proxy is in: an ArrayProxy
        # nested in the key of an assignment target must be lowered as a
        # read, not as a target of its own.
        target_context = self.target_context
        self.target_context = False
        k = self.visit(node.key)
        self.target_context = target_context
        if self.target_context:
            cases = {}
            for n, choice in enumerate(node.choices):
                cases[n] = [self.visit_Assign(_Assign(choice, array_muxed))]
            self.extra_stmts.append(Case(k, cases).makedefault())
        else:
            cases = dict((n, _Assign(array_muxed, self.visit(choice)))
                for n, choice in enumerate(node.choices))
            self.comb.append(Case(k, cases).makedefault())
        return array_muxed

    def visit_ClockSignal(self, node):
        return self.clock_domains[node.cd].clk

    def visit_ResetSignal(self, node):
        rst = self.clock_domains[node.cd].rst
        if rst is None:
            if node.allow_reset_less:
                return 0
            else:
                raise ValueError("Attempted to get reset signal of resetless"
                                 " domain '{}'".format(node.cd))
        else:
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
    orig_comb = f.comb
    f = l.visit(f)
    if l.comb:
        if f.comb is orig_comb:
            f = copy(f)
            f.comb = f.comb + l.comb
        else:
            f.comb += l.comb

    if f.specials:
        for special in sorted(f.specials, key=lambda s: s.duid):
            for obj, attr, direction in special.iter_expressions():
                if direction != SPECIAL_INOUT:
                    # inouts are only supported by Migen when connected directly to top-level
                    # in this case, they are Signal and never need lowering
                    l.comb = []
                    l.target_context = direction != SPECIAL_INPUT
                    l.extra_stmts = []
                    expr = getattr(obj, attr)
                    expr = l.visit(expr)
                    setattr(obj, attr, expr)
                    if l.comb or l.extra_stmts:
                        if f.comb is orig_comb:
                            f = copy(f)
                            f.comb = f.comb + l.comb + l.extra_stmts
                        else:
                            f.comb += l.comb + l.extra_stmts

    return f


def lower_basics(f):
    return _apply_lowerer(_BasicLowerer(f.clock_domains), f)


def lower_complex_slices(f):
    return _apply_lowerer(_ComplexSliceLowerer(), f)

def lower_complex_parts(f):
    return _apply_lowerer(_ComplexPartLowerer(), f)

class _ClockDomainRenamer(NodeVisitor):
    def __init__(self, old, new):
        self.old = old
        self.new = new

    def visit_ClockSignal(self, node):
        if node.cd == self.old:
            node.cd = self.new

    def visit_ResetSignal(self, node):
        if node.cd == self.old:
            node.cd = self.new


def rename_clock_domain_expr(f, old, new):
    cdr = _ClockDomainRenamer(old, new)
    cdr.visit(f)


def rename_clock_domain(f, old, new):
    rename_clock_domain_expr(f, old, new)
    if new != old:
        if old in f.sync:
            if new in f.sync:
                f.sync[new].extend(f.sync[old])
            else:
                f.sync[new] = f.sync[old]
            del f.sync[old]
    for special in f.specials:
        special.rename_clock_domain(old, new)
    try:
        cd = f.clock_domains[old]
    except KeyError:
        pass
    else:
        cd.rename(new)


def call_special_classmethod(overrides, obj, method, *args, **kwargs):
    cl = obj.__class__
    if cl in overrides:
        cl = overrides[cl]
    if hasattr(cl, method):
        return getattr(cl, method)(obj, *args, **kwargs)
    else:
        return None


def _lower_specials_step(overrides, specials):
    f = _Fragment()
    lowered_specials = set()
    for special in sorted(specials, key=lambda x: x.duid):
        impl = call_special_classmethod(overrides, special, "lower")
        if impl is not None:
            f += impl.get_fragment()
            lowered_specials.add(special)
    return f, lowered_specials


def lower_specials(overrides, f):
    if not f.specials:
        return f, set()
    lowered_specials = set()
    while True:
        fs, lowered_specials_step = _lower_specials_step(overrides, f.specials)
        f += fs
        if lowered_specials_step:
            lowered_specials |= lowered_specials_step
            f.specials -= lowered_specials_step
        else:
            break
    return f, lowered_specials
