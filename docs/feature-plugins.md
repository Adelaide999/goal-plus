# Monitor Feature Plugins

Goal Plus monitor feature plugins are read-only projections over the durable
goal record and append-only event log. They never operate or supervise workers.

## Orchestration Plugin

The built-in `orchestration` plugin shows actual Main/subagent interaction:

```text
assignment -> worker_update -> result -> decision
```

Each dispatch exposes its assignment summary, opaque worker identity, current
status, generation, `launching`/`bound` state, launch deadline, and stale-result
count. It does not expose private reasoning, transcript contents, or transcript
paths.

The plugin is enabled by default. Select it explicitly or disable plugins with:

```text
goal_plus_monitor_snapshot(feature_plugins=["orchestration"])
goal_plus_monitor_snapshot(feature_plugins=[])
```

Hosts may annotate `goal_plus_record_work_event.metadata` with their native
operation name:

```json
{
  "orchestration_monitor": {
    "native_operation": "spawn_agent",
    "direction": "main_to_subagent",
    "semantic_event": "assignment"
  }
}
```

Codex normally records `spawn_agent`, `wait_agent`, and `followup_task`. Pi's
wrapper records `pi_goal_plus_run_work_item` and `goal-plus-pi-worker`. The
native commands differ, while the projected assignment, result, and Main-owned
decision flow stays the same.
