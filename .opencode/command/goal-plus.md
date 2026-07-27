---
description: 运行目标，并可选择升级到 Agentic Search
agent: goal-plus-orchestrator
subtask: false
---
使用 `goal-plus` skill 运行此目标。

采取行动前：
1. 使用 skill 工具加载 `goal-plus` skill。
2. 将 @.opencode/skills/goal-plus/SKILL.md 作为必需工作流参考。
3. 首先为原始目标调用 `goal_plus_create`。
4. 如果任务升级到 Search Mode，调用内部 `search` skill 并遵循其工作流。
5. 如果 `goal-plus` skill 或 goal-plus MCP 工具不可用，停止并报告缺失依赖。

目标：
$ARGUMENTS
