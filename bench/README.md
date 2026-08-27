# Elaboration benchmark & correctness harness

Tooling to measure Verilog-elaboration time (`migen.fhdl.verilog.convert`)
and to guard optimization work with layered correctness tests.

## Layout

| file                | purpose |
|---------------------|---------|
| `designs.py`        | parameterized designs stressing known hot spots (tracing, fragment merge, Array/Case lowering, slice/part lowering, Memory specials, FSM) |
| `elab_bench.py`     | per-phase timing harness (build, fragment merge, lowering passes, naming, printing) |
| `correctness.py`    | golden regression: sha256 of Verilog output + deterministic simulation trace, artifacts in `golden/` |
| `z3_equiv.py`       | translates a lowered FHDL fragment into a Z3 transition system and proves bounded equivalence of two fragments |
| `ref_pipeline.py`   | frozen copy of the pre-optimization lowering pipeline used as the formal reference |
| `test_bench.py`     | pytest suite tying it all together |

## Benchmark

```sh
uv run python -m bench.elab_bench                  # all designs
uv run python -m bench.elab_bench many_modules     # subset
uv run python -m bench.elab_bench --repeat 3 --json before.json
```

Best-of-N timings per phase; compare `before.json` / `after.json` across
optimization commits.

## Correctness layers

All must pass before and after any optimization:

1. **Golden regression** (`test_golden_verilog`, `test_golden_simulation_trace`)
   - exact-match hashes of the generated Verilog and of a seeded
     simulation trace for every design.
   - regenerate *only* when an output change is intended and reviewed:
     ```sh
     uv run python -m bench.correctness generate   # after review!
     uv run python -m bench.correctness check      # or just run pytest
     ```
2. **Harness sanity** (`test_profiled_convert_matches_verilog_convert`) -
   the profiled pipeline produces byte-identical output to `convert()`.
3. **Z3 formal equivalence** (`-m z3`), see below.

## Z3 formal equivalence checking

`bench/z3_equiv.py` lowers fragments to symbolic transition systems:
signals become BitVecs, comb statements execute with blocking semantics
from reset defaults, sync statements update concurrently (NBA semantics),
inputs are fresh free variables per cycle.  For each of N cycles the
checker asserts that *some* observable signal differs between the two
fragments; **unsat** proves equivalence to depth N.

Two properties are checked (`pytest bench -m z3`):

- the live conversion pipeline produces hardware equivalent to the frozen
  reference pipeline (`bench/ref_pipeline.py`) on every Z3-compatible
  design,
- fragment merging is associative: `(a + b) + c == a + (b + c)`.

This catches semantic regressions even when they only manifest for input
sequences the random simulation misses.  It does not cover Memory
specials (excluded from `Z3_DESIGNS`; those rely on golden + simulation).

## Running

```sh
uv run python -m pytest bench -q          # everything (~3 s)
uv run python -m pytest bench -q -m "not z3"   # skip formal checks
```

Dependencies: `pytest`, `z3-solver`.
