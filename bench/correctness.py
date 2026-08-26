"""Golden-output regression harness.

Generates and checks reference artifacts for all benchmark designs:

- sha256 of the Verilog text produced by ``verilog.convert()``
- a deterministic pseudo-random simulation trace (input stimulus is
  seeded; output values are sampled every cycle)

Artifacts live in ``bench/golden/``.  Regenerate with::

    python -m bench.correctness generate

After any optimization, ``python -m bench.correctness check`` must pass.
If the Verilog hash changes, inspect the stored .v diff before deciding
whether the change is benign (e.g. pure reordering) - behavioral tests
(simulation + Z3 equivalence) are the arbiter.
"""

import hashlib
import json
import os
import random

from migen.fhdl import verilog
from migen.fhdl.structure import Constant
from migen.sim.core import Simulator

from .designs import DESIGNS, build_design

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")

# small parameters: correctness artifacts don't need to be slow to build
CORRECTNESS_PARAMS = {
    "arith_tree": {"n_leaves": 16},
    "many_modules": {"n": 60},
    "array_mux": {"n_arrays": 4, "n_choices": 8},
    "slice_part": {"n": 24},
    "mem_ports": {"width": 32, "depth": 64, "n_ports": 2},
    "fsm_chain": {"n_stages": 4, "n_states": 6},
}

N_CYCLES = 120
SEED = 0x5EED


def _mask(sig):
    return (1 << len(sig)) - 1


def simulate_design(name, n_cycles=N_CYCLES, seed=SEED):
    """Run the design in the Migen simulator with PRBS inputs.

    Returns list of per-cycle output value lists (masked to signal width).
    Outputs are sampled at each clock edge before sync updates commit,
    i.e. they are the registered outputs as seen by an external observer.
    """
    module, inputs, outputs = build_design(name, **CORRECTNESS_PARAMS[name])
    trace = []
    rng = random.Random(seed)
    done = [False]

    def driver():
        for _ in range(n_cycles):
            stmts = []
            for s in inputs:
                v = rng.getrandbits(len(s))
                stmts.append(s.eq(Constant(v, (len(s), s.signed))))
            yield stmts
            yield None
            trace.append([sim.evaluator.eval(o) & _mask(o) for o in outputs])
        done[0] = True

    sim = Simulator(module, {"sys": []})
    sim.generators["sys"].append(driver())
    with sim:
        sim.run()
    if not done[0]:
        raise RuntimeError("driver did not complete")
    return trace


def convert_design(name):
    module, inputs, outputs = build_design(name, **CORRECTNESS_PARAMS[name])
    ios = set(inputs) | set(outputs)
    return str(verilog.convert(module, ios=ios))


def artifact_for(name):
    src = convert_design(name)
    return {
        "params": CORRECTNESS_PARAMS[name],
        "cycles": N_CYCLES,
        "seed": SEED,
        "verilog_sha256": hashlib.sha256(src.encode()).hexdigest(),
        "trace": simulate_design(name),
    }


def generate():
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    index = {}
    for d in DESIGNS:
        print("generating golden data for", d.name)
        art = artifact_for(d.name)
        index[d.name] = {
            k: v for k, v in art.items() if k != "trace"
        }
        index[d.name]["trace_sha256"] = hashlib.sha256(
            json.dumps(art["trace"]).encode()).hexdigest()
        with open(os.path.join(GOLDEN_DIR, d.name + ".v"), "w") as fp:
            fp.write(convert_design(d.name))
        with open(os.path.join(GOLDEN_DIR, d.name + ".trace.json"), "w") as fp:
            json.dump(art["trace"], fp)
    with open(os.path.join(GOLDEN_DIR, "index.json"), "w") as fp:
        json.dump(index, fp, indent=1, sort_keys=True)
    print("wrote golden data to", GOLDEN_DIR)


def check():
    failures = []
    with open(os.path.join(GOLDEN_DIR, "index.json")) as fp:
        index = json.load(fp)
    for d in DESIGNS:
        ref = index[d.name]
        art = artifact_for(d.name)
        if art["verilog_sha256"] != ref["verilog_sha256"]:
            failures.append("{}: Verilog output changed".format(d.name))
        trace_hash = hashlib.sha256(
            json.dumps(art["trace"]).encode()).hexdigest()
        if trace_hash != ref["trace_sha256"]:
            failures.append("{}: simulation trace changed".format(d.name))
    return failures


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["generate"]:
        generate()
    else:
        fails = check()
        if fails:
            print("\n".join(fails))
            sys.exit(1)
        print("all golden artifacts match")
