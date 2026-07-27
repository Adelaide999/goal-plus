"""Shared host-asset assertions consolidated from per-host test files.

Codex and Claude Code share the bulk of their ``goal-plus`` SKILL.md content
(same modes, same MCP tool names, same lifecycle language). Pi and OpenCode
diverge significantly — different MCP tool surfaces, different concepts — so
their dedicated tests remain in ``tests/test_<host>_assets.py``.

The two helpers below also let each host's budget-planning test delegate the
cross-host shared claims and keep only its unique extras inline.
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def assert_common_budget_planning_claims(text: str) -> None:
    """Budget-planning claims shared by every host's search SKILL.md.

    Each host's test should call this after reading its own SKILL.md, then
    add host-specific budget-planning assertions.
    """
    normalized = " ".join(text.split())
    assert "SearchSpec 与预算" in text
    assert "建议 4" in text
    assert (
        "不同 candidate id 本身不提供"
        in normalized
    )
    assert "理论或结构限制" in normalized or "资源瓶颈" in normalized


def assert_common_goal_plus_skill_text(text: str) -> None:
    """Goal Plus SKILL.md claims shared by codex and claude.

    Pi and opencode have meaningfully different SKILL.md content (different
    MCP tool names, different concepts); they should NOT call this helper.
    """
    assert "name: goal-plus" in text
    assert "goal_plus_create" in text
    assert "goal_plus_record_triage" in text
    assert "goal_plus_save_spec_draft" in text
    assert "goal_plus_gate" in text
    assert "mode_hint" not in text
    assert "Goal Mode" in text
    assert "Spec Discovery Mode" in text
    assert "Search Mode" in text
    assert '"recommended_phase": "goal"' in text
    assert "goal_mode" in text
    assert "不要发送" in text
    assert "`mode`" in text
    assert "`reason`" in text
    assert "Search 是自主升级" in text
    assert "不要要求用户" in text
    assert (
        "Goal Mode 下不要创建 SearchSpec" in text
        or "不要在 Goal Mode 创建 SearchSpec" in text
    )
    assert "search_freeze_spec" in text
    assert "原始目标审计" in text
    assert "mode=autonomous" in text
    assert "mode=probe" in text
    assert ".goal-plus-verifiers/" in text
    assert "`expected_outputs`" in text


@pytest.mark.parametrize("host_dir", ["codex", "claude"])
def test_host_goal_plus_skill_records_modes_and_mcp_tools(host_dir: str) -> None:
    skill_path = ROOT / f".{host_dir}" / "skills" / "goal-plus" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")

    assert_common_goal_plus_skill_text(text)

    if host_dir == "codex":
        assert "/goal-plus-with-final-check" in text
        assert "/goal-plus edit" in text
        assert "/goal-plus mode=autonomous" in text
        assert "/goal-plus mode=probe" in text
        assert "`raw_goal` 的规范末行" in text
        assert "候选 lease 结束绝不会完成" in text
        assert "不单独存储任务 deadline" in text
        assert "把最新用户消息视为" in text
        assert "范围、交付物或成功标准" in text
        assert "goal_plus_update_goal" in text
        assert "在修订或恢复前先澄清" in text
        assert "不要仅因 Goal Plus 记录处于 active" in text
        assert "goal_plus_prepare_final_check" in text
        assert "goal_plus_submit_final_check" in text
        assert "spawn_agent" in text
        assert 'fork_turns="none"' in text
        assert "绝不能代表审查员提交结论" in text
    else:  # claude
        normalized = " ".join(text.split())
        assert "规范中文指引" in text
        assert "worker lease 结束不是目标完成" in normalized
