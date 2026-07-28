from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
from pathlib import Path

import pytest

from goal_plus.models import SearchSpec
from goal_plus.runtime import FileSearchRuntime
from tests._runtime_helpers import make_project, spec_for


def _search_with_candidates(
    tmp_path: Path,
    count: int,
) -> tuple[FileSearchRuntime, str, list[tuple[str, str, Path]]]:
    project = make_project(tmp_path)
    (project / "evaluator.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "VALUE = Path('initial_program.py').read_text().split('=', 1)[1].strip()\n"
        "print(json.dumps({'combined_score': float(VALUE)}))\n",
        encoding="utf-8",
    )
    spec_data = spec_for(project, max_candidates=count).model_dump(mode="json")
    spec_data["workspace"] = {"backend": "git_worktree"}
    runtime = FileSearchRuntime(tmp_path / ".gp")
    frozen = runtime.freeze_spec(
        SearchSpec.model_validate(spec_data),
        [project / "evaluator.py"],
    )
    run_id = runtime.create_run(frozen.frozen_spec_id)
    search_plan = runtime.plan_next(run_id, requested_k=count)
    tasks = runtime.start_batch(run_id, search_plan.plan_id)
    candidates = []
    for task in tasks:
        session = runtime.start_agent_session(run_id, task.candidate_id)
        runtime.get_agent_context(session.agent_session_id)
        candidates.append(
            (task.candidate_id, session.agent_session_id, task.workspace)
        )
    return runtime, run_id, candidates


def _git(workspace: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=workspace, text=True).strip()


def test_global_plan_joins_concurrent_candidate_plans_with_verifier_results(
    tmp_path: Path,
) -> None:
    runtime, run_id, candidates = _search_with_candidates(tmp_path, 2)
    first, second = candidates

    with ThreadPoolExecutor(max_workers=2) as pool:
        empty_views = list(
            pool.map(runtime.get_global_plan, [first[1], second[1]])
        )
    assert empty_views == [[], []]

    descriptions = ["Raise the first candidate score", "Try a larger peer score"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = list(
            pool.map(
                lambda args: runtime.submit_iteration_plan(*args),
                [(first[1], descriptions[0]), (second[1], descriptions[1])],
            )
        )
    assert [entry["description"] for entry in submitted] == descriptions
    assert all(
        entry["score"] is None
        and entry["disposition"] is None
        and entry["commit"] is None
        for entry in submitted
    )

    plan_paths = [
        runtime.root_dir
        / "runs"
        / run_id
        / "candidates"
        / candidate_id
        / "plans"
        / "iteration-0001.json"
        for candidate_id, _, _ in candidates
    ]
    original_plans = [path.read_bytes() for path in plan_paths]
    assert runtime.submit_iteration_plan(first[1], descriptions[0]) == submitted[0]
    with pytest.raises(RuntimeError, match="already has a different plan"):
        runtime.submit_iteration_plan(first[1], "Replace the immutable plan")

    for (_, session_id, workspace), value in zip(candidates, (1, 2), strict=True):
        (workspace / "initial_program.py").write_text(
            f"VALUE = {value}\n", encoding="utf-8"
        )
        report = runtime.run_verifier(
            run_id,
            runtime._load_agent_session_by_id(session_id).candidate_id,
            agent_session_id=session_id,
        )
        assert report.disposition == "keep"

    runtime.submit_iteration_plan(second[1], "Check whether a smaller score helps")
    (second[2] / "initial_program.py").write_text("VALUE = 1\n", encoding="utf-8")
    discarded = runtime.run_verifier(
        run_id,
        second[0],
        agent_session_id=second[1],
    )
    assert discarded.disposition == "discard"

    view = runtime.get_global_plan(first[1])
    assert [(entry["candidate_id"], entry["iteration"]) for entry in view] == [
        (first[0], 1),
        (second[0], 1),
        (second[0], 2),
    ]
    assert [entry["score"] for entry in view] == [1.0, 2.0, 1.0]
    assert [entry["disposition"] for entry in view] == [
        "keep",
        "keep",
        "discard",
    ]
    assert all(entry["commit"] for entry in view)
    assert [path.read_bytes() for path in plan_paths] == original_plans

    peer_commit = view[1]["commit"]
    subprocess.run(
        ["git", "cat-file", "-e", f"{peer_commit}^{{commit}}"],
        cwd=first[2],
        check=True,
    )
    assert _git(first[2], "show", f"{peer_commit}:initial_program.py") == "VALUE = 2"


def test_iteration_plan_enforces_settled_boundary_and_worker_ownership(
    tmp_path: Path,
) -> None:
    runtime, run_id, [candidate] = _search_with_candidates(tmp_path, 1)
    candidate_id, session_id, workspace = candidate

    context = runtime.get_agent_context(session_id)
    assert "history" not in context

    program = workspace / "initial_program.py"
    program.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Git-clean settled workspace"):
        runtime.submit_iteration_plan(session_id, "Late plan after editing")
    with pytest.raises(RuntimeError, match="requires an iteration plan"):
        runtime.run_verifier(
            run_id,
            candidate_id,
            agent_session_id=session_id,
        )
    assert runtime.list_iterations(run_id, candidate_id) == []

    parent_report = runtime.run_verifier(
        run_id,
        candidate_id,
        hypothesis="parent verification",
    )
    assert parent_report.disposition == "keep"
    assert runtime.get_global_plan(session_id) == []

    (workspace / ".tmp" / "handoff.json").write_text("{}\n", encoding="utf-8")
    program.write_text("VALUE = 99\n", encoding="utf-8")
    subprocess.run(["git", "add", "initial_program.py"], cwd=workspace, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "manual divergence",
        ],
        cwd=workspace,
        check=True,
    )
    with pytest.raises(RuntimeError, match="settled results ledger HEAD"):
        runtime.submit_iteration_plan(session_id, "Plan from a divergent commit")

    settled_head = runtime._load_candidate_record(
        run_id, candidate_id
    ).results_ledger_git_head
    subprocess.run(
        ["git", "reset", "--hard", str(settled_head)],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="one line"):
        runtime.submit_iteration_plan(session_id, "two\nlines")

    runtime.submit_iteration_plan(session_id, "Use the planned worker refinement")
    program.write_text("VALUE = 2\n", encoding="utf-8")
    runtime.run_verifier(
        run_id,
        candidate_id,
        agent_session_id=session_id,
        hypothesis="worker-supplied text must not replace the plan",
    )

    iterations = runtime.list_iterations(run_id, candidate_id)
    assert iterations[0]["hypothesis"] == "parent verification"
    assert iterations[1]["hypothesis"] == "Use the planned worker refinement"
    assert runtime.get_global_plan(session_id) == [
        {
            "candidate_id": candidate_id,
            "iteration": 2,
            "description": "Use the planned worker refinement",
            "score": 2.0,
            "disposition": "keep",
            "commit": iterations[1]["git_head"],
        }
    ]


def test_promoted_run_rejects_stale_worker_iterations(tmp_path: Path) -> None:
    runtime, run_id, [candidate] = _search_with_candidates(tmp_path, 1)
    candidate_id, session_id, workspace = candidate
    runtime.submit_iteration_plan(session_id, "Create the promoted candidate")
    (workspace / "initial_program.py").write_text("VALUE = 1\n", encoding="utf-8")
    runtime.run_verifier(run_id, candidate_id, agent_session_id=session_id)
    runtime.select(run_id)
    patch_path = runtime.promote(run_id, candidate_id)

    record_before = runtime._load_candidate_record(run_id, candidate_id)
    head_before = _git(workspace, "rev-parse", "HEAD")
    patch_before = patch_path.read_bytes()
    global_plan_before = runtime.get_global_plan(session_id)

    with pytest.raises(RuntimeError, match="state promoted"):
        runtime.submit_iteration_plan(session_id, "Mutate after promotion")
    with pytest.raises(RuntimeError, match="state promoted"):
        runtime.run_verifier(
            run_id,
            candidate_id,
            agent_session_id=session_id,
        )
    with pytest.raises(RuntimeError, match="state promoted"):
        runtime.run_verifier(run_id, candidate_id)

    record_after = runtime._load_candidate_record(run_id, candidate_id)
    assert record_after.model_dump(mode="json") == record_before.model_dump(mode="json")
    assert _git(workspace, "rev-parse", "HEAD") == head_before
    assert patch_path.read_bytes() == patch_before
    assert runtime.get_global_plan(session_id) == global_plan_before


def test_plan_submission_is_serialized_with_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, run_id, [candidate] = _search_with_candidates(tmp_path, 1)
    _, session_id, _ = candidate
    plan_checked = threading.Event()
    release_plan = threading.Event()
    invalidation_done = threading.Event()
    errors: list[BaseException] = []
    original_assert = runtime._assert_worker_iteration_allowed

    def pause_after_plan_check(run: object, operation: str) -> None:
        original_assert(run, operation)  # type: ignore[arg-type]
        if threading.current_thread().name == "plan-submission":
            plan_checked.set()
            assert release_plan.wait(timeout=5)

    monkeypatch.setattr(
        runtime,
        "_assert_worker_iteration_allowed",
        pause_after_plan_check,
    )

    def submit_plan() -> None:
        try:
            runtime.submit_iteration_plan(session_id, "Commit before invalidation")
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def invalidate() -> None:
        try:
            runtime.invalidate_run(
                run_id,
                reason="verifier_contract_invalid",
                summary="confirmed invalid verifier contract",
                evidence=[{"kind": "reproduction"}],
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            invalidation_done.set()

    plan_thread = threading.Thread(target=submit_plan, name="plan-submission")
    plan_thread.start()
    assert plan_checked.wait(timeout=5)
    invalidation_thread = threading.Thread(target=invalidate)
    invalidation_thread.start()
    assert not invalidation_done.wait(timeout=0.1)

    release_plan.set()
    plan_thread.join(timeout=5)
    invalidation_thread.join(timeout=5)
    assert not plan_thread.is_alive()
    assert not invalidation_thread.is_alive()
    assert errors == []
    assert runtime._load_run(run_id).invalidated_at is not None
    assert runtime.get_global_plan(session_id)[0]["description"] == (
        "Commit before invalidation"
    )
    with pytest.raises(RuntimeError, match="invalidated"):
        runtime.submit_iteration_plan(session_id, "Write after invalidation")
