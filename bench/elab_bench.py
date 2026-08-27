"""Elaboration-time benchmark harness.

Times each phase of the Verilog conversion pipeline separately so that
optimization work can target the actual hot spots:

    build            Python object construction (Signal()/traceback cost)
    fragment merge   Module.get_fragment() and Fragment.__iadd__
    cd collect       clock-domain discovery
    lower_slices     lower_complex_slices()
    insert_resets    insert_resets()
    lower_basics_1   first lower_basics() pass
    lower_specials   lower_specials() pass
    lower_basics_2   second lower_basics() pass
    naming           build_namespace()
    printing         Verilog text generation

Usage:
    python -m bench.elab_bench                     # all designs, table output
    python -m bench.elab_bench arith_tree mem_ports
    python -m bench.elab_bench --json results.json # machine-readable dump
"""

import argparse
import json
import sys
import time
from collections import defaultdict

from migen.fhdl.structure import _Fragment
from migen.fhdl.tools import (lower_complex_slices, lower_basics,
                              lower_specials, list_clock_domains)
from migen.fhdl.namer import build_namespace
from migen.fhdl import verilog
from migen.fhdl.conv_output import ConvOutput

from .designs import DESIGNS, build_design


class _Timer:
    def __init__(self):
        self.phases = defaultdict(float)

    class _Span:
        def __init__(self, timer, name):
            self.timer = timer
            self.name = name

        def __enter__(self):
            self.t0 = time.perf_counter()

        def __exit__(self, *exc):
            self.timer.phases[self.name] += time.perf_counter() - self.t0

    def span(self, name):
        return self._Span(self, name)


def convert_profiled(fi, ios=None, name="top", special_overrides=dict(),
                     create_clock_domains=True):
    """Mirror of migen.fhdl.verilog.convert() with per-phase timing."""
    t = _Timer()
    r = ConvOutput()

    if not isinstance(fi, _Fragment):
        with t.span("fragment merge"):
            fi = fi.get_fragment()
    f = _Fragment()
    with t.span("fragment merge"):
        f += fi

    if ios is None:
        ios = set()
    with t.span("cd collect"):
        for cd_name in sorted(list_clock_domains(f)):
            try:
                f.clock_domains[cd_name]
            except KeyError:
                if create_clock_domains:
                    from migen.fhdl.structure import ClockDomain
                    cd = ClockDomain(cd_name)
                    f.clock_domains.append(cd)
                    ios |= {cd.clk, cd.rst}
                else:
                    raise KeyError("Unresolved clock domain: \""+cd_name+"\"")

    with t.span("lower slices"):
        f = lower_complex_slices(f)
    with t.span("insert resets"):
        from migen.fhdl.tools import insert_resets
        insert_resets(f)
    with t.span("lower basics 1"):
        f = lower_basics(f)
    with t.span("lower specials"):
        f, lowered_specials = lower_specials(special_overrides, f)
    with t.span("lower basics 2"):
        f = lower_basics(f)

    with t.span("naming"):
        from migen.fhdl.tools import list_signals, list_special_ios
        for io in sorted(ios, key=lambda x: x.duid):
            if io.name_override is None:
                io_name = io.backtrace[-1][0]
                if io_name:
                    io.name_override = io_name
        ns = build_namespace(list_signals(f)
                             | list_special_ios(f, True, True, True)
                             | ios, verilog._reserved_keywords)

    with t.span("printing"):
        src = "/* Machine-generated using Migen */\n"
        src += verilog._printheader(f, ios, name, ns, DummyAttrTranslate())
        src += verilog._printcomb(f, ns, display_run=False)
        src += verilog._printsync(f, ns)
        src += verilog._printspecials(special_overrides,
                                      f.specials - lowered_specials,
                                      ns, r.add_data_file, DummyAttrTranslate())
        src += "endmodule\n"
    r.set_main_source(src)
    return r, dict(t.phases)


class DummyAttrTranslate:
    def __getitem__(self, k):
        return (k, "true")


def run_benchmark(names=None, repeat=1, **params):
    """Returns {design: {phase: seconds}} using best-of-N timings."""
    results = {}
    for d in DESIGNS:
        if names and d.name not in names:
            continue
        best = {}
        for _ in range(repeat):
            _, phases = convert_profiled_build(d.name, **params)
            for phase, sec in phases.items():
                if phase not in best or sec < best[phase]:
                    best[phase] = sec
        results[d.name] = best
    return results


def convert_profiled_build(name, **params):
    t0 = time.perf_counter()
    module, inputs, outputs = build_design(name, **params)
    build_time = time.perf_counter() - t0
    ios = set(inputs) | set(outputs)
    result, phases = convert_profiled(module, ios=ios)
    phases_out = {"build": build_time, "total convert": sum(phases.values())}
    phases_out.update(phases)
    return result, phases_out


def format_table(results):
    phases = []
    for ph in results.values():
        for k in ph:
            if k not in phases:
                phases.append(k)
    order = ["build", "total convert", "fragment merge", "cd collect",
             "lower slices", "insert resets", "lower basics 1",
             "lower specials", "lower basics 2", "naming", "printing"]
    phases.sort(key=lambda p: order.index(p) if p in order else len(order))
    header = "{:<16}".format("design") + "".join(
        "{:>14}".format(p[:13]) for p in phases)
    lines = [header, "-" * len(header)]
    for name, ph in results.items():
        row = "{:<16}".format(name)
        for p in phases:
            v = ph.get(p)
            row += "{:>14}".format("{:.4f}".format(v) if v is not None else "-")
        lines.append(row)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("designs", nargs="*",
                    help="subset of: {}".format(", ".join(d.name for d in DESIGNS)))
    ap.add_argument("--repeat", type=int, default=1,
                    help="runs per design; best-of-N per phase (default 1)")
    ap.add_argument("--json", dest="json_path",
                    help="also write results as JSON")
    args = ap.parse_args()

    names = set(args.designs) or None
    unknown = (names or set()) - {d.name for d in DESIGNS}
    if unknown:
        ap.error("unknown design(s): {}".format(", ".join(sorted(unknown))))

    # deep expression trees recurse deeply in NodeTransformer; give the
    # benchmark a big stack instead of failing with RecursionError
    import threading
    sys.setrecursionlimit(200000)
    threading.stack_size(256 * 1024 * 1024)
    holder = {}

    def _run():
        try:
            holder["results"] = run_benchmark(names, repeat=args.repeat)
        except BaseException as e:
            holder["error"] = e

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    if "error" in holder:
        raise holder["error"]
    results = holder["results"]

    print(format_table(results))
    if args.json_path:
        with open(args.json_path, "w") as fp:
            json.dump(results, fp, indent=2, sort_keys=True)
        print("\nwrote {}".format(args.json_path))


if __name__ == "__main__":
    main()
