from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_host_assets_common import assert_common_budget_planning_claims


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.claude


def test_claude_mcp_json_registers_search_runtime() -> None:
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))

    server = data["mcpServers"]["goal-plus"]
    assert server["command"] == "goal-plus"
    assert server["args"] == ["--root", ".gp"]


def test_claude_assets_wire_goal_plus_host_hooks() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    stop_hooks = settings["hooks"]["Stop"]
    post_tool_use_hooks = settings["hooks"]["PostToolUse"]

    assert not (ROOT / ".claude" / "settings.local.json").exists()
    assert settings["hooks"].keys() == {"Stop", "PostToolUse"}
    assert stop_hooks[0]["matcher"] == ""
    assert stop_hooks[0]["hooks"][0]["type"] == "command"
    command = stop_hooks[0]["hooks"][0]["command"]
    assert command == "goal-plus --goal-plus-host-hook"
    assert "python3" not in command
    assert post_tool_use_hooks[0]["matcher"] == ""
    post_command = post_tool_use_hooks[0]["hooks"][0]["command"]
    assert post_command == "goal-plus --goal-plus-host-hook"

    text = (ROOT / "docs" / "claude-code.md").read_text(encoding="utf-8")
    assert "ships Claude Code Goal Plus host hooks" in text
    assert "PostToolUse(goal_plus_create)" in text
    assert "does not wire PreToolUse or SubagentStop hooks" in text
    assert "goal-plus --goal-plus-host-hook" in text


def test_claude_skill_uses_foreground_agent_and_generic_bind() -> None:
    text = (ROOT / ".claude" / "skills" / "search" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "search_start_agent_session" in text
    assert "search_redispatch_candidate" in text
    assert "Agent" in text
    assert "search_bind_agent_handle" in text
    assert "SendMessage" in text
    assert "background: false" in text
    assert "background subagent" not in text.lower()
    assert "## Verifier 冻结契约" in text
    assert '有限数值类型的 `spec.metric_name`' in text
    assert ".goal-plus-verifiers/" in text
    assert "`expected_outputs` 只接受" in text
    assert "GOAL_PLUS_VERIFIER_TMPDIR" in text
    assert "VerifierWorkspaceSideEffect" in text
    assert "固定 `/tmp`" in text


def test_claude_search_skill_documents_whole_run_budget_planning() -> None:
    text = (ROOT / ".claude" / "skills" / "search" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split())

    assert_common_budget_planning_claims(text)
    assert "所有轮次中不同候选工作区总数的不可变上限" in normalized
    assert "`ceil(max_candidates / max_parallel)`" in text
    assert "`max_candidates = rounds * max_parallel`" in text
    assert "`max_candidates=15`" in text
    assert "默认值 4 当作整个 run 预算" in normalized
    assert "不要调用 `search_select`" in normalized
    assert "同候选 continuation" in normalized
    assert "不代表必须启动更多工作" in normalized


def test_claude_worker_agent_calls_context_and_verifier() -> None:
    text = (ROOT / ".claude" / "agents" / "search-candidate-agent.md").read_text(
        encoding="utf-8"
    )

    assert "name: search-candidate-agent" in text
    assert "maxTurns: 8" in text
    assert "mcp__goal-plus__*" in text
    assert "search_get_agent_context" in text
    assert "search_run_verifier" in text
    assert "工作区根目录" in text
    assert "且只追加一条已验证记录" in text
    assert "hypothesis=" in text
    assert "candidate_action=stop_and_report" in text
    assert "立即返回" in text
    assert "把分配的候选思路当作假设" in text
    assert "有希望的方向" in text
    assert "固定产物数量" in text
    assert "理论或结构限制" in text


def test_claude_worker_agent_turn_budget_variants_exist() -> None:
    flash = (ROOT / ".claude" / "agents" / "search-candidate-agent-flash.md").read_text(
        encoding="utf-8"
    )
    deep = (ROOT / ".claude" / "agents" / "search-candidate-agent-deep.md").read_text(
        encoding="utf-8"
    )

    assert "name: search-candidate-agent-flash" in flash
    assert "maxTurns: 4" in flash
    assert "name: search-candidate-agent-deep" in deep
    assert "maxTurns: 16" in deep
    assert "candidate_action=stop_and_report" in flash
    assert "candidate_action=stop_and_report" in deep
    assert "把分配的候选思路当作假设" in flash
    assert "把分配的候选思路当作假设" in deep
    assert "理论或结构限制" in flash
    assert "理论或结构限制" in deep


def test_claude_search_skill_documents_tier_escalation_and_resume() -> None:
    text = (ROOT / ".claude" / "skills" / "search" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    agent = (ROOT / ".claude" / "agents" / "search-candidate-agent.md").read_text(
        encoding="utf-8"
    )

    assert "search-candidate-agent-flash" in text
    assert "search-candidate-agent-deep" in text
    assert "达到 `maxTurns` 且未记录任何 verifier iteration" in text
    assert "history 由运行时拥有，不是 `plan.md` 文件" in text
    assert "状态级恢复" in text
    assert "context.history" in text
    assert "context.iterations" in text
    assert "search_redispatch_candidate" in text
    assert "`SendMessage` 不可用" in text
    assert "不要依赖聊天 transcript" in agent


def test_claude_docs_record_log_inspection_paths() -> None:
    text = (ROOT / "docs" / "claude-code.md").read_text(encoding="utf-8")
    debug = (ROOT / "docs" / "debugging-runtime.md").read_text(encoding="utf-8")

    combined = text + "\n" + debug
    assert "--output-format stream-json" in combined
    assert "--debug-file" in combined
    assert "claude project purge" in combined
    assert "~/.claude/projects" in combined
    assert "subagents/" in combined


def test_claude_docs_state_current_host_boundary_concisely() -> None:
    text = (ROOT / "docs" / "claude-code.md").read_text(encoding="utf-8")

    assert "## Current Support" in text
    assert "Foreground Agent launch" in text
    assert "State-level redispatch" in text
    assert "Same-worker messaging" in text
    assert "instruction-driven" in text
    assert "no host-specific API copy is maintained here" in text


def test_claude_goal_plus_skill_documents_multiple_search_tasks() -> None:
    text = (ROOT / ".claude" / "skills" / "goal-plus" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "同一个 `goal_plus_id`" in text
    assert "`search_tasks` 仅追加" in text
    assert "`linked_search` 是当前任务兼容视图" in text
    assert "此时不要调用 `search_report`" in text
    assert "只有 Goal Plus 记录达到终态后" in text
    assert "绝不能生成中间 Goal Plus 报告" in text
