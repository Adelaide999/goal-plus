---
name: goal-plus
description: >
  运行自然语言目标；当任务具有可度量 verifier、有界编辑范围和有用的多候选搜索空间时，
  可选择升级到 Agentic Search。
argument-hint: 目标、源码路径，以及可选的优化/场景提示。
---

# Goal Plus Skill

Goal Plus 是 Search MCP 运行时上方的轻量 goal 层。它记录原始目标，triage 是否值得 Search，
在需要时发现冻结 spec，然后把 Search Mode 委托给内部 `search` skill。

## OpenCode 中的工具名

MCP server 配置名为 `goal-plus`，因此工具使用以下前缀：

| 运行时工具 | OpenCode 工具名 |
|---|---|
| `goal_plus_create` | `goal-plus_goal_plus_create` |
| `goal_plus_status` | `goal-plus_goal_plus_status` |
| `goal_plus_record_triage` | `goal-plus_goal_plus_record_triage` |
| `goal_plus_save_spec_draft` | `goal-plus_goal_plus_save_spec_draft` |
| `goal_plus_confirm_frozen_verifier` | `goal-plus_goal_plus_confirm_frozen_verifier`（旧版可选审计证据） |
| `goal_plus_link_search_run` | `goal-plus_goal_plus_link_search_run` |
| `goal_plus_record_search_result` | `goal-plus_goal_plus_record_search_result` |
| `goal_plus_set_status` | `goal-plus_goal_plus_set_status` |
| `goal_plus_gate` | `goal-plus_goal_plus_gate` |

Search Mode 工具使用内部 `search` skill，例如 `search_freeze_spec`、`search_create`、
`search_plan_next`、`search_start_batch`、`search_start_agent_session`、`search_select`、
`search_report` 和 `search_promote`。

任何必需 MCP 工具不可用时，停止并报告 goal-plus MCP server 未连接。不要在聊天中模拟
`.gp` 状态。

## 工作流

### 步骤 1：创建目标

调用：

```text
goal-plus_goal_plus_create(raw_goal="<用户目标>", source_path="<可选>")
```

原始目标可以用 `mode=autonomous`（默认）开头，表示充足且可续期的候选探索；也可用
`mode=probe` 表示短期可行性、潜力和阻塞因素探查。运行时会把该前缀替换为 `raw_goal`
中的一行规范中文提示；它只是探索指引，不是 Goal/Spec Discovery/Search phase 或 Search
strategy mode。模型仍根据证据决定任务保留 goal 形态还是升级到 Search Mode。

### 步骤 2：Triage

读取足够上下文以判断 Search 是否有价值，然后调用
`goal-plus_goal_plus_record_triage`。

大部分以下条件成立时才使用 Search Mode：

- 存在数值或可比较 metric
- 存在自动正确性门禁
- 编辑范围可以限定
- 至少有两种可信实现方案
- baseline 行为可度量
- 候选预算值得投入

建议映射：

- Goal Mode：`is_optimization=false`、`recommended_phase="goal"`、
  `confidence="high"`。
- Spec Discovery Mode：`is_optimization=true`、
  `recommended_phase="spec_discovery"`，并列出缺失的 baseline/metric/gate 字段。
- Search Mode：`is_optimization=true`、`recommended_phase="search"`、
  `confidence="high"`。

### 步骤 3：Goal Mode

Goal Mode 用于普通实现、调查、文档、审查和定性任务。不要在 Goal Mode 创建 SearchSpec。
在当前工作区工作，以合适命令或审查证据验证，然后调用
`goal-plus_goal_plus_set_status(status="complete", evidence=[...])`。

最终回复前调用：

```text
goal-plus_goal_plus_gate(goal_plus_id="<id>", event="stop", context={})
```

如果 gate 阻止，按其 `continuation_prompt` 继续。对顶层 agent，每条仍 active 的记录都会
阻止 Stop，并重新提供完整原始目标和时间上下文。继续工作或记录真实终态；候选 worker
lease 结束绝不会完成父级目标。

### 步骤 4：Spec Discovery Mode

Discovery 将模糊优化请求转为 SearchSpec draft。需要产出：

- baseline 命令和结果
- metric 名称、方向和聚合方式
- 正确性门禁命令或 verifier 产物
- 允许和禁止的编辑范围
- 要冻结的 verifier 产物路径
- 候选预算和 worker 配置
- 提升规则
- 尚未解决的问题

ranking verifier 必须输出一个最终 JSON 对象，其中包含有限数值类型的
`spec.metric_name`，例如 `{"combined_score": 123.0}`。命令可以内联，也可以调用
现有仓库工具。只在必要时创建自定义 verifier 文件；在 Spec Discovery 期间且冻结前，
将其写入源码拥有的 `.goal-plus-verifiers/` 等路径，绝不能放在 `.gp/` 或 `.search/`。
它必须保持候选工作区只读，并将编译器和临时输出放入唯一的
`GOAL_PLUS_VERIFIER_TMPDIR`/`TMPDIR`（或 Python `tempfile`）；并发候选验证时固定
`/tmp` 路径不安全。冻结会在消耗候选预算前拒绝工作区副作用。freeze 工具暴露完整嵌套
`SearchSpec` schema；`expected_outputs` 只列出产物路径/glob，不解析 stdout。

对 AscendC Direct Invoke 场景，记录 `scenario="ascendc_direct_invoke"`，完整读取
`examples/ascendc-direct-search/SPEC_DISCOVERY.md`，遵循其 request schema 和源码模板。
针对准确固定的 Git commit，使用 `knowledge.sources.json` 运行
`materialize_knowledge.py` 生成任务局部 `_skills/`，绝不能复制 live Skill 目录。
主 agent 生成 Golden、cases、verifier、baseline 和 SearchSpec。冻结前，使用 JSON Schema
validator 按 `examples/ascendc-direct-search/request.schema.json` 校验
`_task/operator_request.json`；解析 JSON 或手动字段清单不够。不要要求用户准备任务目录
或编写 verifier。只支持 Direct Invoke，不调用外部 AscendC Agent、plugin 或编排工作流。

调用 `goal-plus_goal_plus_save_spec_draft`。只有 `confidence="high"` 且
`open_questions=[]` 时才继续 Search Mode；否则补齐缺失内容或继续 Goal Mode。

#### 自主 Search 升级

draft 达到高置信度且无 open question 后，自动进入 Search Mode gate。不要要求用户批准
verifier、metric、编辑范围、提升规则或 mode 变化。用户提示有用但可选；agent 必须发现
缺失细节并依据证据决策。

`identified_at` 和 `origin` 仅作为 provenance。旧版
`goal-plus_goal_plus_confirm_frozen_verifier` 工具和
`user_confirmed_frozen_verifier` 字段可兼容读取，但不是 Search 准入要求，绝不能暂停
`/goal-plus`。

### 步骤 5：Search Mode

调用任何创建或运行 Search 状态的 `search_*` 工具前，调用：

```text
goal-plus_goal_plus_gate(
  goal_plus_id="<id>",
  event="pre_tool_use",
  context={"tool_name": "search_freeze_spec"}
)
```

允许后，调用内部 `search` skill，并严格遵循：

```text
search_freeze_spec -> search_create -> search_plan_next -> search_start_batch
-> search_start_agent_session -> host 前台 worker -> search_run_verifier
-> search_select -> search_promote
```

`search_create` 后调用 `goal-plus_goal_plus_link_search_run`。选择并提升后调用
`goal-plus_goal_plus_record_search_result`。它只预留规范报告路径，不创建报告文件。
Goal Plus 仍 active 时不要调用 `goal-plus_search_report`。

一条 Goal Plus 记录就是完整用户任务。如果原始目标审计需要另一次有 verifier 支持的 Search，
在同一个 `goal_plus_id` 下创建并链接新 `run_id`。`search_tasks` 是仅追加任务历史，
每项对应一个冻结 spec 上的一个 run；`linked_search` 只是当前任务兼容视图。

### 步骤 6：最终原始目标审计

Search 完成只证明冻结 spec。最终审计检查原始用户目标在提升和集成工作后是否确实满足。
满足时调用 `goal-plus_goal_plus_set_status(status="complete", evidence=[...])`；
未满足时在 Goal Mode 继续集成，或用明确证据把目标标记为 blocked。

只有 Goal Plus 记录达到终态后，才对每个成功记录的 `run_id` 调用且只调用一次
`goal-plus_search_report`，并返回两条最终报告路径。绝不能生成中间 Goal Plus 报告。

## Hook 兼容性

host 有 hook 时，将 `goal_plus_gate` 接到 `search_*` 前的 `pre_tool_use`，以及 agent
结束前的 `stop` 或 `subagent_stop`。仓库中的 OpenCode 资产不包含这些 hook，
因此要在相应 checkpoint 手动调用 gate。这由指令驱动，OpenCode 本身不会强制执行；
gate 只控制 phase 顺序，host 仍负责前台 worker 启动、中断和返回值。
