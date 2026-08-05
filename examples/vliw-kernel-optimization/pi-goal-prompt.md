/goal-plus main=openai/gpt-5.6-terra annotator=openai/gpt-5.6-terra workers=zai/glm-5.2 max_parallel=2 Optimize the VLIW kernel in `examples/vliw-kernel-optimization/workspace`.

Minimize the correct `cycles` value emitted by
`.goal-plus-verifiers/vliw_score.py`. Preserve the simulator semantics and all
public-case correctness. Only `solution.py` may be edited; do not modify the
runner, verifier, simulator, test cases, or score adapter. Do not hard-code
case seeds or use network access. Report the selected verifier-backed cycle
count and the improvement over the 147734-cycle starter implementation.
