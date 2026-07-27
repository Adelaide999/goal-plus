---
name: search
description: OpenCode 使用 goal-plus MCP server 和前台 Task worker 的内部 Search Mode 引擎。
---

# OpenCode 的 Search Mode 运行时

在 `/goal-plus` 已把目标升级到 Search Mode 后使用此内部 skill，或用它底层调试已可度量的
SearchSpec。普通用户入口是 `/goal-plus`。

OpenCode 中的 MCP server 名为 `goal-plus`，因此逻辑 `search_*` 工具显示为
`goal-plus_search_*`。按最后的逻辑工具名匹配。

## Verifier 冻结契约

调用 `goal-plus_search_freeze_spec` 前，从 `source_path` 运行 `ranking_signal`，确认最后一个
非空 stdout 行是 JSON，且包含有限数值类型的 `spec.metric_name`，例如
`{"combined_score": 123.0}`。只在必要时创建自定义 verifier 文件，并在 Spec Discovery
期间写入源码拥有的 `.goal-plus-verifiers/` 等路径，绝不能放在 `.gp/` 或 `.search/`。
freeze 工具暴露完整嵌套 `SearchSpec` schema；`expected_outputs` 只接受产物路径/glob，
不解析 stdout。不要在完成预检前启动候选执行。

预检在一次性源码副本中运行，并把候选工作区视为只读。verifier 必须把编译器和临时输出
放入唯一的 `GOAL_PLUS_VERIFIER_TMPDIR`/`TMPDIR` 或
`tempfile.TemporaryDirectory()`。绝不能使用固定 `/tmp` 路径。任何工作区变更都会触发
`VerifierWorkspaceSideEffect`；修复 verifier 并冻结新 spec 后才能启动候选。

运行时验证仍返回 `VerifierWorkspaceSideEffect`、`metrics.infrastructure_failure=true`
或 `metrics.candidate_action=stop_and_report` 时，worker 必须立即停止，不能删除生成文件、
修改冻结 verifier、绕过失败 reset 或重试。父级使 run 失效、停止 worker、修复 verifier，
并创建后继 run。绝不能选择或提升失效 run。

## SearchSpec 与预算

最小结构：

```json
{
  "objective": "可度量的任务目标",
  "metric_name": "primary_metric",
  "metric_direction": "maximize",
  "source_path": "path/to/project",
  "edit_surface": {
    "allow": ["候选可编辑的文件或 glob"],
    "deny": ["verifier 或配置文件"]
  },
  "process_verifiers": [
    {
      "name": "ranking_signal",
      "role": "ranking_signal",
      "command": ["command", "arg"],
      "timeout_seconds": 30
    }
  ],
  "promotion_verifiers": [
    {
      "name": "anti_cheat_gate",
      "role": "anti_cheat_gate",
      "command": ["goal-plus-internal", "check-frozen-hashes"]
    }
  ],
  "budget": {
    "max_candidates": 4,
    "max_parallel": 2
  },
  "strategy": {
    "name": "agent_guided",
    "driver": "builtin",
    "worker_mode": "agent-session-pool",
    "worker_agent_type": "SearchCandidateAgent",
    "history_policy": {"scope": "top_n", "top_n": 5}
  }
}
```

`max_candidates` 是整个 run 和所有规划轮次中不可变的候选工作区总上限。
`max_parallel` 是一个规划 batch 的最大宽度；运行时不会用它监管 Task lifecycle。
大致轮次容量为 `ceil(max_candidates / max_parallel)`；两者相等通常只允许一个完整 batch。
OpenCode 运行时没有自己拥有的时间预算；subagent 运行到 step 上限或用户中断。

调用 `search_freeze_spec` 前选择整个 run 的候选预算，冻结后不能增长。存在外层时间、attempt
或 token 预算时：

1. 为主 agent 最终验证、选择、报告和提升预留时间。
2. 选择 host 能支持的 `max_parallel`；没有更好资源信号时建议 4，这只是规划建议。
3. 根据 worker tier、既往耗时和启动/verifier 开销估算一个 batch 时长。实际并发时取最慢
   worker 耗时，不要求和。
4. 估算 `rounds = floor((remaining_seconds - final_reserve_seconds) / estimated_batch_seconds)`，
   同时服从显式 attempt/token 上限，再设置 `max_candidates = rounds * max_parallel`。

例如剩余 7200 秒、预留 900 秒、每 batch 1260 秒可运行 5 轮；`max_parallel=3` 时设置
`max_candidates=15`。每个 batch 完成后刷新剩余时间和 `search_list_history`，再调用
`search_plan_next`。`requested_k` 只请求当前轮次；不能把默认值 4 当作整个 run 预算。
剩余预算仍能容纳有用 batch 时不要调用 `search_select`。

`strategy.worker_mode` 必须是 `agent-session-pool`。`strategy.worker_agent_type` 选择固定
session step 上限的 OpenCode subagent：

| 变体 | Steps | 适用情况 |
|---|---|---|
| `SearchCandidateAgentFlash` | 15 | smoke test、低成本探查 |
| `SearchCandidateAgent` | 50 | 标准 autoresearch 循环 |
| `SearchCandidateAgentDeep` | 100 | 较难问题的持续迭代 |
| `SearchCandidateAgentExtraDeep` | 150 | 广泛 Search、复杂 fixture |

自定义 Python strategy 可以返回 plan 级 `worker_policy` 覆盖下一 batch 的默认 tier。
始终使用 `search_start_agent_session` 返回的 `session.launch.subagent_type`，它是 strategy
routing 后的权威 Task tier。

## 主 Agent 派发 Policy

冻结 spec 前选择初始 tier。先前 flash/default worker 未产生任何
`search_run_verifier` iteration 或可用最终分数时，为后续工作提升 tier。
history 由运行时拥有，不是 `plan.md`。主 agent 通过 `search_list_history` 读取候选结果；
worker 通过 `search_get_agent_context` 读取 `context.history` 和 `context.iterations`。
worker 未产出有用结果时，对同一候选调用 `search_redispatch_candidate` 并指定更高 tier，
不要要求它从聊天 transcript 推断历史。

启动新候选前，检查近期尝试是否聚集于同一机制或瓶颈。不同 candidate id 本身不提供
多样性。现有候选仍有希望且能受益于累积上下文时，优先同候选 continuation 或使用更大
tier 的状态级重新派发，而不是启动近似重复候选。同一特性类别的并行候选只有在测试实质
不同假设时才有价值。可用候选容量不代表必须启动更多工作。

大量尝试仍无实质进展后，不要默认继续相近变更。重新评估适用的理论或结构限制，例如上下界、
关键路径、资源瓶颈、饱和证据或不可行约束，再确定可信突破方向。

## 工作流

### 步骤 1：只读探查

读取足够文件以确定 objective、metric、source path、允许编辑文件、禁止的 verifier/config
文件、process verifier、可选 promotion verifier 和预算。`spec.metric_name` 会成为每个
subagent `results.tsv` 的第二列标题，应使用清晰的领域名称，避免泛化的 `score`。
`spec.metric_direction`（`minimize`/`maximize`）决定 iteration 是否改进。

打包示例使用 `examples/` 中对应 JSON。用户提供额外预算指令时，在冻结前修改 spec 对象。
“先请求 N 个候选”表示 `search_plan_next(..., requested_k=N)`，不能据此改变候选总预算
或 pool size。

### 步骤 2：校验、冻结并创建

根据已保存 spec 校验目标、metric、source path、编辑范围、冻结 verifier 产物和预算。
从仓库/运行时证据解决歧义，或返回 Goal Plus Spec Discovery；不要要求用户批准进入 Search。

```text
goal-plus_search_freeze_spec(spec=<spec>, verifier_artifact_paths=[...])
goal-plus_search_create(frozen_spec_id="<id>")
```

后续 cycle 保持相同 verifier 和编辑契约时，可跳过重新冻结，使用现有 `frozen_spec_id`
调用 `search_create`；新 run 会 materialize 当前源码 baseline。记录返回的 `run_id`。

### 步骤 3：规划并创建候选工作区

```text
goal-plus_search_plan_next(run_id="<run_id>", requested_k=<k>)
goal-plus_search_start_batch(run_id="<run_id>", plan_id="<plan_id>", proposals=<可选>)
```

每个 `CandidateTask` 拥有隔离工作区。默认 `agent_guided` strategy 的
`plan.requires_agent_proposals` 为 true；必须根据 `plan.official_history` 和
`plan.proposal_contract` 编写准确 `plan.planned_k` 个 proposal。每个 proposal 包含
`intent`、`expected_tradeoff`、`instructions` 以及相应 parent/base candidate 引用。
首个 batch 没有 history，可以从源码开始；第二个 batch 起每个 proposal 必须引用至少一个
正式候选。固定 work order 的 builtin 或 Python planner 令
`plan.requires_agent_proposals=false`，此时调用 `search_start_batch` 时不传 proposal。

### 步骤 4：启动 OpenCode Task worker

对 `worker_policy.mode == "agent-session-pool"`：

1. 对每个要派发的候选调用
   `goal-plus_search_start_agent_session(run_id, candidate_id, directive)`。
   响应 `launch` 包含 `subagent_type`、`description` 和 `prompt`。
2. 原样调用
   `Task(subagent_type=launch.subagent_type, description=launch.description, prompt=launch.prompt)`。
   `launch.prompt` 是 worker 唯一需要的 prompt；不要追加或硬编码 `run_id`/工作区路径。
3. 等待前台 OpenCode Task 返回；不存在 MCP wait 调用。
4. 首次 Task 返回后，调用
   `goal-plus_search_bind_opencode_session(agent_session_id=session.agent_session_id, opencode_session_id=<Task metadata.sessionId>)`，
   绑定 OpenCode session id，以支持同 session continuation。
5. Task 返回后，自行调用不带 `agent_session_id` 的
   `goal-plus_search_run_verifier(run_id, candidate_id, "process")` 确认最终分数。
6. 同一候选应在同一 OpenCode 上下文继续且 tier 足够时，调用
   `goal-plus_search_continue_agent_session(agent_session_id, directive?)`，再运行
   `Task(task_id=launch.task_id, subagent_type=launch.subagent_type, description=launch.description, prompt=launch.prompt)`。
   这会继续同一 candidate/session/workspace，不是 fork，也不创建新候选。
7. 先前 Task 达到 step 上限、没有有用 verifier 证据或需要更大 tier 时，调用
   `goal-plus_search_redispatch_candidate(..., worker_agent_type="SearchCandidateAgentDeep")`，
   并像新 Task 一样启动 payload。它为同一候选工作区创建新 `agent_session_id`，
   不改变候选 policy，也不创建新候选。
8. 候选预算仍有剩余且确需新候选时，规划并启动下一 batch。

硬性 host 规则：OpenCode Task 是前台调用；没有受支持的 `timeout` 参数。主 agent 等待 Task
返回后才能绑定、验证、继续、报告或提升。`max_parallel` 只描述规划中的预期 pool size，
运行时不提供 MCP wait loop 或 lifecycle supervisor。worker 必须从
`search_get_agent_context(agent_session_id)` 推导 id 和路径；launch 中的 candidate id
只用于 UI 映射。停止运行中的 subagent 属于 OpenCode/用户中断；不存在 MCP abort。

### 步骤 5：Subagent Autoresearch 契约

subagent 只收到 `agent_session_id` 和候选思路。它：

1. 调用 `goal-plus_search_get_agent_context(agent_session_id)`，读取权威 `run_id`、
   `candidate_id`、`workspace`、允许/禁止文件、budget、history、iterations、results 和
   `results_tsv`。唯一必需 MCP 调用是 `search_get_agent_context` 和
   `search_run_verifier`。恢复时使用这些字段和继承账本，不依赖 launch prompt 或聊天历史。
2. 在工作区运行循环：编辑允许文件 ->
   `goal-plus_search_run_verifier(..., agent_session_id=..., hypothesis="<简洁假设>")` ->
   读取 ScoreReport -> 保留改进或在 regression 后恢复旧 commit。
3. 选择新变体前检查 `workspace/results.tsv`。运行时拥有这份连续的
   `commit \t <metric_name> \t status \t hypothesis` 账本，会验证现有前缀，并为每份
   返回报告追加且只追加一条记录。worker 绝不能创建、重写、截断、删除或手动追加它。
4. checkout 最佳状态后结束，并返回包含标识、最佳 metric、commit、改动文件和方案简述的
   摘要。该答案只用于 OpenCode/主 agent 映射；不存在 MCP finalize 调用。

不要在 worker prompt 中传递数值分数目标、baseline 分数或本地验证要求。worker 读取自己的
verifier 输出并决定下一步。

### 步骤 6：验证、选择、报告和提升

对每个已返回的候选 Task 运行主流程最终确认：

```text
goal-plus_search_run_verifier(run_id, candidate_id, "process", hypothesis="主流程最终验证")
goal-plus_search_list_history(run_id, top_n=5, sort_by="score")
goal-plus_search_select(run_id)
```

仅在选择和用户审查后调用：

```text
goal-plus_search_promote(run_id, selected_candidate_id)
```

由 Goal Plus 调用时，不生成报告就交还控制；Goal Plus skill 会在父记录达到终态后调用且只调用
一次 `goal-plus_search_report`。独立 Search 只在提升后调用报告。提升导出 patch，
不应直接改变主源码工作区。

## 失败处理

| 失败 | Action |
|---|---|
| MCP 工具不可用 | 告知用户 `goal-plus` MCP server 未连接；不要继续 |
| Freeze 失败 | 修复 spec 路径/产物，然后重试 |
| 候选工作区缺失 | 调用 status/report；不要手动重建 |
| Verifier 失败 | 在报告中保留失败；不要编辑 verifier |
| 没有通过的候选 | 报告分数和 failure class，再决定是否运行另一 batch |
| 用户要求停止 | 停止启动新 Task，由 OpenCode 中断运行中的 Task；不存在 MCP abort |

## k_module Smoke 模式

快速运行时 smoke test 可加载 `examples/k_module_search_spec.json`，冻结
`tests/fixtures/k_module_problem/evaluator.py`，创建 4 个候选，派发确定性编辑，验证、选择
并报告。这是 control-plane 测试，不是 Search 质量证明。
