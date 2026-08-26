"""Parameterized benchmark designs for elaboration-time measurements.

Each design factory returns a ``(module, inputs, outputs)`` tuple where
``inputs``/``outputs`` are lists of top-level Signals used by the
correctness harnesses (simulation traces and Z3 equivalence checks).
Designs are chosen to stress known elaboration hot spots:

- ``arith_tree``    deep operator trees, many Signal() creations (tracer)
- ``many_modules``  fragment merging from hundreds of submodules
- ``array_mux``     Array/Case lowering (_BasicLowerer)
- ``slice_part``    complex slice/part lowering
- ``mem_ports``     Memory specials (lowering + emission)
- ``fsm_chain``     genlib FSM state encoding + Case statements
"""

from collections import namedtuple

from migen import *
from migen.genlib.fsm import FSM


Design = namedtuple("Design", "name build inputs outputs")


class _ArithLeaf(Module):
    def __init__(self):
        self.a = Signal(16)
        self.b = Signal(16)
        self.o = Signal(17)
        self.r = Signal(17)
        acc = self.a + self.b
        for k in range(6):
            acc = acc + (self.a ^ C(k, 16)) - (self.b | C(k, 16))
        self.comb += self.o.eq(acc)
        self.sync += self.r.eq(acc)


def _build_arith_tree(n_leaves=384):
    m = Module()
    inputs, outputs = [], []
    sums = []
    for i in range(n_leaves):
        leaf = _ArithLeaf()
        m.submodules.leaf = leaf
        inputs += [leaf.a, leaf.b]
        outputs += [leaf.o, leaf.r]
        sums.append(leaf.r if i % 2 else leaf.o)
    total = Signal(24)
    acc = C(0, 24)
    for s in sums:
        acc = acc + s
    m.comb += total.eq(acc)
    outputs.append(total)
    return m, inputs, outputs


class _Tiny(Module):
    def __init__(self, width=8):
        self.a = Signal(width)
        self.b = Signal(width)
        self.q = Signal(width)
        self.d = Signal(width)
        self.comb += self.q.eq(self.a & self.b | C(1, width))
        self.sync += self.d.eq(self.a + self.b)


def _build_many_modules(n=2500):
    m = Module()
    inputs, outputs = [], []
    last_q = None
    for i in range(n):
        t = _Tiny()
        m.submodules.t = t
        if last_q is None:
            inputs += [t.a, t.b]
        else:
            m.comb += t.a.eq(last_q), t.b.eq(t.q if False else last_q ^ C(i, 8))
        outputs.append(t.d)
        last_q = t.q
    return m, inputs, [outputs[-1]]


def _build_array_mux(n_arrays=128, n_choices=16):
    m = Module()
    inputs, outputs = [], []
    sel = Signal(max=n_choices)
    data = Signal(12)
    inputs += [sel, data]
    for i in range(n_arrays):
        choices = []
        for c in range(n_choices):
            s = Signal(12, name_override="a{}c{}".format(i, c))
            m.sync += s.eq(data + C(c * i, 12))
            choices.append(s)
        out = Signal(12, name_override="a{}out".format(i))
        m.comb += out.eq(Array(choices)[sel])
        outputs.append(out)
    # exercise the LHS (write) path of array-proxy lowering
    dst = Array([Signal(12, name_override="dst{}".format(c))
                 for c in range(n_choices)])
    en = Signal()
    inputs.append(en)
    for c in range(n_choices):
        outputs.append(dst[c])
    m.sync += If(en, dst[sel].eq(data))
    return m, inputs, outputs


def _build_slice_part(n=512):
    m = Module()
    inputs, outputs = [], []
    wide = Signal(64)
    off = Signal(4)
    inputs += [wide, off]
    for i in range(n):
        part = Signal(8, name_override="p{}".format(i))
        m.comb += part.eq(wide.part(C((i * 5) % 49, 6) + off, 8))
        m.comb += part.eq(Cat(wide[i%32:(i%32)+8], wide[(i*3)%40:((i*3)%40)+8][0:4],
                              Replicate(wide[63:64], 4))[0:8])
        outputs.append(part)
    shifted = Signal(64)
    m.comb += shifted.eq((wide << C(1, 6)) | (wide >> C(1, 6)))
    shifted_out = Signal(16, name_override="shifted_out")
    m.comb += shifted_out.eq(shifted[0:16])
    outputs.append(shifted_out)
    return m, inputs, outputs


def _build_mem_ports(width=32, depth=4096, n_ports=6):
    m = Module()
    mem = Memory(width, depth)
    inputs, outputs = [], []
    wrport = mem.get_port(write_capable=True)
    m.specials += mem, wrport
    we_adr = Signal(max=depth)
    we_dat = Signal(width)
    we = Signal()
    m.comb += wrport.adr.eq(we_adr), wrport.dat_w.eq(we_dat), wrport.we.eq(we)
    inputs += [we_adr, we_dat, we]
    for p in range(n_ports):
        port = mem.get_port(has_re=True)
        m.specials += port
        adr = Signal(max=depth)
        re = Signal()
        m.comb += port.adr.eq(adr), port.re.eq(re)
        inputs += [adr, re]
        outputs.append(port.dat_r)
    return m, inputs, outputs


class _FsmStage(Module):
    def __init__(self, n_states=8):
        self.start = Signal()
        self.x = Signal(8)
        self.done = Signal()
        self.y = Signal(8)

        fsm = FSM(reset_state="IDLE")
        self.submodules += fsm
        acc = Signal(8)
        fsm.act("IDLE",
                self.done.eq(1),
                If(self.start,
                   NextState("S0")))
        for s in range(n_states - 1):
            fsm.act("S{}".format(s),
                    NextState("S{}".format(s + 1)),
                    self.y.eq(acc + C(s, 8)))
        fsm.act("S{}".format(n_states - 1),
                NextState("IDLE"),
                self.y.eq(acc))
        # acc must be updated synchronously - assigning it inside an act
        # block would create a combinational loop
        self.sync += If(fsm.ongoing("IDLE"),
                        acc.eq(self.x)).Else(acc.eq(acc + C(1, 8)))


def _build_fsm_chain(n_stages=120, n_states=8):
    m = Module()
    inputs, outputs = [], []
    prev_done = Signal(reset=1)
    x = Signal(8)
    start = Signal()
    inputs += [x, start]
    for i in range(n_stages):
        st = _FsmStage(n_states)
        m.submodules.st = st
        m.comb += st.start.eq(start & prev_done), st.x.eq(x + C(i, 8))
        prev_done = st.done
        outputs.append(st.y)
    return m, inputs, outputs


DESIGNS = [
    Design("arith_tree", _build_arith_tree, None, None),
    Design("many_modules", _build_many_modules, None, None),
    Design("array_mux", _build_array_mux, None, None),
    Design("slice_part", _build_slice_part, None, None),
    Design("mem_ports", _build_mem_ports, None, None),
    Design("fsm_chain", _build_fsm_chain, None, None),
]


def build_design(name_or_design, **params):
    d = name_or_design if isinstance(name_or_design, Design) \
        else {x.name: x for x in DESIGNS}[name_or_design]
    module, inputs, outputs = d.build(**params)
    return module, inputs, outputs


# Designs that only use constructs the Z3 translator supports (no Memory
# specials). Used by the formal equivalence tests.
Z3_DESIGNS = ["arith_tree", "many_modules", "array_mux", "slice_part",
              "fsm_chain"]
