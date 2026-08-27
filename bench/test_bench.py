"""Correctness tests guarding elaboration-time optimizations.

Layers (all must pass before/after any optimization):

1. golden regression - sha256 of Verilog output and of a deterministic
   simulation trace for every benchmark design
2. harness sanity    - convert_profiled() produces identical Verilog to
                       verilog.convert()
3. Z3 equivalence    - the live conversion pipeline is formally proven
   equivalent (to a bounded depth) to the frozen reference pipeline in
   bench/ref_pipeline.py, and fragment merging is associative

Run:  pytest bench -v          (add `-m "not z3"` to skip formal checks)
Regenerate goldens after *intentional* output changes:
      python -m bench.correctness generate
"""

import hashlib
import json
import os

import pytest

from migen.fhdl.structure import _Fragment
from migen.fhdl import verilog

from .correctness import GOLDEN_DIR, DESIGNS, artifact_for, convert_design
from .designs import build_design, Z3_DESIGNS
from .elab_bench import convert_profiled


# ----------------------------------------------------------------- golden

@pytest.mark.parametrize("name", [d.name for d in DESIGNS])
def test_golden_verilog(name):
    ref = json.load(open(os.path.join(GOLDEN_DIR, "index.json")))[name]
    src = convert_design(name)
    assert hashlib.sha256(src.encode()).hexdigest() == ref["verilog_sha256"], (
        "Verilog output changed for {}; diff against bench/golden/{}.v "
        "and update goldens only if the change is intended".format(
            name, name))


@pytest.mark.parametrize("name", [d.name for d in DESIGNS])
def test_golden_simulation_trace(name):
    ref = json.load(open(os.path.join(GOLDEN_DIR, "index.json")))[name]
    art = artifact_for(name)
    trace_hash = hashlib.sha256(
        json.dumps(art["trace"]).encode()).hexdigest()
    assert trace_hash == ref["trace_sha256"]


# ---------------------------------------------------------------- harness

@pytest.mark.parametrize("name", [d.name for d in DESIGNS])
def test_profiled_convert_matches_verilog_convert(name):
    module, inputs, outputs = build_design(
        name, **_correctness_params(name))
    r1, _ = convert_profiled(module, ios=set(inputs) | set(outputs))
    module2, inputs2, outputs2 = build_design(
        name, **_correctness_params(name))
    r2 = verilog.convert(module2, ios=set(inputs2) | set(outputs2))
    assert str(r1) == str(r2)


def _correctness_params(name):
    from .correctness import CORRECTNESS_PARAMS
    return dict(CORRECTNESS_PARAMS[name])


# -------------------------------------------------------------------- z3

def _lowered_pair(name, params):
    """Build one raw fragment, lower clones through reference + live."""
    from .z3_equiv import clone_fragment
    from .ref_pipeline import run_reference_pipeline

    def prep(f):
        from migen.fhdl.structure import ClockDomain
        from migen.fhdl.tools import list_clock_domains
        for cd_name in sorted(list_clock_domains(f)):
            try:
                f.clock_domains[cd_name]
            except KeyError:
                f.clock_domains.append(ClockDomain(cd_name))

    def live_pipeline(f):
        from migen.fhdl import tools
        f = tools.lower_complex_slices(f)
        tools.insert_resets(f)
        f = tools.lower_basics(f)
        f = tools.lower_basics(f)
        return f

    module, inputs, outputs = build_design(name, **params)
    raw = module.get_fragment()
    # add missing clock domains *before* cloning so both pipelines share
    # the same cd.clk / cd.rst Signal objects
    prep(raw)
    f_ref = run_reference_pipeline(clone_fragment(raw))
    f_live = live_pipeline(clone_fragment(raw))
    return f_ref, f_live, inputs, outputs


@pytest.mark.z3
@pytest.mark.parametrize("name", Z3_DESIGNS)
def test_z3_live_pipeline_equivalent_to_reference(name):
    from .z3_equiv import fragments_equivalent
    from .correctness import CORRECTNESS_PARAMS

    f_ref, f_live, inputs, outputs = _lowered_pair(
        name, dict(CORRECTNESS_PARAMS[name]))
    ok, model, stats = fragments_equivalent(
        f_ref, f_live, set(inputs), cycles=3)
    assert ok, "pipeline divergence detected ({}): {}".format(name, model)


@pytest.mark.z3
def test_z3_fragment_merge_associativity():
    """((a+b)+c) must be equivalent to (a+(b+c)) - guards Fragment.__add__."""
    from .z3_equiv import clone_fragment, fragments_equivalent
    from .correctness import CORRECTNESS_PARAMS

    module, inputs, outputs = build_design(
        "array_mux", **CORRECTNESS_PARAMS["array_mux"])
    f = module.get_fragment()
    k = len(f.comb) // 3
    cds = list(f.clock_domains)

    def sub(comb_slice):
        return _Fragment(list(comb_slice), {}, set(), list(cds))

    a = sub(f.comb[:k])
    b = _Fragment(list(f.comb[k:2 * k]),
                  {cd: list(v) for cd, v in f.sync.items()},
                  set(), list(cds))
    c = sub(f.comb[2 * k:])

    left = (a + b) + c
    right = a + (b + c)
    ok, model, stats = fragments_equivalent(
        left, right, set(inputs), cycles=3)
    assert ok, "fragment merge associativity broken: {}".format(model)
