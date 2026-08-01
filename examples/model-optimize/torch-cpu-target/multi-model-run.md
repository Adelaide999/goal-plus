# Multi-model validation

This is a small live validation of Goal Plus static model selection on the
deterministic Torch CPU target. It assigns two long-lived candidate lanes to
different Codex models while both use the same run-wide Annotated Evidence.

| Candidate slot | Fixed selected model |
| --- | --- |
| `c001` | `gpt-5.6-terra` |
| `c002` | `gpt-5.6-sol` |

The binding is `immutable_per_loop`: a candidate retains its selected model
over continuation. There is no model routing, replacement, or
candidate-isolated search. Annotated Evidence is shared read-only coordination
context; it does not reserve files or prove that a worker read it.

## Preconditions

Run from the repository root. The `scaling` Conda environment must contain the
CPU PyTorch runtime. First establish the deterministic local baseline:

```powershell
conda run -n scaling python examples/model-optimize/torch-cpu-target/verify.py
conda run -n scaling python examples/model-optimize/torch-cpu-target/benchmark.py
```

The verifier commands in the spec use `python`. Activate `scaling` in the
shell that launches Codex so candidate workers inherit that interpreter. Do
not wrap the global Codex shim in `conda run` on Windows; some installations
deny execution of that shim from `conda run`.

```powershell
conda activate scaling
Remove-Item Env:SSL_CERT_FILE -ErrorAction Ignore
Remove-Item Env:CODEX_CA_CERTIFICATE -ErrorAction Ignore
cmd /c codex exec --full-auto "Use Goal Plus Search Mode to run examples/model-optimize/torch-cpu-target/multi-model-search-spec.json. Freeze this exact spec, create the run, make exactly one initial plan for two candidates, and launch the returned Codex sessions. Each worker may edit only model.py or serving.py, must use search_get_global_evidence before an iteration, and must call search_run_verifier with its own agent_session_id after a material change. Continue the same two workers only while the run policy allows. Select and promote only after the candidate work completes, then record the Goal Plus result and produce the terminal report."
```

The explicit clearing of `SSL_CERT_FILE` and `CODEX_CA_CERTIFICATE` is
intentional. Some Windows Conda setups retain a stale
`...\\scaling\\ssl\\cacert.pem` value; clearing it makes Codex use Windows
system trust roots. If the network requires a corporate CA, set
`CODEX_CA_CERTIFICATE` to that valid PEM file instead.

The outer Codex controller model is deliberately unspecified. Worker model
identity is governed by frozen `strategy.models` and the generated
`selected_models` lane bindings.

## Acceptance evidence

Accept a run only if all of the following are present under its `.gp` state:

- The frozen spec has the two declared model choices with one count each.
- The only initial plan has `requested_k=2`, with `selected_models` ordered
  Terra, Sol.
- Candidate and agent-session records preserve those same exact models across
  any continuation.
- Both lanes share the same `run_id`; verifier-backed iterations from either
  lane appear in the Annotated Evidence view available to the other.
- Every selected result passes `verify.py`, reports a finite
  `tokens_per_second`, and leaves the one-thread rule intact.

This is an integration smoke, not an effectiveness comparison: two models and
one run cannot establish a multi-model performance advantage.
