---
name: goal-plus
description: 运行 Claude Code 目标，并可通过 goal-plus MCP server 升级到 Agentic Search。
---

# Claude Code 的 Goal Plus

对 `/goal-plus` 使用此 skill。成功标准可度量且已冻结时，它可以升级为多候选
Agentic Search。使用 `goal-plus` MCP server 暴露的逻辑 `goal_plus_*` 和 `search_*`
工具；Claude Code 可能显示 server 前缀，按最后的逻辑工具名匹配。

## 工作流

1. 调用 `goal_plus_create(raw_goal=...)`。目标可用 `mode=autonomous` 开头，表示充足且
   可续期的候选探索（省略时默认）；也可用 `mode=probe` 表示短期可行性、潜力和阻塞因素
   探查。运行时把前缀替换为 `raw_goal` 末行的规范中文指引；它不是 phase、Search strategy
   或运行时字段。
2. 检查足够上下文以分类任务。
3. 调用 `goal_plus_record_triage`。
4. triage 选择 Goal Mode 时，在当前工作区正常工作。不要在 Goal Mode 创建 SearchSpec。
5. triage 选择 Spec Discovery Mode 时，确定 baseline、metric、正确性门禁、编辑范围、
   verifier 产物、预算和提升规则。ranking verifier 必须输出最终 JSON 对象，其中包含有限
   数值类型的 `spec.metric_name`；文件应放在源码拥有的 `.goal-plus-verifiers/` 等路径，
   绝不能放在 `.gp/` 或 `.search/`。`expected_outputs` 只列出产物路径/glob，
   不解析 stdout。verifier 必须保持候选工作区只读，并使用唯一的
   `GOAL_PLUS_VERIFIER_TMPDIR`/`TMPDIR`（或 Python `tempfile`）存放临时输出；
   并行 Search 下固定 `/tmp` 路径不安全。冻结会在消耗候选预算前拒绝工作区副作用。
   使用 `goal_plus_save_spec_draft` 保存完整契约。
   对 AscendC Direct Invoke 场景，记录 `scenario="ascendc_direct_invoke"`，完整读取
   `examples/ascendc-direct-search/SPEC_DISCOVERY.md`，遵循其 request schema 和模板，
   并针对固定 Git commit 运行 `materialize_knowledge.py` 生成任务局部 `_skills/`。
   不要复制 live Skill 目录。主 agent 生成 Golden、cases、verifier、baseline 和 SearchSpec。
   冻结前使用 JSON Schema validator 按
   `examples/ascendc-direct-search/request.schema.json` 校验
   `_task/operator_request.json`。不要要求用户准备任务目录或编写 verifier；只支持
   Direct Invoke，不调用外部 AscendC Agent、plugin 或编排工作流。
6. 只有已保存 draft 的 `confidence="high"` 且没有 open question 时才进入 Search Mode。
7. Search 是自主升级。draft 达到高置信度且无 open question 后，直接进入 Search Mode gate，
   不要要求用户批准 verifier、metric、编辑范围、提升规则或 mode 变化。用户提示不是必需条件。
8. `origin="initial"` 或 `origin="in_progress"` 仅作为 provenance，不能影响准入。
9. 调用 `search_freeze_spec` 等 Search Mode 工具前，调用
   `goal_plus_gate(event="pre_tool_use", context={"tool_name": "search_freeze_spec"})`。
10. 在 Search Mode 使用内部 `search` skill：`search_freeze_spec`、`search_create`、
    `search_plan_next`、`search_start_batch`、`search_start_agent_session`、最终
    `search_run_verifier`、`search_select` 和 `search_promote`。
11. `search_create` 后调用 `goal_plus_link_search_run`。
12. 选择并提升后调用 `goal_plus_record_search_result`。它只预留规范报告路径，
    不生成报告文件；此时不要调用 `search_report`。
13. 原始目标审计需要另一次有 verifier 支持的 Search 时，在同一个 `goal_plus_id` 下创建并
    链接新 `run_id`，然后重复 Search Mode 流程。`search_tasks` 仅追加；
    `linked_search` 是当前任务兼容视图。
14. 最后执行原始目标审计，只有原始目标满足时才调用
    `goal_plus_set_status(status="complete", evidence=[...])`。
15. 只有 Goal Plus 记录达到终态后，才对每个成功记录的 `run_id` 调用且只调用一次
    `search_report`。绝不能生成中间 Goal Plus 报告；返回两条最终报告路径。
16. 停止前调用 `goal_plus_gate(event="stop", context={})`；如果返回 continuation prompt，
    则继续工作。

## Triage Schema

```json
{
  "is_optimization": false,
  "confidence": "high",
  "recommended_phase": "goal",
  "identified_at": "initial",
  "scenario": null,
  "reasons": ["此分类正确的原因"],
  "missing": []
}
```

`recommended_phase` 只能为 `"goal"`、`"spec_discovery"` 或 `"search"`。
不要发送 `mode` 或 `reason` 字段，也不要使用 `"goal_mode"` 等值。

Goal Mode 用于普通编码、文档、审查和调查，不使用 SearchSpec。Spec Discovery Mode
用于 metric、baseline、正确性门禁或编辑范围仍不明确的优化目标。Search Mode 用于已冻结、
可度量的优化，并把候选工作区创建、verifier、选择、报告和提升委托给 Search MCP 流程。

`goal_plus_confirm_frozen_verifier` 和 `user_confirmed_frozen_verifier` 只为兼容旧 run 而
可读，是可选审计证据，不是 Search Mode 准入要求。`/goal-plus` 执行期间绝不能为它们暂停
或询问用户。

## Hook 兼容性

仓库在 `.claude/settings.json` 中提供 Claude Code Goal Plus host hook，运行
`goal-plus --goal-plus-host-hook`。`PostToolUse(goal_plus_create)` 把记录绑定到当前顶层
Claude Code `session_id`。`Stop` hook 是 `goal_plus_gate(event="stop")` 的最终后备：
每条与 session 绑定且仍 active 的记录都会收到完整原始目标和时间上下文。Claude 必须继续
或在结束前记录真实终态；worker lease 结束不是目标完成。

hook 不替代上述显式工作流调用，也未接入 `PreToolUse` 或 `SubagentStop`。因此 Search Mode
工具前要手动调用 pre-tool gate，最终回复前手动调用 stop gate。subagent 工具事件不绑定
Goal Plus 所有权。`goal_plus_gate` 不监管 worker lifecycle；Claude 前台 Agent 行为和轮次
预算由内部 `search` skill 负责。
