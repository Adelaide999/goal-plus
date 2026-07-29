# Worker Budget Smoke Evidence

This file records the manual smoke test used to verify Codex worker budget
behavior for the adapter implementation. Raw logs are under the
gitignored `.gp/smoke-logs/` directory in this workspace.

## Codex Parent Watchdog

Command log: `.gp/smoke-logs/codex-worker-budget.jsonl`

Observed behavior:

- The parent Codex run received `budget_control.mode = "parent_watchdog"`.
- It spawned one child worker for a task that ran `sleep 60`.
- It waited for the 10 second watchdog window.
- The wait timed out.
- The parent interrupted the child through the available fallback
  `send_input(interrupt=true)` surface.
- The final child status was completed with a message that `sleep 60` was
  interrupted and did not complete.

Key log evidence:

```text
budget_control parent_watchdog: wait timed out after 10s; interrupt succeeded via send_input(interrupt=true).
Final child status: completed - sleep 60 was interrupted/aborted and did not complete.
```
