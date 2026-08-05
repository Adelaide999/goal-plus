# Public VLIW Workspace

Optimize `solution.py`, specifically `KernelBuilder.build_kernel`, to reduce
the simulated cycle count while preserving the output of `reference_kernel2`.
The complete machine and task contract is in [`problem.md`](problem.md).

Run the public evaluator with:

```bash
python3 runner.py
```

Goal Plus uses:

```bash
python3 .goal-plus-verifiers/vliw_score.py
```

The score adapter exits nonzero for invalid solutions and otherwise emits a
final JSON object containing `cycles`. Lower values are better.

Only `solution.py` may be edited. Treat `problem.py`, `runner.py`,
`verifier.py`, `test_cases/`, `public_tests/`, and `.goal-plus-verifiers/` as
read-only evaluation assets.
