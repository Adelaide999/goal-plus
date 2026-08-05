from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "vliw-kernel-optimization"
WORKSPACE = EXAMPLE / "workspace"
pytestmark = pytest.mark.example


def test_vliw_public_baseline_emits_goal_plus_metric() -> None:
    completed = subprocess.run(
        [sys.executable, ".goal-plus-verifiers/vliw_score.py"],
        cwd=WORKSPACE,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "cycles": 147734.0
    }


def test_vliw_prompt_is_a_role_routed_goal_not_a_static_spec() -> None:
    prompt = (EXAMPLE / "pi-goal-prompt.md").read_text(encoding="utf-8")
    first_line = prompt.splitlines()[0]

    assert first_line.startswith("/goal-plus main=")
    assert " annotator=" in first_line
    assert " workers=" in first_line
    assert "max_parallel=2" in first_line
    assert "examples/vliw-kernel-optimization/workspace" in prompt
    assert ".goal-plus-verifiers/vliw_score.py" in prompt
    assert "search_freeze_spec" not in prompt
    assert "SearchSpec" not in prompt


def test_vliw_example_contains_only_public_evaluation_assets() -> None:
    required = (
        "problem.py",
        "solution.py",
        "runner.py",
        "verifier.py",
        "test_cases/public_cases.json",
        "public_tests/smoke_test.py",
        ".goal-plus-verifiers/vliw_score.py",
    )
    assert all((WORKSPACE / path).is_file() for path in required)
    assert not any("hidden" in path.name.lower() for path in EXAMPLE.rglob("*"))
    assert (EXAMPLE / "LICENSE.edgebench").is_file()
