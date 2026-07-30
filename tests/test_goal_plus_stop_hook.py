from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from goal_plus.goal_plus import FileGoalPlusRuntime


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "hooks" / "goal_plus_stop.py"
HOOK_CLI = [
    sys.executable,
    "-m",
    "goal_plus.server",
    "--goal-plus-host-hook",
]


def _stop_hook_events(search_root: Path) -> list[dict]:
    event_dir = search_root / "host-logs" / "codex-hook-events"
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(event_dir.glob("*.json"))
    ]


def _run_hook(tmp_path: Path, search_root: Path, hook_input: dict | None = None, **env):
    run_env = {
        **os.environ,
        "GOAL_PLUS_SEARCH_ROOT": str(search_root),
        "GOAL_PLUS_PROJECT_ROOT": str(tmp_path),
        **{key: str(value) for key, value in env.items()},
    }
    return subprocess.run(
        HOOK_CLI,
        cwd=tmp_path,
        input=json.dumps(hook_input or {}),
        text=True,
        capture_output=True,
        check=False,
        env=run_env,
    )


def test_legacy_stop_hook_script_still_runs(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"

    result = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=tmp_path,
        input="{}",
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "GOAL_PLUS_SEARCH_ROOT": str(search_root),
            "GOAL_PLUS_PROJECT_ROOT": str(tmp_path),
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_stop_hook_allows_when_no_goal_state_and_does_not_create_state(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"

    result = _run_hook(tmp_path, search_root)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert not search_root.exists()


def test_stop_hook_allows_unbound_active_goal_without_session_match(
    tmp_path: Path,
) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")

    result = _run_hook(tmp_path, search_root, {"stop_reason": "done"})

    assert result.returncode == 0
    assert result.stdout == ""

    events = runtime.list_events(record.goal_plus_id)
    assert events[-1]["event_type"] == "session_gate_skipped"
    assert events[-1]["payload"]["reason"] == "no_matching_session"
    hook_event = _stop_hook_events(search_root)[0]
    assert hook_event["decision"] == "skipped"
    assert hook_event["reason"] == "no_matching_session"
    assert hook_event["goal_plus_id"] == record.goal_plus_id


def test_stop_hook_blocks_active_goal_mode_for_full_goal_audit(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Tidy docs wording")
    runtime.record_triage(
        record.goal_plus_id,
        {
            "is_optimization": False,
            "confidence": "high",
            "recommended_phase": "goal",
            "reasons": ["qualitative docs task"],
        },
    )

    runtime.activate_session(
        record.goal_plus_id,
        {
            "host": "codex",
            "session_id": "session-current",
            "transcript_path": "/tmp/current.jsonl",
        },
    )

    result = _run_hook(
        tmp_path,
        search_root,
        {
            "hook_event_name": "Stop",
            "session_id": "session-current",
            "stop_reason": "end_turn",
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "该修订版的完整原始目标" in payload["reason"]
    assert "Tidy docs wording" in payload["reason"]
    assert "created_at_utc" in payload["reason"]
    assert "checked_at_utc" in payload["reason"]
    assert "goal_plus_set_status" in payload["reason"]
    assert runtime.list_events(record.goal_plus_id)[-1]["event_type"] == "gate_blocked"

    hook_event = _stop_hook_events(search_root)[0]
    assert hook_event["schema_version"] == 1
    assert hook_event["invocation_id"].startswith("hook_")
    assert hook_event["hook_event_name"] == "Stop"
    assert hook_event["outcome"] == "completed"
    assert hook_event["decision"] == "block"
    assert hook_event["goal_plus_id"] == record.goal_plus_id
    assert hook_event["session_id"] == "session-current"
    assert hook_event["stop_reason"] == "end_turn"
    assert hook_event["duration_ms"] >= 0
    assert hook_event["started_at"] <= hook_event["finished_at"]
    assert hook_event["error_type"] is None
    assert hook_event["error"] is None
    assert "prompt" not in hook_event
    assert "transcript_path" not in hook_event
    assert "continuation_prompt" not in hook_event


def test_explicit_gate_call_is_not_counted_as_automatic_stop_hook(
    tmp_path: Path,
) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")

    runtime.gate(record.goal_plus_id, event="stop", context={})

    assert _stop_hook_events(search_root) == []


def test_stop_hook_records_allowed_terminal_goal(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")
    runtime.activate_session(
        record.goal_plus_id,
        {"host": "codex", "session_id": "session-terminal"},
    )
    runtime.set_status(
        record.goal_plus_id,
        status="complete",
        reason="verified",
        evidence=[{"kind": "test", "path": "evidence.json"}],
    )

    result = _run_hook(
        tmp_path,
        search_root,
        {
            "hook_event_name": "Stop",
            "session_id": "session-terminal",
            "goal_plus_id": record.goal_plus_id,
            "stop_reason": "end_turn",
        },
    )

    assert result.returncode == 0
    assert "systemMessage" in json.loads(result.stdout)
    hook_event = _stop_hook_events(search_root)[0]
    assert hook_event["decision"] == "allow"
    assert hook_event["outcome"] == "completed"
    assert hook_event["goal_plus_id"] == record.goal_plus_id


def test_stop_hook_records_failure_and_still_fails_open(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    goal_dir = search_root / "goal-plus" / "gp_999"
    goal_dir.mkdir(parents=True)
    (goal_dir / "goal.json").write_text("{", encoding="utf-8")

    result = _run_hook(
        tmp_path,
        search_root,
        {
            "hook_event_name": "Stop",
            "session_id": "session-broken",
            "goal_plus_id": "gp_999",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "allowing host action because hook failed" in result.stderr
    hook_event = _stop_hook_events(search_root)[0]
    assert hook_event["decision"] == "error"
    assert hook_event["outcome"] == "failed"
    assert hook_event["goal_plus_id"] == "gp_999"
    assert hook_event["error_type"] == "JSONDecodeError"
    assert 0 < len(hook_event["error"]) <= 1024


def test_stop_hook_records_each_invocation_separately(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    runtime.create_goal("Optimize model throughput")

    for _ in range(2):
        result = _run_hook(
            tmp_path,
            search_root,
            {"hook_event_name": "Stop", "session_id": "unmatched"},
        )
        assert result.returncode == 0

    hook_events = _stop_hook_events(search_root)
    assert len(hook_events) == 2
    assert len({event["invocation_id"] for event in hook_events}) == 2


def test_stop_hook_can_target_explicit_goal_id(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    first = runtime.create_goal("Optimize kernel")
    second = runtime.create_goal("Tidy docs")
    runtime.record_triage(
        second.goal_plus_id,
        {
            "is_optimization": False,
            "confidence": "high",
            "recommended_phase": "goal",
            "reasons": ["qualitative docs task"],
        },
    )

    result = _run_hook(tmp_path, search_root, GOAL_PLUS_ID=first.goal_plus_id)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert runtime.list_events(first.goal_plus_id)[-1]["event_type"] == "gate_blocked"


def test_post_tool_use_goal_plus_create_binds_main_session(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")

    result = _run_hook(
        tmp_path,
        search_root,
        {
            "hook_event_name": "PostToolUse",
            "session_id": "session-main",
            "transcript_path": "/tmp/main.jsonl",
            "tool_name": "mcp__goal-plus__goal_plus_create",
            "tool_response": {"goal_plus_id": record.goal_plus_id},
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    updated = runtime.status(record.goal_plus_id)
    assert updated.active_session is not None
    assert updated.active_session.host == "codex"
    assert updated.active_session.session_id == "session-main"
    assert updated.active_session.transcript_path == "/tmp/main.jsonl"
    assert updated.active_session.state == "attached"


def test_post_tool_use_goal_plus_create_ignores_subagent_context(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")

    result = _run_hook(
        tmp_path,
        search_root,
        {
            "hook_event_name": "PostToolUse",
            "session_id": "session-main",
            "agent_id": "agent-sub",
            "agent_type": "search_candidate_agent",
            "agent_transcript_path": "/tmp/subagent.jsonl",
            "tool_name": "mcp__goal-plus__goal_plus_create",
            "tool_response": {"goal_plus_id": record.goal_plus_id},
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert runtime.status(record.goal_plus_id).active_session is None


def test_stop_hook_blocks_only_current_bound_session(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")
    runtime.activate_session(
        record.goal_plus_id,
        {
            "host": "codex",
            "session_id": "session-a",
            "transcript_path": "/tmp/session-a.jsonl",
        },
    )

    interrupted = _run_hook(
        tmp_path,
        search_root,
        {"hook_event_name": "Stop", "session_id": "session-b"},
    )

    assert interrupted.returncode == 0
    assert interrupted.stdout == ""
    events = runtime.list_events(record.goal_plus_id)
    assert events[-1]["event_type"] == "session_gate_skipped"
    assert events[-1]["payload"]["current_session_id"] == "session-b"

    same_session = _run_hook(
        tmp_path,
        search_root,
        {"hook_event_name": "Stop", "session_id": "session-a"},
    )

    assert same_session.returncode == 0
    payload = json.loads(same_session.stdout)
    assert payload["decision"] == "block"
    assert "判断原始目标" in payload["reason"]


def test_stop_hook_disable_env_allows_without_gate_event(tmp_path: Path) -> None:
    search_root = tmp_path / ".search"
    runtime = FileGoalPlusRuntime(search_root)
    record = runtime.create_goal("Optimize model throughput")
    before = runtime.list_events(record.goal_plus_id)

    result = _run_hook(
        tmp_path,
        search_root,
        GOAL_PLUS_STOP_HOOK_DISABLED="1",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert runtime.list_events(record.goal_plus_id) == before
    assert _stop_hook_events(search_root) == []
