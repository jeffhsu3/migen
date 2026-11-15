from copy import copy
from operator import itemgetter

from migen.fhdl.structure import *
from migen.fhdl.structure import (_Operator, _Slice, _Part, _Assign, _ArrayProxy,
                                  _Fragment)


def _make_dispatch(classes):
    return {cls: "visit_" + name for cls, name in classes.items()}


_common_classes = {
    Constant: "Constant",
    Signal: "Signal",
    ClockSignal: "ClockSignal",
    ResetSignal: "ResetSignal",
    _Operator: "Operator",
    _Slice: "Slice",
    Cat: "Cat",
    Replicate: "Replicate",
    _Assign: "Assign",
    If: "If",
    Case: "Case",
    _Fragment: "Fragment",
    _ArrayProxy: "ArrayProxy",
}
# NB: NodeVisitor deliberately does not dispatch _Part (historical
# behaviour: it falls through to visit_unknown)
_visitor_dispatch = _make_dispatch(_common_classes)
_transformer_classes = dict(_common_classes)
_transformer_classes[_Part] = "Part"
_transformer_dispatch = _make_dispatch(_transformer_classes)


class NodeVisitor:
    # {exact node type: unbound handler}; populated lazily per visitor class.
    # Subclasses of registered types resolve to their base's handler via MRO.
    _dispatch_table = _visitor_dispatch
    _method_cache = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._method_cache = {}

    def _resolve_method(self, cls):
        vcls = self.__class__
        for k in cls.__mro__:
            method_name = self._dispatch_table.get(k)
            if method_name is not None:
                return getattr(vcls, method_name)
        if issubclass(cls, (list, tuple)):
            return vcls.visit_statements
        if issubclass(cls, dict):
            return vcls.visit_clock_domains
        return vcls.visit_unknown

    def visit(self, node):
        cls = node.__class__
        try:
            fn = self._method_cache[cls]
        except KeyError:
            fn = self._method_cache[cls] = self._resolve_method(cls)
        return fn(self, node)

    def visit_Constant(self, node):
        pass

    def visit_Signal(self, node):
        pass

    def visit_ClockSignal(self, node):
        pass

    def visit_ResetSignal(self, node):
        pass

    def visit_Operator(self, node):
        operands = node.operands
        n = len(operands)
        if n == 2:
            self.visit(operands[0])
            self.visit(operands[1])
        elif n == 1:
            self.visit(operands[0])
        else:
            for o in operands:
                self.visit(o)

    def visit_Slice(self, node):
        self.visit(node.value)

    def visit_Part(self, node):
        self.visit(node.value)
        self.visit(node.offset)

    def visit_Cat(self, node):
        for e in node.l:
            self.visit(e)

    def visit_Replicate(self, node):
        self.visit(node.v)

    def visit_Assign(self, node):
        self.visit(node.l)
        self.visit(node.r)

    def visit_If(self, node):
        self.visit(node.cond)
        self.visit(node.t)
        self.visit(node.f)

    def visit_Case(self, node):
        self.visit(node.test)
        for v, statements in sorted(node.cases.items(),
                                    key=lambda x: -1 if isinstance(x[0], str) and x[0] == "default" else x[0].duid):
            self.visit(statements)

    def visit_Fragment(self, node):
        self.visit(node.comb)
        self.visit(node.sync)

    def visit_statements(self, node):
        for statement in node:
            self.visit(statement)

    def visit_clock_domains(self, node):
        for clockname, statements in sorted(node.items(), key=itemgetter(0)):
            self.visit(statements)

    def visit_ArrayProxy(self, node):
        for choice in node.choices:
            self.visit(choice)
        self.visit(node.key)

    def visit_unknown(self, node):
        pass


# Default methods always copy the node, except for:
# - Signals, ClockSignals and ResetSignals
# - Unknown objects
# - All fragment fields except comb and sync
# In those cases, the original node is returned unchanged.
#
# As an optimization, composite nodes whose children are all unchanged
# are returned as-is instead of being rebuilt.
class NodeTransformer(NodeVisitor):
    _dispatch_table = _transformer_dispatch

    def visit_Constant(self, node):
        return node

    def visit_Signal(self, node):
        return node

    def visit_ClockSignal(self, node):
        return node

    def visit_ResetSignal(self, node):
        return node

    def visit_Operator(self, node):
        operands = node.operands
        n = len(operands)
        if n == 2:
            o0, o1 = operands
            new_operands = self.visit(o0)
            n0 = new_operands
            new_operands = self.visit(o1)
            if n0 is o0 and new_operands is o1:
                return node
            return _Operator(node.op, [n0, new_operands])
        if n == 1:
            o0 = operands[0]
            new_operands = self.visit(o0)
            if new_operands is o0:
                return node
            return _Operator(node.op, [new_operands])
        new_operands = [self.visit(o) for o in operands]
        for old, new in zip(operands, new_operands):
            if old is not new:
                return _Operator(node.op, new_operands)
        return node

    def visit_Slice(self, node):
        value = self.visit(node.value)
        if value is node.value:
            return node
        return _Slice(value, node.start, node.stop)

    def visit_Part(self, node):
        value = self.visit(node.value)
        offset = self.visit(node.offset)
        if value is node.value and offset is node.offset:
            return node
        return _Part(value, offset, node.width)

    def visit_Cat(self, node):
        l = node.l
        new_l = [self.visit(e) for e in l]
        for old, new in zip(l, new_l):
            if old is not new:
                return Cat(*new_l)
        return node

    def visit_Replicate(self, node):
        v = self.visit(node.v)
        if v is node.v:
            return node
        return Replicate(v, node.n)

    def visit_Assign(self, node):
        l = self.visit(node.l)
        r = self.visit(node.r)
        if l is node.l and r is node.r:
            return node
        return _Assign(l, r)

    def visit_If(self, node):
        cond = self.visit(node.cond)
        t = self.visit(node.t)
        f = self.visit(node.f)
        if cond is node.cond and t is node.t and f is node.f:
            return node
        r = If(cond)
        r.t = t
        r.f = f
        return r

    def visit_Case(self, node):
        test = self.visit(node.test)
        new_cases = {}
        changed = test is not node.test
        for v, statements in sorted(node.cases.items(),
                                    key=lambda x: -1 if isinstance(x[0], str) and x[0] == "default" else x[0].duid):
            new_statements = self.visit(statements)
            changed |= new_statements is not statements
            new_cases[v] = new_statements
        if not changed:
            return node
        return Case(test, new_cases)

    def visit_Fragment(self, node):
        comb = self.visit(node.comb)
        sync = self.visit(node.sync)
        if comb is node.comb and sync is node.sync:
            return node
        r = copy(node)
        r.comb = comb
        r.sync = sync
        return r

    # NOTE: this will always return a list, even if node is a tuple
    def visit_statements(self, node):
        if type(node) is not list:
            new_node = [self.visit(statement) for statement in node]
            return new_node
        if not node:
            return node
        # Assign self.visit() results to `new_node` so tracer.get_var_name
        # sees the same local name across all statements when lowerers create
        # proxy Signals inside visit().
        for i, statement in enumerate(node):
            new_node = self.visit(statement)
            if new_node is not statement:
                res = node[:i]
                res.append(new_node)
                for rest in node[i + 1:]:
                    new_node = self.visit(rest)
                    res.append(new_node)
                return res
        return node

    def visit_clock_domains(self, node):
        new_dict = {}
        changed = False
        for clockname, statements in sorted(node.items(),
                                            key=itemgetter(0)):
            new_statements = self.visit(statements)
            changed |= new_statements is not statements
            new_dict[clockname] = new_statements
        return node if not changed else new_dict

    def visit_ArrayProxy(self, node):
        choices = node.choices
        new_choices = [self.visit(choice) for choice in choices]
        key = self.visit(node.key)
        if key is node.key and all(old is new
                                   for old, new in zip(choices, new_choices)):
            return node
        return _ArrayProxy(new_choices, key)

    def visit_unknown(self, node):
        return node
