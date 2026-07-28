---
description: /goal-plus 优化目标的旧兼容别名
agent: goal-plus-orchestrator
subtask: false
---

对这个旧优化命令使用 `goal-plus` skill。该命令只是兼容别名；`/goal-plus` 是规范用户入口。

采取行动前：
1. 使用 skill 工具加载 `goal-plus` skill。
2. 将 @.opencode/skills/goal-plus/SKILL.md 作为必需工作流参考。
3. 不要绕过 `/goal-plus` triage、自主 spec discovery、Search Mode gate 或最终原始目标审计。
4. 只有 Goal Plus 进入 Search Mode 后才调用内部 `search` skill。
5. 如果 `goal-plus` skill 或 goal-plus MCP 工具不可用，停止并报告缺失依赖。

目标：

$ARGUMENTS
