---
name: search
description: 使用前台 Claude Code Agent 和 goal-plus MCP server 的 /goal-plus 内部 Search Mode 引擎。
---

# Claude Code 的 Search Mode 运行时

在 `/goal-plus` 已把目标升级到 Search Mode 后使用此 skill，或用它底层调试已可度量的
SearchSpec。普通用户入口是 `/goal-plus`。使用 `goal-plus` MCP server 暴露的逻辑
`search_*` 工具；Claude Code 可能显示 server 前缀，按最后的逻辑工具名匹配。

## Verifier 冻结契约

调用 `search_freeze_spec` 前，从 `source_path` 运行拟定的 `ranking_signal`，确认其最后一个
非空 stdout 行是 JSON，且包含有限数值类型的 `spec.metric_name`，例如
`{"combined_score": 123.0}`。只在必要时创建自定义 verifier，并在 Spec Discovery 期间
写入源码拥有的 `.goal-plus-verifiers/` 等路径，绝不能放在 `.gp/` 或 `.search/`。
freeze 工具暴露完整嵌套 `SearchSpec` schema；`expected_outputs` 只接受产物路径/glob，
不解析 stdout。运行时会重复预检，并在候选启动前拒绝无效 freeze。

预检在一次性源码副本中运行，并把候选工作区视为只读。verifier 必须将编译器和临时输出
放入 `GOAL_PLUS_VERIFIER_TMPDIR`/`TMPDIR` 或
`tempfile.TemporaryDirectory()`。绝不能使用固定 `/tmp` 路径。任何工作区变更都会触发
`VerifierWorkspaceSideEffect`；启动候选前应修复 verifier 并冻结新 spec。

运行时验证仍返回 `VerifierWorkspaceSideEffect`、`metrics.infrastructure_failure=true`
或 `metrics.candidate_action=stop_and_report` 时，worker 必须立即停止，不能清理生成文件、
编辑冻结 verifier、绕过失败 reset 或重试。父级使 run 失效、停止每个 live worker、
修复并重新冻结，再创建后继 run。绝不能选择或提升失效 run。

## SearchSpec 与预算

`budget.max_candidates` 是所有轮次中不同候选工作区总数的不可变上限；
`budget.max_parallel` 是一个规划 batch 的最大宽度，不是候选总数。大致轮次容量为
`ceil(max_candidates / max_parallel)`；两者相等通常只允许一个完整 batch。

调用 `search_freeze_spec` 前选择整个 run 预算，冻结后不能增长。存在外层时间、attempt
或 token 预算时：

1. 为主 agent 最终验证、选择、报告和提升预留时间。
2. 选择 host 能支持的 `max_parallel`；没有更好资源信号时建议 4。
3. 根据 Claude worker tier、已观测 worker 时长和 verifier 开销估算 batch 时长。
4. 设置 `rounds = floor((remaining_seconds - final_reserve_seconds) / estimated_batch_seconds)`，
   再设置 `max_candidates = rounds * max_parallel`。

例如剩余 7200 秒、预留 900 秒、每 batch 1260 秒可运行 5 轮；`max_parallel=3` 时设置
`max_candidates=15`。每个 batch 完成后刷新剩余时间和 history。`requested_k` 只请求当前轮次，
不能把默认值 4 当作整个 run 预算。仍能容纳有用 batch 时不要调用 `search_select`。

worker tier：

- `search-candidate-agent-flash`：4 turns，用于 smoke test 和低成本探查
- `search-candidate-agent`：8 turns，用于普通候选工作
- `search-candidate-agent-deep`：16 turns，用于较大源码树、较慢 verifier 或跨文件推理

先前 worker 达到 `maxTurns` 且未记录任何 verifier iteration 时，为同一候选提高 tier。
history 由运行时拥有，不是 `plan.md` 文件。主 agent 从 `search_list_history` 读取结果；
worker 从 `search_get_agent_context` 读取 `context.history` 和 `context.iterations`。
不要要求 worker 从聊天 transcript 推断历史。

新候选启动前检查近期尝试是否聚集于同一机制或瓶颈。不同 candidate id 本身不提供多样性。
现有候选仍有希望且受益于累积上下文时，优先同候选 continuation 或更大 tier 的状态级恢复，
而不是近似重复候选。可用候选容量不代表必须启动更多工作。大量尝试仍无进展后，重新评估
上下界、关键路径、资源瓶颈、饱和证据或不可行约束。

## 工作流

1. 读取足够上下文，确定 objective、metric、source path、编辑范围、process/promotion
   verifier 和预算。`metric_name` 应清晰且领域特定；`metric_direction` 决定改进方向。
2. 校验契约后调用：

   ```text
   search_freeze_spec(spec=<spec>, verifier_artifact_paths=[...])
   search_create(frozen_spec_id="<id>")
   ```

   后续 cycle 保持相同 verifier 和编辑契约时，可复用现有 `frozen_spec_id`。
3. 规划并创建候选工作区：

   ```text
   search_plan_next(run_id="<run_id>", requested_k=<k>)
   search_start_batch(run_id="<run_id>", plan_id="<plan_id>", proposals=<可选>)
   ```

   `agent_guided` 要求根据 `plan.official_history` 和 `plan.proposal_contract` 编写准确数量的
   proposal；固定 work order 的 strategy 不传 proposal。
4. 对每个候选调用 `search_start_agent_session`，然后使用返回 payload 启动前台 Agent：

   ```text
   Agent(
     description=launch.description,
     prompt=launch.message,
     subagent_type=launch.agent_type,
     background=false
   )
   ```

   原样使用 launch 字段，不要追加或硬编码 `run_id`/工作区路径。Agent 返回后，使用
   `search_bind_agent_handle` 绑定终态 handle 和 summary，并自行运行不带
   `agent_session_id` 的 `search_run_verifier` 确认最终分数。
5. 要继续同一个 native agent，先调用 `search_continue_agent_session`，再使用
   `SendMessage(agent=<绑定 id>, message=launch.message)`。如果 `SendMessage` 不可用，
   或原 agent 达到 `maxTurns` 且无法继续，则通过
   `search_redispatch_candidate` 对同一候选执行状态级恢复，并启动新前台 Agent。
6. 候选预算仍有剩余且确需新候选时，再规划下一 batch。每个 Agent 都是前台调用；
   此运行时没有 MCP wait loop、后台 subagent supervisor 或 abort API。
7. 对每个返回候选执行主流程最终 verifier，读取 `search_list_history`，全部 worker drain 后
   再调用 `search_select`。只能使用 `search_promote` 提升，不能手动复制文件。
8. 该 Search 属于 Goal Plus 时，不生成报告就交还控制；Goal Plus skill 会在父记录达到终态后
   调用且只调用一次 `search_report`。独立 Search 只在提升后报告。

## Worker 契约

worker 只收到 `agent_session_id` 和候选思路。它首先调用
`search_get_agent_context(agent_session_id)`，将返回的 `run_id`、`candidate_id`、
`workspace`、允许/禁止文件、budget、history、iterations、results 和 `results_tsv`
视为权威依据。唯一必需 MCP 调用是 `search_get_agent_context` 和 `search_run_verifier`。

worker 只在候选工作区中运行 autoresearch 循环：编辑允许文件，调用
`search_run_verifier(..., agent_session_id=..., hypothesis="<简洁假设>")`，读取
ScoreReport，并保留改进或恢复旧 commit。运行时拥有 `results.tsv`，会验证已有记录并为每份
报告追加且只追加一条记录；worker 绝不能创建、重写、截断、删除或手动追加它。

如果结果包含 `VerifierWorkspaceSideEffect` 或 `candidate_action=stop_and_report`，worker
立即返回，不能清理或重试。结束时 checkout 最佳工作区状态，并返回包含标识、最佳 metric、
commit、改动文件和方案简述的摘要。不存在 MCP finalize 调用。

## Host 规则

- Claude Agent 使用 `background: false` 的前台启动。
- `max_parallel` 只用于规划；运行时不监管 Agent lifecycle。
- 没有 Task/Agent 级受支持 timeout；turn 上限由 agent frontmatter 决定。
- `search_continue_agent_session` 只继续相同 runtime `agent_session_id`，不能用来创建新方向。
- `search_redispatch_candidate` 是同一候选工作区使用新 `agent_session_id` 的状态级恢复。
- 停止运行中的 Agent 属于 Claude Code/用户中断；不存在 MCP abort。
- 候选触碰 denied file 或编辑范围外文件时，仍运行 verifier，让运行时标记失败。

## 失败处理

MCP 工具不可用时报告 server 未连接；freeze 失败时修复 spec/产物；候选工作区缺失时读取
status/report，不手动重建；verifier 失败保留在报告中，不编辑 verifier；没有通过候选时
报告分数与 failure class。用户要求停止时不再启动 Agent，由 Claude Code 中断运行项。
