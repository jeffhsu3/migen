import operator
import collections.abc
import inspect
from functools import wraps

from migen.fhdl.structure import *
from migen.fhdl.structure import (_Value, _Statement,
                                  _Operator, _Slice, _Part, _ArrayProxy,
                                  _Assign, _Fragment)
from migen.fhdl.bitcontainer import value_bits_sign
from migen.fhdl.tools import (list_targets, list_signals,
                              insert_resets, lower_specials)
from migen.fhdl.simplify import MemoryToArray
from migen.fhdl.specials import _MemoryLocation
from migen.fhdl.module import Module
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.sim.vcd import VCDWriter, DummyVCDWriter


class ClockState:
    def __init__(self, high, half_period, time_before_trans):
        self.high = high
        self.half_period = half_period
        self.time_before_trans = time_before_trans


class TimeManager:
    def __init__(self, description):
        self.clocks = collections.OrderedDict()

        for k, period_phase in description.items():
            if isinstance(period_phase, tuple):
                period, phase = period_phase
            else:
                period = period_phase
                phase = 0
            half_period = period//2
            if phase >= half_period:
                phase -= half_period
                high = True
            else:
                high = False
            self.clocks[k] = ClockState(high, half_period, half_period - phase)

    def tick(self):
        rising = set()
        falling = set()
        dt = min(cs.time_before_trans for cs in self.clocks.values())
        for k, cs in self.clocks.items():
            if cs.time_before_trans == dt:
                cs.high = not cs.high
                if cs.high:
                    rising.add(k)
                else:
                    falling.add(k)
            cs.time_before_trans -= dt
            if not cs.time_before_trans:
                cs.time_before_trans += cs.half_period
        return dt, rising, falling


str2op = {
    "~": operator.invert,
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,

    ">>>": operator.rshift,
    "<<<": operator.lshift,

    "&": operator.and_,
    "^": operator.xor,
    "|": operator.or_,

    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
}


def _truncate(value, nbits, signed):
    value = value & (2**nbits - 1)
    if signed and (value & 2**(nbits - 1)):
        value -= 2**nbits
    return value


_comparisons = {"<", "<=", "==", "!=", ">", ">="}


def _printed_signed(node):
    # Match the flag _printexpr uses to insert $signed({1'd0, ...}) casts.
    # For comparisons and shifts this can differ from the actual Verilog
    # result type, so it must be kept separate from _expression_bits_sign.
    if isinstance(node, _Operator):
        if node.op == "-" and len(node.operands) == 1:
            return True
        operands = node.operands[1:] if node.op == "m" else node.operands
        return any(_printed_signed(o) for o in operands)
    if isinstance(node, (_Slice, _Part, Cat, Replicate)):
        return False
    return _expression_bits_sign(node)[1]


def _operand_bits_sign(operands):
    bs = [_expression_bits_sign(o) for o in operands]
    signs = [_printed_signed(o) for o in operands]
    if any(signs):
        bs = [(nbits, signed) if printed else (nbits + 1, True)
              for (nbits, signed), printed in zip(bs, signs)]
    return (max(nbits for nbits, signed in bs),
            all(signed for nbits, signed in bs))


def _expression_bits_sign(node):
    # Width of the emitted expression, before its context widens it. Unlike
    # value_bits_sign(), Verilog does not reserve carry/product/shift bits.
    if isinstance(node, _Operator):
        if node.op in _comparisons:
            return 1, False
        if node.op == "m":
            operands = node.operands[1:]
        else:
            operands = node.operands
        if len(operands) == 1:
            nbits, signed = _expression_bits_sign(operands[0])
            if node.op == "-" and not _printed_signed(operands[0]):
                # The backend emits -$signed({1'd0, unsigned_operand}).
                return nbits + 1, True
            return nbits, signed
        if node.op in {"<<<", ">>>"}:
            return _expression_bits_sign(operands[0])
        return _operand_bits_sign(operands)
    elif isinstance(node, Cat):
        return sum(_expression_bits_sign(e)[0] for e in node.l), False
    elif isinstance(node, Replicate):
        return _expression_bits_sign(node.v)[0] * node.n, False
    elif isinstance(node, _MemoryLocation):
        return node.memory.width, False
    return value_bits_sign(node)


class Evaluator:
    def __init__(self, clock_domains, replaced_memories):
        self.clock_domains = clock_domains
        self.replaced_memories = replaced_memories
        self.signal_values = dict()
        self.modifications = dict()

    def commit(self):
        r = set()
        for k, v in self.modifications.items():
            if k not in self.signal_values or self.signal_values[k] != v:
                self.signal_values[k] = v
                r.add(k)
        self.modifications.clear()
        return r

    def _eval_operand(self, node, postcommit, nbits, cast_signed,
                      context_signed):
        if cast_signed and not _printed_signed(node):
            # Mixed signed/unsigned operations emit $signed({1'd0, node}).
            # The concatenation stops the outer width reaching node.
            nbits = _expression_bits_sign(node)[0]
            return _truncate(self.eval(node, postcommit, 0), nbits, False)
        return self.eval(node, postcommit, nbits, context_signed)

    def eval(self, node, postcommit=False, context_width=None,
             context_signed=None):
        # None uses the FHDL width for a standalone simulator request;
        # zero selects Verilog's self-determined expression width. A positive
        # width comes from an assignment or a surrounding operator. Signedness
        # propagates separately (an assignment's target type does not affect it).
        if isinstance(node, Constant):
            value = node.value
        elif isinstance(node, Signal):
            if postcommit and node in self.modifications:
                value = self.modifications[node]
            else:
                value = self.signal_values.get(node, node.reset.value)
        else:
            value = None
        if value is not None:
            signed = node.signed and context_signed is not False
            return _truncate(value, node.nbits, signed)

        if isinstance(node, _Operator):
            # A directly yielded value uses its FHDL width. Inside a Verilog
            # expression, widths flow from assignments and other operands.
            if context_width is None:
                context_width = len(node)
            nbits, signed = _expression_bits_sign(node)
            cast_signed = _printed_signed(node)
            nbits = max(nbits, context_width)
            if context_signed is None:
                context_signed = signed
            if node.op in _comparisons:
                # The result's context cannot widen the comparison operands.
                nbits, signed = _operand_bits_sign(node.operands)
                context_signed = signed
            if node.op == "m":
                condition = self.eval(node.operands[0], postcommit, 0)
                operand = node.operands[1 if condition else 2]
                result = self._eval_operand(
                    operand, postcommit, nbits, cast_signed, context_signed)
            elif node.op in {"<<<", ">>>"}:
                left, right = node.operands
                value = self.eval(left, postcommit, nbits, context_signed)
                shift = _truncate(self.eval(right, postcommit, 0),
                                  _expression_bits_sign(right)[0], False)
                # Shifts at least as wide as the result have no remaining
                # data bits; avoid constructing arbitrarily large integers.
                result = str2op[node.op](value, min(shift, nbits))
            else:
                operands = [self._eval_operand(o, postcommit, nbits,
                                               cast_signed, context_signed)
                            for o in node.operands]
                if node.op == "-" and len(operands) == 1:
                    result = -operands[0]
                else:
                    result = str2op[node.op](*operands)
            if node.op in _comparisons:
                return int(result)
            return _truncate(result, nbits, context_signed)
        elif isinstance(node, _Slice):
            v = self.eval(node.value, postcommit)
            idx = range(node.start, node.stop)
            return sum(((v >> i) & 1) << j for j, i in enumerate(idx))
        elif isinstance(node, _Part):
            v = self.eval(node.value, postcommit)
            offset = self.eval(node.offset, postcommit)
            idx = range(offset, offset + node.width)
            return sum(((v >> i) & 1) << j for j, i in enumerate(idx))
        elif isinstance(node, Cat):
            shift = 0
            r = 0
            for element in node.l:
                nbits = _expression_bits_sign(element)[0]
                # make value always positive
                value = self.eval(element, postcommit, 0) & (2**nbits - 1)
                r |= value << shift
                shift += nbits
            return r
        elif isinstance(node, Replicate):
            nbits = _expression_bits_sign(node.v)[0]
            v = self.eval(node.v, postcommit, 0) & (2**nbits - 1)
            return sum(v << i*nbits for i in range(node.n))
        elif isinstance(node, _ArrayProxy):
            idx = min(len(node.choices) - 1, self.eval(node.key, postcommit))
            nbits, signed = value_bits_sign(node)
            if context_signed is False:
                signed = False
            return _truncate(self.eval(node.choices[idx], postcommit, nbits),
                             nbits, signed)
        elif isinstance(node, _MemoryLocation):
            array = self.replaced_memories[node.memory]
            return self.eval(array[self.eval(node.index, postcommit)], postcommit)
        elif isinstance(node, ClockSignal):
            return self.eval(self.clock_domains[node.cd].clk, postcommit)
        elif isinstance(node, ResetSignal):
            rst = self.clock_domains[node.cd].rst
            if rst is None:
                if node.allow_reset_less:
                    return 0
                else:
                    raise ValueError("Attempted to get reset signal of resetless"
                                     " domain '{}'".format(node.cd))
            else:
                return self.eval(rst, postcommit)
        else:
            raise NotImplementedError(node)

    def assign(self, node, value):
        if isinstance(node, Signal):
            assert not node.variable
            self.modifications[node] = _truncate(value,
                                                 node.nbits, node.signed)
        elif isinstance(node, Cat):
            for element in node.l:
                nbits = len(element)
                self.assign(element, value & (2**nbits-1))
                value >>= nbits
        elif isinstance(node, _Slice):
            full_value = self.eval(node.value, True)
            # clear bits assigned to by the slice
            full_value &= ~((2**node.stop-1) - (2**node.start-1))
            # set them to the new value
            value &= 2**(node.stop - node.start)-1
            full_value |= value << node.start
            self.assign(node.value, full_value)
        elif isinstance(node, _Part):
            full_value = self.eval(node.value, True)
            offset = self.eval(node.offset, True)
            start = offset
            stop = offset + node.width
            full_value &= ~((2**stop-1) - (2**start-1))
            value &= 2**(stop - start)-1
            full_value |= value << start
            self.assign(node.value, full_value)
        elif isinstance(node, _ArrayProxy):
            idx = min(len(node.choices) - 1, self.eval(node.key))
            self.assign(node.choices[idx], value)
        elif isinstance(node, _MemoryLocation):
            array = self.replaced_memories[node.memory]
            self.assign(array[self.eval(node.index)], value)
        else:
            raise NotImplementedError(node)

    def execute(self, statements):
        for s in statements:
            if isinstance(s, _Assign):
                nbits = _expression_bits_sign(s.l)[0]
                self.assign(s.l, self.eval(s.r, context_width=nbits))
            elif isinstance(s, If):
                if self.eval(s.cond, context_width=0):
                    self.execute(s.t)
                else:
                    self.execute(s.f)
            elif isinstance(s, Case):
                # Case items share a comparison context with the selector.
                # Unlike binary operators, case emits no mixed-sign casts.
                bs = [_expression_bits_sign(s.test)] + [
                    value_bits_sign(k) for k in s.cases
                    if isinstance(k, Constant)]
                nbits = max(b[0] for b in bs)
                signed = all(b[1] for b in bs)
                test = self.eval(s.test, context_width=nbits,
                                 context_signed=signed)
                test = _truncate(test, nbits, signed)
                found = False
                for k, v in s.cases.items():
                    if (isinstance(k, Constant)
                            and _truncate(k.value, k.nbits, signed) == test):
                        self.execute(v)
                        found = True
                        break
                if not found and "default" in s.cases:
                    self.execute(s.cases["default"])
            elif isinstance(s, collections.abc.Iterable):
                self.execute(s)
            elif isinstance(s, Display):
                args = []
                for arg in s.args:
                    assert isinstance(arg, _Value)
                    try:
                        args.append(self.signal_values[arg])
                    except: # not yet evaluated
                        args.append(arg.reset.value)
                print(s.s %(*args,))
            else:
                raise NotImplementedError


class DummyAsyncResetSynchronizerImpl(Module):
    def __init__(self, cd, async_reset):
        # TODO: asynchronous set
        # This naive implementation has a minimum reset pulse
        # width requirement of one clock period in cd.
        self.comb += cd.rst.eq(async_reset)


class DummyAsyncResetSynchronizer:
    @staticmethod
    def lower(dr):
        return DummyAsyncResetSynchronizerImpl(dr.cd, dr.async_reset)


# TODO: instances via Iverilog/VPI
class Simulator:
    def __init__(self, fragment_or_module, generators, clocks={"sys": 10}, vcd_name=None,
                 special_overrides={}):
        if isinstance(fragment_or_module, _Fragment):
            self.fragment = fragment_or_module
        else:
            self.fragment = fragment_or_module.get_fragment()

        mta = MemoryToArray()
        mta.transform_fragment(None, self.fragment)

        overrides = {AsyncResetSynchronizer: DummyAsyncResetSynchronizer}
        overrides.update(special_overrides)
        f, lowered = lower_specials(overrides, self.fragment)
        if self.fragment.specials:
            raise ValueError("Could not lower all specials", self.fragment.specials)

        if not isinstance(generators, dict):
            generators = {"sys": generators}
        self.generators = dict()
        self.passive_generators = set()
        for k, v in generators.items():
            if (isinstance(v, collections.abc.Iterable)
                    and not inspect.isgenerator(v)):
                self.generators[k] = list(v)
            else:
                self.generators[k] = [v]

        clocks = collections.OrderedDict(sorted(clocks.items(),
                                                key=operator.itemgetter(0)))
        self.time = TimeManager(clocks)
        for clock in clocks.keys():
            if clock not in self.fragment.clock_domains:
                cd = ClockDomain(name=clock, reset_less=True)
                cd.clk.reset = C(self.time.clocks[clock].high)
                self.fragment.clock_domains.append(cd)

        insert_resets(self.fragment)
        # comb signals return to their reset value if nothing assigns them
        self.fragment.comb[0:0] = [s.eq(s.reset)
                                   for s in list_targets(self.fragment.comb)]
        self.evaluator = Evaluator(self.fragment.clock_domains,
                                   mta.replacements)

        if vcd_name is None:
            self.vcd = DummyVCDWriter()
        else:
            self.vcd = VCDWriter(vcd_name, module_name=type(fragment_or_module).__name__)

            signals = list_signals(self.fragment)
            for cd in self.fragment.clock_domains:
                signals.add(cd.clk)
                if cd.rst is not None:
                    signals.add(cd.rst)
            for memory_array in mta.replacements.values():
                signals |= set(memory_array)
            for signal in sorted(signals, key=lambda x: x.duid):
                self.vcd.set(signal, signal.reset.value)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        self.vcd.close()

    def _commit_and_comb_propagate(self):
        # TODO: optimize
        all_modified = set()
        modified = self.evaluator.commit()
        all_modified |= modified
        while modified:
            self.evaluator.execute(self.fragment.comb)
            modified = self.evaluator.commit()
            all_modified |= modified
        for signal in all_modified:
            self.vcd.set(signal, self.evaluator.signal_values[signal])

    def _evalexec_nested_lists(self, x):
        if isinstance(x, list):
            return [self._evalexec_nested_lists(e) for e in x]
        elif isinstance(x, _Value):
            return self.evaluator.eval(x)
        elif isinstance(x, _Statement):
            self.evaluator.execute([x])
            return None
        else:
            raise ValueError("Invalid simulator exec/eval request", x)

    def _process_generators(self, cd):
        exhausted = []
        for generator in self.generators[cd]:
            reply = None
            while True:
                try:
                    request = generator.send(reply)
                    if request is None:
                        break  # next cycle
                    elif isinstance(request, str):
                        if request == "passive":
                            self.passive_generators.add(generator)
                        elif request == "active":
                            self.passive_generators.discard(generator)
                        else:
                            raise ValueError("Unknown simulator command: '{}'"
                                             .format(request))
                    else:
                        try:
                            reply = self._evalexec_nested_lists(request)
                        except Exception as e:
                            tb = inspect.getframeinfo(generator.gi_frame)
                            print("While evaluating the following generator, an error occurred:")
                            print("  File {}, line {}, in {}".format(tb.filename, tb.lineno, tb.function))
                            for c in tb.code_context:
                                print("    ", c.lstrip())
                            raise

                except StopIteration:
                    exhausted.append(generator)
                    break
        for generator in exhausted:
            self.generators[cd].remove(generator)

    def _continue_simulation(self):
        for cd_generators in self.generators.values():
            if set(cd_generators) - self.passive_generators:
                return True
        return False

    def run(self):
        self.evaluator.execute(self.fragment.comb)
        self._commit_and_comb_propagate()

        while True:
            dt, rising, falling = self.time.tick()
            self.vcd.delay(dt)
            for cd in rising:
                self.evaluator.assign(self.fragment.clock_domains[cd].clk, 1)
                if cd in self.fragment.sync:
                    self.evaluator.execute(self.fragment.sync[cd])
                if cd in self.generators:
                    self._process_generators(cd)
            for cd in falling:
                self.evaluator.assign(self.fragment.clock_domains[cd].clk, 0)
            self._commit_and_comb_propagate()

            if not self._continue_simulation():
                break


def run_simulation(*args, **kwargs):
    with Simulator(*args, **kwargs) as s:
        s.run()


def passive(generator):
    @wraps(generator)
    def wrapper(*args, **kwargs):
        yield "passive"
        yield from generator(*args, **kwargs)
    return wrapper
