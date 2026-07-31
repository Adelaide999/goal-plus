"""System tests: drive a real host code agent and assert the main agent's final
JSON report matches the expected scenario contract.

These tests are skipped unless `-m st` is passed. They require:
  - Codex on PATH
  - goal-plus MCP server configured for that host

Each test loads a prompt from tests/st/prompts/<scenario>.md, runs the selected
host in a temporary project root, then parses the st_report JSON block from
stdout.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from .conftest import load_prompt
from .helpers.report_parser import StReport, extract_st_report, find_run_id_in_stdout


SCENARIO_CASES = [
    pytest.param(
        "codex_redispatch",
        marks=(pytest.mark.st, pytest.mark.st_codex),
        id="codex_redispatch",
    ),
    pytest.param(
        "codex_circle_packing_cycle",
        marks=(pytest.mark.st, pytest.mark.st_codex),
        id="codex_circle_packing_cycle",
    ),
    pytest.param(
        "codex_rolling_followup",
        marks=(pytest.mark.st, pytest.mark.st_codex),
        id="codex_rolling_followup",
    ),
    pytest.param(
        "codex_parallel_loop_cycle",
        marks=(pytest.mark.st, pytest.mark.st_codex),
        id="codex_parallel_loop_cycle",
    ),
    pytest.param(
        "codex_time_advisory",
        marks=(pytest.mark.st, pytest.mark.st_codex),
        id="codex_time_advisory",
    ),
    pytest.param(
        "codex_autoresearch_lease",
        marks=(pytest.mark.st, pytest.mark.st_codex),
        id="codex_autoresearch_lease",
    ),
]


def _assert_common_contract(report: StReport, scenario: str) -> None:
    assert report is not None, (
        "no st_report JSON block found in host stdout — main agent did not "
        "emit the ST output contract; check the log file for the full session"
    )
    assert report.scenario == scenario, (
        f"scenario mismatch: expected {scenario}, got {report.scenario}"
    )
    assert report.run_id, "run_id missing in st_report"
    # candidates is allowed to be empty only if extra.error is set
    if not report.candidates:
        assert report.extra.get("error"), (
            "candidates empty but no error reason in extra.error"
        )
        pytest.skip(f"host run failed before producing candidates: {report.extra['error']}")
    assert report.selected_candidate_id, "selected_candidate_id missing"
    assert report.best_score is not None, "best_score missing"
    assert report.report_path, "report_path missing"


def _assert_codex_redispatch(report: StReport) -> None:
    assert len(report.candidates) >= 1, (
        f"codex redispatch should have >=1 candidate, got {len(report.candidates)}"
    )
    extra = report.extra
    assert extra.get("host") == "codex"
    assert extra.get("model") == "gpt-5.6-terra"
    assert extra.get("same_candidate") is True
    first = extra.get("first_agent_session_id")
    redispatched = extra.get("redispatch_agent_session_id")
    assert first and redispatched and first != redispatched, (
        "redispatch must create a second, distinct agent_session_id"
    )
    assert extra.get("redispatch_budget_control_mode") == "parent_watchdog"
    assert len(extra.get("verifier_scores") or []) >= 1


def _assert_codex_circle_packing_cycle(report: StReport) -> None:
    expected_ids = ["c001", "c002"]
    assert [candidate.get("candidate_id") for candidate in report.candidates] == expected_ids, (
        "Codex cycle must report exactly c001 and c002 in order"
    )
    assert all(
        candidate.get("status") == "evaluated"
        and int(candidate.get("iterations") or 0) >= 1
        for candidate in report.candidates
    ), "both Codex cycle candidates must be evaluated with verifier iterations"

    extra = report.extra
    assert extra.get("host") == "codex"
    assert extra.get("model") == "gpt-5.6-terra"
    assert extra.get("rounds") == 1
    assert extra.get("batch_sizes") == [2]
    session_ids = extra.get("agent_session_ids") or []
    assert len(session_ids) == 2, "cycle must report two agent_session_id values"
    assert len(set(session_ids)) == 2, "cycle agent_session_id values must be distinct"


def _assert_codex_rolling_followup(report: StReport) -> None:
    assert [candidate.get("candidate_id") for candidate in report.candidates] == [
        "c001",
        "c002",
    ]
    assert all(
        candidate.get("status") == "evaluated"
        and int(candidate.get("iterations") or 0) >= 1
        for candidate in report.candidates
    )
    extra = report.extra
    assert extra.get("host") == "codex"
    assert extra.get("model") == "gpt-5.6-terra"
    assert extra.get("wait_mode") == "wait_any"
    session_ids = extra.get("initial_agent_session_ids") or []
    assert len(session_ids) == 2 and len(set(session_ids)) == 2
    assert len(extra.get("task_names") or []) == 2
    assert extra.get("continued_candidate_id") == extra.get(
        "first_completed_candidate_id"
    )
    assert extra.get("continued_agent_session_id") in session_ids
    assert extra.get("continue_tool") == "followup_task"
    assert extra.get("same_worker_continuation") is True


def _assert_codex_parallel_loop_cycle(report: StReport) -> None:
    assert [candidate.get("candidate_id") for candidate in report.candidates] == [
        "c001",
        "c002",
    ]
    assert all(
        candidate.get("status") == "evaluated"
        and int(candidate.get("iterations") or 0) >= 1
        for candidate in report.candidates
    )
    extra = report.extra
    assert extra.get("host") == "codex"
    assert extra.get("model") == "gpt-5.6-luna"
    assert extra.get("orchestration_mode") == "parallel_loops"
    assert extra.get("plans_count") == 1
    session_ids = extra.get("initial_agent_session_ids") or []
    assert len(session_ids) == 2 and len(set(session_ids)) == 2
    assert len(extra.get("task_names") or []) == 2
    assert extra.get("continued_candidate_id") == extra.get(
        "first_completed_candidate_id"
    )
    assert extra.get("continued_agent_session_id") in session_ids
    assert extra.get("same_worker_continuation") is True
    assert isinstance(extra.get("best_observed_after_first_completion"), (int, float))
    assert extra.get("best_candidate_observed_after_first_completion") in {
        "c001",
        "c002",
    }
    assert extra.get("new_candidates_after_initial") == 0
    assert extra.get("observed_worker_models") == ["gpt-5.6-luna"]


def _assert_codex_time_advisory(report: StReport) -> None:
    assert len(report.candidates) == 1
    assert report.candidates[0].get("status") == "evaluated"
    assert int(report.candidates[0].get("iterations") or 0) >= 1
    assert report.extra.get("host") == "codex"
    assert report.extra.get("model") == "gpt-5.6-terra"
    assert report.extra.get("agent_session_id")


def _assert_codex_autoresearch_lease(report: StReport) -> None:
    assert len(report.candidates) == 1
    assert report.candidates[0].get("status") == "evaluated"
    assert int(report.candidates[0].get("iterations") or 0) >= 1
    extra = report.extra
    assert extra.get("host") == "codex"
    assert extra.get("model") == "gpt-5.6-terra"
    assert extra.get("agent_session_id")
    assert extra.get("min_runtime_seconds") == 300
    assert extra.get("max_runtime_seconds") == 420
    assert extra.get("parent_closeout_after_seconds") == 375


SCENARIO_ASSERTIONS = {
    "codex_redispatch": _assert_codex_redispatch,
    "codex_circle_packing_cycle": _assert_codex_circle_packing_cycle,
    "codex_rolling_followup": _assert_codex_rolling_followup,
    "codex_parallel_loop_cycle": _assert_codex_parallel_loop_cycle,
    "codex_time_advisory": _assert_codex_time_advisory,
    "codex_autoresearch_lease": _assert_codex_autoresearch_lease,
}


@pytest.mark.parametrize("scenario", SCENARIO_CASES)
def test_scenario(
    scenario: str,
    st_runner,
    st_project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if scenario == "codex_time_advisory":
        monkeypatch.setenv(
            "GOAL_PLUS_OUTER_DEADLINE_AT",
            "1970-01-01T00:00:00Z",
        )
    prompt = load_prompt(scenario)
    timeout = 1200 if scenario == "codex_autoresearch_lease" else 2400
    result = st_runner.run_streaming(prompt, scenario=scenario, timeout=timeout)

    # Always print the log path so debugging is one click away
    print(f"\n[{scenario}] log: {result.log_path}")
    print(f"[{scenario}] exit: {result.returncode}, timed_out: {result.timed_out}")

    assert not result.timed_out, (
        f"host run timed out for {scenario}; see {result.log_path}"
    )
    # Some hosts may exit non-zero even on useful agent output; the st_report
    # block is the source of truth, not the exit code.
    report = extract_st_report(result.stdout)
    if report is None:
        run_id_fallback = find_run_id_in_stdout(result.stdout)
        pytest.fail(
            f"no st_report JSON block in stdout for {scenario} "
            f"(fallback run_id guess: {run_id_fallback}); full log: {result.log_path}"
        )

    _assert_common_contract(report, scenario)
    SCENARIO_ASSERTIONS[scenario](report)

    if scenario == "codex_parallel_loop_cycle":
        run_dir = st_project_root / ".gp" / "runs" / report.run_id
        run_payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        spec_payload = json.loads(
            (
                st_project_root
                / ".gp"
                / "specs"
                / run_payload["frozen_spec_id"]
                / "frozen_spec.json"
            ).read_text(encoding="utf-8")
        )
        assert spec_payload["spec"]["strategy"]["orchestration_mode"] == "parallel_loops"
        assert len(list((run_dir / "plans").glob("*.json"))) == 1
        assert len(list((run_dir / "candidates").glob("*/candidate.json"))) == 2
        session_paths = list((run_dir / "agent_sessions").glob("*.json"))
        assert len(session_paths) == 2
        sessions = {
            payload["agent_session_id"]: payload
            for payload in (
                json.loads(path.read_text(encoding="utf-8"))
                for path in session_paths
            )
        }
        continued_id = report.extra["continued_agent_session_id"]
        assert (
            sessions[continued_id]["candidate_id"]
            == report.extra["continued_candidate_id"]
        )
        assert sessions[continued_id]["launch"]["tool"] == "followup_task"
        assert run_payload["best_candidate_id"] == report.selected_candidate_id
        assert run_payload["best_score"] == pytest.approx(report.best_score)

    if scenario == "codex_time_advisory":
        agent_session_id = report.extra["agent_session_id"]
        evidence_path = (
            st_project_root
            / ".gp"
            / "host-logs"
            / "codex-time-advisory"
            / "sent"
            / f"{agent_session_id}.json"
        )
        assert evidence_path.is_file(), (
            "Codex Search candidate PostTool hook did not record an advisory "
            f"for {agent_session_id}"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert evidence["agent_session_id"] == agent_session_id
        assert evidence["run_id"] == report.run_id
        assert evidence["deadline_source"] == "outer_deadline"
        assert evidence["remaining_seconds"] == 0
        assert evidence["average_submission_seconds"] > 0
        assert evidence["total_verifier_count"] >= 1

    if scenario == "codex_autoresearch_lease":
        agent_session_id = report.extra["agent_session_id"]
        evidence_path = (
            st_project_root
            / ".gp"
            / "host-logs"
            / "codex-autoresearch-leases"
            / f"{agent_session_id}.json"
        )
        assert evidence_path.is_file(), (
            "Codex Search candidate did not persist AutoResearch lease evidence "
            f"for {agent_session_id}"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        started_at = datetime.fromisoformat(
            evidence["started_at"].replace("Z", "+00:00")
        )
        first_stop_at = datetime.fromisoformat(
            evidence["first_stop_attempt_at"].replace("Z", "+00:00")
        )
        released_at = datetime.fromisoformat(
            evidence["released_at"].replace("Z", "+00:00")
        )
        lease_deadline_at = datetime.fromisoformat(
            evidence["lease_deadline_at"].replace("Z", "+00:00")
        )
        assert evidence["status"] == "released"
        assert evidence["release_reason"] == "lease_satisfied"
        assert evidence["min_runtime_seconds"] == 300
        assert evidence["max_runtime_seconds"] == 420
        assert evidence["parent_closeout_after_seconds"] == 375
        assert evidence["blocked_stop_attempts"] >= 1, (
            "worker never attempted an early stop, so SubagentStop continuation "
            "was not exercised"
        )
        assert (first_stop_at - started_at).total_seconds() < 300
        assert (released_at - started_at).total_seconds() >= 300
        assert evidence["elapsed_seconds"] >= 300
        assert evidence["elapsed_seconds"] < 375
        assert lease_deadline_at == started_at + timedelta(seconds=300)
        assert evidence["lease_precedes_parent_closeout"] is True
        assert evidence["lease_precedes_parent_hard_deadline"] is True
        assert evidence["released_within_parent_closeout_budget"] is True
        assert evidence["released_within_max_runtime"] is True
        assert 300 < evidence["parent_closeout_after_seconds"] < 420

    # Smoke keyword check: run_id must appear somewhere in the raw output
    assert report.run_id in result.stdout, (
        f"run_id {report.run_id} not found in raw stdout — likely the main agent "
        f"hallucinated it"
    )
