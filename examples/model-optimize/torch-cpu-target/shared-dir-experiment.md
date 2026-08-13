# Shared-dir validation

This validation exercises verifier-settled shared tools.

## Scope

Run [`shared-dir-treatment-search-spec.json`](shared-dir-treatment-search-spec.json)
with the two ordered proposals in
[`shared-dir-proposals.json`](shared-dir-proposals.json). The spec enables
`shared_dir`, uses a correctness validity gate before the ranking verifier,
and keeps every candidate's final artifact independent of the run shared
directory.

The first candidate publishes a small tool after its process verifier passes.
The second discovers, copies, adapts, and locally revalidates that tool.

## Preconditions

- Use a clean checkout with an enabled `goal-plus` MCP server.
- Run candidates through the normal `parallel_loops` flow; workers must submit
  their own process verifier with the supplied `agent_session_id`.
- Keep the CPU verifier resource lock and the single-thread contract intact.
- Do not edit frozen verifiers, `.gp` state, or the validation files during a
  validation run.

## Required mechanism chain

```text
producer staging
  -> attributed passing process verifier
  -> immutable shared snapshot and index entry
  -> tool remains absent from candidate Global Evidence
  -> annotator publishes a Tool View from manifest, snapshot, and Evidence
  -> all loops read the Tool View and prior objective iteration Views
  -> adopter judges relevance and requests one hash-checked candidate-local copy
  -> adopter adapts the copied files into allowed_files
  -> the next process verifier atomically consumes the copy receipt
  -> an objective iteration View describing adoption enters Global Evidence
  -> discard restores the adopter's prior candidate-local best
```

The producer stages only a small, self-contained tool under its own
`.tmp/share-out` directory. It must not publish an entire project, a verifier,
logs, credentials, datasets, or build output. A `manifest.json` with `name`,
`summary`, and `entrypoint` is recommended.

An adopter may inspect the Tool View, then use `search_copy_shared_tool` to
materialize the exact snapshot in its candidate-local temporary inbox. It must
treat the copy as untrusted code: do not execute unknown scripts or install
peer dependencies. If it uses a tool, it copies and adapts the needed files
into its own allowed edit surface and reruns its own verifier; the promoted
result must not import from or otherwise depend on the temporary inbox or run
shared directory.

## Acceptance criteria

The validation passes only when durable evidence demonstrates all applicable
steps below:

1. A producer has a non-empty staged tool and an attributed, passing process
   verifier.
2. The producer iteration reports `shared_tool_publish_status="published"`
   or `"partially_published"`, and `.gp/runs/<run_id>/shared/index.json`
   contains the published tool id, while candidate Global Evidence still exposes
   no discoverable tool before Tool View binding.
3. After the annotator completes, Global Evidence exposes the same tool id,
   source commit, snapshot hash, and a Tool View that states the tool was not
   independently verified. It does not expose the runtime-owned snapshot path.
4. An adopter judges the Tool View relevant, performs a default single-tool
   isolated trial, and calls `search_copy_shared_tool` with the exact `tool_id`
   and `snapshot_hash`. The returned receipt identifies a candidate-local inbox.
5. The next attributed process verifier atomically consumes the pending receipt,
   records it in the iteration's `adopted_tools`, and generates an objective
   iteration View. The View objectively describes the local adoption outcome
   and any confounded condition; it remains iteration Evidence rather than a
   tool-level reward aggregate.
6. The selected and promoted candidate passes correctness without access to
   the run shared directory.

## Diagnostics

Use `goal_plus_monitor_snapshot` as the primary read-only view. Per candidate,
inspect the latest staged entries/file count, publish status, published count,
and status totals. Relevant statuses are:

- `not_staged`: no tool was offered.
- `skipped_unattributed_verifier`: only parent fallback verification occurred.
- `skipped_failed_verifier`: the process verifier did not pass.
- `snapshot_rejected` or `snapshot_error`: the runtime did not publish it.
- `published` or `partially_published`: a snapshot reached the shared index.
- `consumed_unchanged`: accepted staging duplicated the candidate/path's latest
  snapshot and was consumed without a new version.

## Permission boundary

The runtime owns shared-dir writes. It atomically claims staging and publishes
completed snapshots and the index; peers receive only Tool Views and explicit
candidate-local copies made through the runtime. Filesystem read-only mode is
advisory on both Linux and Windows when workers run as the same OS user. Strong
isolation requires a host sandbox, distinct OS users, or ACLs.
