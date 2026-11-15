from migen.fhdl.structure import *


class _Node:
    __slots__ = ("signal_count", "numbers", "use_name", "use_number",
                 "children", "_sorted_numbers", "_number_index")

    def __init__(self):
        self.signal_count = 0
        self.numbers = set()
        self.use_name = False
        self.use_number = False
        self.children = {}
        self._sorted_numbers = None
        self._number_index = None

    def sorted_numbers(self):
        if self._sorted_numbers is None:
            self._sorted_numbers = sorted(self.numbers)
        return self._sorted_numbers


def _display_tree(filename, tree):
    from migen.util.treeviz import RenderNode

    def _to_render_node(name, node):
        children = [_to_render_node(k, v) for k, v in node.children.items()]
        if node.use_name:
            if node.use_number:
                color = (0.5, 0.9, 0.8)
            else:
                color = (0.8, 0.5, 0.9)
        else:
            if node.use_number:
                color = (0.9, 0.8, 0.5)
            else:
                color = (0.8, 0.8, 0.8)
        label = "{0}\n{1} signals\n{2}".format(name, node.signal_count, node.numbers)
        return RenderNode(label, children, color=color)

    top = _to_render_node("top", tree)
    top.to_svg(filename)


def _build_tree(signals, basic_tree=None):
    root = _Node()
    if basic_tree is None:
        for signal in signals:
            current = root
            current.signal_count += 1
            for name, number in signal.backtrace:
                children = current.children
                child = children.get(name)
                if child is None:
                    child = _Node()
                    children[name] = child
                current = child
                current.numbers.add(number)
                current.signal_count += 1
    else:
        for signal in signals:
            current_b = basic_tree
            current = root
            current.signal_count += 1
            for name, number in signal.backtrace:
                current_b = current_b.children[name]
                use_number = current_b.use_number
                key = (name, number) if use_number else name
                children = current.children
                child = children.get(key)
                if child is None:
                    child = _Node()
                    if use_number:
                        idxmap = current_b._number_index
                        if idxmap is None:
                            idxmap = current_b._number_index = {
                                n: i for i, n in enumerate(current_b.sorted_numbers())}
                        child._number_index = idxmap
                    children[key] = child
                current = child
                if _debug:
                    current.numbers.add(number)
                current.signal_count += 1
    return root


def _set_use_name(node, node_name=""):
    children = node.children
    n_children = len(children)
    if n_children == 0:
        if node.signal_count > 0:
            node.use_name = True
            return {(node_name, )}
        return set()
    if n_children == 1:
        c_prefix, child = next(iter(children.items()))
        c_names = _set_use_name(child, c_prefix)
        if child.use_name:
            r = {(c_prefix, ) + c_name for c_name in c_names}
        else:
            r = c_names
        if node.signal_count > child.signal_count:
            node.use_name = True
            r.add((node_name, ))
        return r

    cnames = [(k, _set_use_name(v, k)) for k, v in children.items()]
    # A child needs its name qualified if its subtree shares any leaf
    # name with another child. Finding shared leaves via a single map
    # is linear in total leaf count instead of quadratic in children.
    owners = {}
    for prefix, names in cnames:
        for name in names:
            lst = owners.get(name)
            if lst is None:
                owners[name] = [prefix]
            else:
                lst.append(prefix)
    for prefixes in owners.values():
        if len(prefixes) > 1:
            for prefix in prefixes:
                children[prefix].use_name = True
    r = set()
    child_sig_sum = 0
    for c_prefix, c_names in cnames:
        child = children[c_prefix]
        child_sig_sum += child.signal_count
        if child.use_name:
            for c_name in c_names:
                r.add((c_prefix, ) + c_name)
        else:
            r |= c_names

    if node.signal_count > child_sig_sum:
        node.use_name = True
        r.add((node_name, ))

    return r


def _name_signal(tree, signal):
    elements = []
    treepos = tree
    for step_name, step_n in signal.backtrace:
        children = treepos.children
        child = children.get(step_name)
        if child is not None:
            treepos = child
            if treepos.use_name:
                elements.append(step_name)
        else:
            treepos = children[(step_name, step_n)]
            if treepos.use_name:
                elements.append(step_name + str(treepos._number_index[step_n]))
    return "_".join(elements)


def _build_pnd_from_tree(tree, signals):
    return {signal: _name_signal(tree, signal) for signal in signals}


def _invert_pnd(pnd):
    inv_pnd = {}
    for k, v in pnd.items():
        lst = inv_pnd.get(v)
        if lst is None:
            inv_pnd[v] = [k]
        else:
            lst.append(k)
    return inv_pnd


def _list_conflicting_signals(pnd):
    inv_pnd = _invert_pnd(pnd)
    r = set()
    for k, v in inv_pnd.items():
        if len(v) > 1:
            r.update(v)
    return r


def _set_use_number(tree, signals):
    for signal in signals:
        current = tree
        for step_name, step_n in signal.backtrace:
            current = current.children[step_name]
            current.use_number = current.signal_count > len(current.numbers) and len(current.numbers) > 1

_debug = False


def _build_pnd_for_group(group_n, signals):
    basic_tree = _build_tree(signals)
    _set_use_name(basic_tree)
    if _debug:
        _display_tree("tree{0}_basic.svg".format(group_n), basic_tree)
    pnd = _build_pnd_from_tree(basic_tree, signals)

    # If there are conflicts, try splitting the tree by numbers
    # on paths taken by conflicting signals.
    conflicting_signals = _list_conflicting_signals(pnd)
    if conflicting_signals:
        _set_use_number(basic_tree, conflicting_signals)
        if _debug:
            print("namer: using split-by-number strategy (group {0})".format(group_n))
            _display_tree("tree{0}_marked.svg".format(group_n), basic_tree)
        numbered_tree = _build_tree(signals, basic_tree)
        _set_use_name(numbered_tree)
        if _debug:
            _display_tree("tree{0}_numbered.svg".format(group_n), numbered_tree)
        pnd = _build_pnd_from_tree(numbered_tree, signals)
    else:
        if _debug:
            print("namer: using basic strategy (group {0})".format(group_n))

    # ...then add number suffixes by DUID
    inv_pnd = _invert_pnd(pnd)
    duid_suffixed = False
    for name, signals in inv_pnd.items():
        if len(signals) > 1:
            duid_suffixed = True
            for n, signal in enumerate(sorted(signals, key=lambda x: x.duid)):
                pnd[signal] += str(n)
    if _debug and duid_suffixed:
        print("namer: using DUID suffixes (group {0})".format(group_n))

    return pnd


def _is_traced(signal):
    return getattr(signal, "_traced", True) or signal.name_override is None


def _build_signal_groups(signals):
    r = []
    for signal in signals:
        if not _is_traced(signal):
            continue
        # build chain of related signals
        related_list = []
        cur_signal = signal
        while cur_signal is not None:
            related_list.insert(0, cur_signal)
            cur_signal = cur_signal.related
        # add to groups
        for _ in range(len(related_list) - len(r)):
            r.append(set())
        for target_set, source_signal in zip(r, related_list):
            if _is_traced(source_signal):
                target_set.add(source_signal)
    # with the algorithm above and a list of all signals,
    # a signal appears in all groups of a lower number than its.
    # make signals appear only in their group of highest number.
    for s1, s2 in zip(r, r[1:]):
        s1 -= s2
    return r


def _build_pnd(signals, override_names=None):
    if override_names is None:
        override_names = {}
    groups = _build_signal_groups(signals)
    gpnds = [_build_pnd_for_group(n, gsignals) if gsignals else {}
             for n, gsignals in enumerate(groups)]

    pnd = dict()
    for gn, gpnd in enumerate(gpnds):
        for signal, name in gpnd.items():
            result = name
            cur_gn = gn
            cur_signal = signal
            while cur_signal.related is not None:
                cur_signal = cur_signal.related
                cur_gn -= 1
                if cur_signal in gpnds[cur_gn]:
                    parent_name = gpnds[cur_gn][cur_signal]
                else:
                    parent_name = override_names.get(cur_signal, cur_signal.name_override)
                result = parent_name + "_" + result
            pnd[signal] = result

    return pnd


def build_namespace(signals, reserved_keywords=set()):
    ns = Namespace({}, reserved_keywords)
    # register signals with name_override
    swno = {signal for signal in signals if signal.name_override is not None}
    override_names = {}
    for signal in sorted(swno, key=lambda x: x.duid):
        override_names[signal] = ns.get_name(signal)
    ns.pnd = _build_pnd(signals, override_names)
    return ns


class Namespace:
    def __init__(self, pnd, reserved_keywords=set()):
        self.counts = {k: 1 for k in reserved_keywords}
        self.sigs = {}
        self._names = {}
        self.pnd = pnd
        self.clock_domains = dict()

    def get_name(self, sig):
        if type(sig) is not Signal:
            if isinstance(sig, ClockSignal):
                sig = self.clock_domains[sig.cd].clk
            elif isinstance(sig, ResetSignal):
                rst = self.clock_domains[sig.cd].rst
                if rst is None:
                    raise ValueError("Attempted to obtain name of non-existent "
                                     "reset signal of domain "+sig.cd)
                sig = rst
        res = self._names.get(sig)
        if res is not None:
            return res

        if sig.name_override is not None:
            sig_name = sig.name_override
        else:
            sig_name = self.pnd[sig]
        n = self.sigs.get(sig)
        if n is None:
            n = self.counts.get(sig_name, 0)
            self.sigs[sig] = n
            self.counts[sig_name] = n + 1
        res = sig_name + "_" + str(n) if n else sig_name
        self._names[sig] = res
        return res
