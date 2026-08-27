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
    # {exact node type: method name}; None entries mean the node is
    # dispatched dynamically (list/tuple/dict/unknown). Subclasses of
    # registered types resolve to their base's handler via the MRO.
    _dispatch_table = _visitor_dispatch
    _resolved = {}

    def _resolve(self, cls):
        for k in cls.__mro__:
            try:
                return self._dispatch_table[k]
            except KeyError:
                pass
        return None

    def visit(self, node):
        cls = node.__class__
        try:
            method_name = self._resolved[cls]
        except KeyError:
            method_name = self._resolved[cls] = self._resolve(cls)
        if method_name is not None:
            return getattr(self, method_name)(node)
        if isinstance(node, (list, tuple)):
            return self.visit_statements(node)
        elif isinstance(node, dict):
            return self.visit_clock_domains(node)
        else:
            return self.visit_unknown(node)

    def visit_Constant(self, node):
        pass

    def visit_Signal(self, node):
        pass

    def visit_ClockSignal(self, node):
        pass

    def visit_ResetSignal(self, node):
        pass

    def visit_Operator(self, node):
        for o in node.operands:
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
    # NB: separate resolution cache - the two dispatch tables differ
    # (e.g. _Part)
    _resolved = {}

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
            return [self.visit(statement) for statement in node]
        new_node = [self.visit(statement) for statement in node]
        for old, new in zip(node, new_node):
            if old is not new:
                return new_node
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
