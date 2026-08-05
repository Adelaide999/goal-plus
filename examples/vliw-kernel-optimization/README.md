# VLIW Kernel Optimization

This example is a local, public-case VLIW optimization task that can be opened
directly through Pi's native `/goal-plus` command. It uses only the Python
standard library and does not require Docker or accelerator hardware.

## One-command start

From the Goal Plus repository root:

```bash
pi -p "$(cat examples/vliw-kernel-optimization/pi-goal-prompt.md)"
```

The checked-in prompt uses this role routing:

```text
model=gpt-5.6-terra,gpt-5.6-sol
```

The first model runs the Main Agent and Evidence Annotation; the second model
runs both candidate Workers. These short ids must resolve uniquely in the local
Pi registry; use qualified `provider/model` values if a model id is ambiguous.
A single value uses the same model for all three roles, while three values
select Main, Annotation, and Worker independently.

The equivalent interactive request is the first line of
[`pi-goal-prompt.md`](pi-goal-prompt.md). No SearchSpec or experiment launcher
is required: Goal Plus discovers the verifier, metric, edit surface, and local
workspace from the task.

## Local baseline

Run the public task without Goal Plus:

```bash
cd examples/vliw-kernel-optimization/workspace
python3 runner.py
python3 .goal-plus-verifiers/vliw_score.py
```

The starter implementation is correct and reports `147734` cycles. Lower is
better. Only `solution.py` is an optimization surface; the simulator, runner,
verifier, test cases, and Goal Plus score adapter are read-only evaluation
assets.

## Scope

This is a runnable local example, not an official EdgeBench result. It includes
only public cases, so it demonstrates Goal Plus orchestration and model routing
rather than hidden-case benchmark comparability. See
[`PROVENANCE.md`](PROVENANCE.md) for the upstream source and license.
