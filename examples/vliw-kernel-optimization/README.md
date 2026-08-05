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
main=openai/gpt-5.6-terra annotator=openai/gpt-5.6-terra workers=zai/glm-5.2
```

`main` and `annotator` select those roles explicitly; `workers` uses the
existing Candidate model allocation and can contain one or more models. These
short ids must resolve uniquely in the local
Pi registry; use qualified `provider/model` values if a model id is ambiguous.
For example, `workers=worker-a,worker-b` round-robins two models over the fixed
candidate lanes. Existing `models=` remains a compatibility alias for
`workers=`.

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
