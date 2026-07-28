# Global Plan Development Plan

本文档定义 Goal Plus Search 的轻量 Global Plan 开发方案和实现合同。
Global Plan 的目的不是增加一套搜索控制面，而是让并行 candidate 共享已经提出和
已经验证的尝试，使每条 candidate-local AutoResearch loop 能基于其他 loop 的公开证据
更快收敛。

本方案建立在已经实现的 candidate-local best rollback 之上：每个 verifier attempt
都有真实、长期可达的 Git commit；`keep` 保留代码，`discard`/`failure` 恢复本地最优，
但所有尝试历史继续存在。

当前状态：**已实现。**

## 目标

1. 每个 candidate 在开始一轮新修改前读取最新 Global Plan。
2. candidate 思考后提交一句话 iteration plan，再开始修改代码。
3. 不同 candidate 可以并行读取和提交，不等待其他 candidate 完成思考或验证。
4. plan 提交后立即出现在 Global Plan；尚未验证时结果字段为空。
5. verifier 结算后，Global Plan 自动展示 score、`keep|discard|failure` 和真实 attempt
   commit。
6. Global Plan 展示当前 run 内全部 candidate plan-backed 尝试，不因代码回滚、
   candidate-local best、全局排名、selection 或 promotion 而删除历史。
7. peer 实现只通过 commit hash 渐进式披露；默认不展示代码、diff、文件列表或日志。
8. 保持实现精简，不复制已有 verifier 结果，不引入 plan admission、reservation 或
   搜索空间建模。

## 非目标

第一版不实现：

- plan 去重、相似度分析、冲突检测或方向推荐；
- 全局 plan 审批、拒绝、rebase 或 reservation；
- candidate 调度、worker lifecycle 或自动停止；
- 根据 Global Plan 自动 checkout、cherry-pick 或移植 peer 代码；
- 新的 commit diff/code retrieval 工具；
- 独立的 Global Plan 数据库、共享 append log 或版本化 snapshot；
- 把 Global Plan 当作全局 incumbent 或改变 candidate-local rollback 判定；
- Global AtomicPlan、AtomicPlan admission 或完整 Search State/Evidence Schema 方案。

并行 candidate 可能同时读取同一份视图并选择相似方向。这是第一版接受的行为；Global
Plan 提供共享证据，但不承诺消除重复探索。

## 不接入 Global AtomicPlan

Global Plan 的 `global` 只表示全局可见，不表示 candidate plan 需要全局准入。第一版的
三个对象是：

```text
CandidateIterationPlan = candidate 下一轮准备做什么
IterationRecord        = verifier 实际观察到什么
Global Plan            = 所有 plan/result 的只读投影视图
```

不增加 snapshot version、admission、overlap/conflict review、reservation、
accepted/rejected/rebase 或串行 plan commit。它们会让异步 candidate plan submission
经过一个全局协调点，与本方案“不等待其他 candidate”的目标冲突。

第一版只保证单个 plan JSON 原子创建，以及现有 verifier settlement 对单个 candidate 的
原子结算。后续只有在真实运行出现大量重复探索、不可并行资源竞争或明确的预算 reservation
需求时，才在 `CandidateIterationPlan` 之上增加可选 AtomicPlan admission；Global Plan 的
公开字段不需要因此改变。

## 核心设计

Global Plan 是一个 **runtime 生成的只读投影视图**，不是新的可变全局文件：

```text
c001 immutable plan files + c001 IterationRecord[] --+
c002 immutable plan files + c002 IterationRecord[] --+--> Global Plan view
c003 immutable plan files + c003 IterationRecord[] --+
```

事实来源只有两类：

1. candidate 提交的不可变 plan 文件；
2. verifier 已经写入的现有 `IterationRecord`。

Global Plan 在读取时按 `(candidate_id, iteration)` 合并两者。它不持久化第二份聚合结果，
因此不存在 Global Plan 与 candidate history 同步或回滚的问题。

## 不增加 Plan Lifecycle 状态

不在 plan 文件、`CandidateRecord` 或 Global Plan entry 中增加 `pending`、`settled`、
`plan_status` 等 lifecycle 字段。plan 本身只是一条不可变事实：candidate 在某个
iteration 前声明准备做什么。

结果尚未产生时，score、disposition 和 commit 自然为空；结果产生后，读取视图时从
对应 `IterationRecord` 填充。是否已经完成由对应 result 是否存在判断，不单独维护状态。
score 不能独自作为完成标记，因为已经完成的 `failure` 也可能没有 score。

广义上 plan 文件仍属于 runtime 持久化数据，但它是 append-only event，不是需要恢复、
迁移或原子推进的 candidate 状态机。

## Plan 文件布局

每个 candidate 拥有独立 plan 目录：

```text
.gp/runs/<run_id>/candidates/<candidate_id>/plans/
  iteration-0001.json
  iteration-0002.json
  iteration-0003.json
```

plan 不放入 candidate Git workspace，原因是：

- candidate rollback 不应恢复或删除 Global Plan 历史；
- plan 不应进入 attempt commit 或污染代码 diff；
- plan 不属于 edit surface，也不应被 verifier 当作候选产物；
- worker 不应直接修改、截断或删除 runtime-owned history。

每个 iteration 使用独立 JSON 文件，而不是共享 JSONL：

- 可以复用现有临时文件加原子 rename 的写入方式；
- 不会产生半行 append 或多个进程竞争一个文件；
- 不同 candidate 写不同目录，不争用共享 append 文件；最终提交只为 run state/
  invalidation fence 短暂获取 `run.lock`；
- 单文件天然提供 `(candidate_id, iteration)` 幂等身份。

### Plan Schema

实现使用一个最小 Pydantic model：

```text
CandidateIterationPlan
  run_id: str
  candidate_id: str
  iteration: int
  agent_session_id: str
  description: str
  created_at: str
```

约束：

- `description` trim 后非空；
- 必须是单行文本；
- 建议最多 240 个字符；
- `iteration` 必须等于 candidate 下一次 process iteration；
- 同一 candidate/iteration 重复提交相同的规范化 description 时返回已有文件；
- 同一路径已存在但 description 不同时拒绝，不覆盖旧 plan；
- 幂等比较不使用新请求的 `created_at`，已有文件的时间和提交 session 保持不变。

不保存 score、disposition 或 commit。这些字段在 plan 提交时不存在，且已经由
`IterationRecord` 权威保存。

## Result 事实来源

第一版不新增独立 result 文件。现有 `CandidateRecord.iterations` 已经包含：

```text
iteration
agent_session_id
hypothesis
score
process_passed
disposition
git_head
ledger_git_head
failure_class
created_at
```

再写一份 `result.json` 会形成双写事务：任何一次崩溃都可能让 candidate JSON 与 result
文件不一致。Global Plan 应直接读取 `IterationRecord`。

`workspace/results.tsv` 也不适合作为 Global Plan 的唯一 result 来源：它可能继承其他
candidate/run 的行，聚合时容易重复；同时 `status=pass|fail` 表示 verifier 有效性，
不等于 `keep|discard|failure` disposition。

## Global Plan View

每个 entry 只公开：

```json
{
  "candidate_id": "c001",
  "iteration": 7,
  "description": "Pack independent initialization operations into fewer bundles",
  "score": 13350.0,
  "disposition": "discard",
  "commit": "d06f5bd32127b9b2f089c2ae67f1e14108ba1a4d"
}
```

尚无对应 verifier result 的 plan：

```json
{
  "candidate_id": "c002",
  "iteration": 4,
  "description": "Replace repeated scans with an indexed lookup",
  "score": null,
  "disposition": null,
  "commit": null
}
```

字段语义：

| 字段 | 来源 | 语义 |
|---|---|---|
| `candidate_id` | plan/result identity | 产生该尝试的 candidate |
| `iteration` | plan/result identity | candidate-local process iteration |
| `description` | plan description | 修改前提交的一句话计划 |
| `score` | `IterationRecord.score` | verifier 报告的 score；可能为空 |
| `disposition` | `IterationRecord.disposition` | `keep`、`discard`、`failure`；无 result 时为 `null` |
| `commit` | `IterationRecord.git_head` | verifier 实际测试的 attempt commit |

视图不返回：workspace path、changed files、artifact hash、restoration commit、ledger
commit、verifier metrics、failure diagnostics、日志路径、handoff、推荐方向或排名。

第一版返回当前 run 的全部 plan-backed entry，不做 `top_n`、score filter 或只保留
best。entry 按内部 `created_at` 排序，并使用 candidate id/iteration 作为稳定
tie-break；时间戳不需要暴露在窄视图中。

Global Plan 只遍历 plan 文件，再查找同一 `(candidate_id, iteration)` 的 result。没有
plan 文件的旧 iteration、parent final verification 或其他内部复验不进入视图；runtime
不反向生成、猜测或兼容第二条 Global Plan 数据路径。

## API

第一版只增加两个 worker 工具。

### `search_get_global_plan`

```text
search_get_global_plan(agent_session_id: str) -> list[GlobalPlanEntry]
```

行为：

1. 从 `agent_session_id` 推导权威 run/candidate，拒绝由 worker 自报 run scope；
2. 扫描当前 run 的 candidate plan 文件和 `IterationRecord`；
3. 动态 join 并返回窄视图；
4. 不写任何 runtime 状态；
5. 不锁住其他 candidate，也不等待 concurrent plan/verifier。

### `search_submit_iteration_plan`

```text
search_submit_iteration_plan(
  agent_session_id: str,
  description: str,
) -> GlobalPlanEntry
```

行为：

1. 从 session 推导 run/candidate；
2. 获取该 candidate 已有的 verifier/settlement lock；
3. 按 `candidate verifier.lock -> run.lock` 的固定顺序短暂进入 run transaction，确认 run
   未 invalidated，且状态仍为 `running|waiting_for_workers|selecting|selection_blocked`；
4. 若 next iteration 已有相同 description，则幂等返回；若 description 不同则拒绝；
5. 创建新 plan 前确认 workspace 仍处于 settled boundary：运行时账本存在、candidate
   artifact Git-clean，且 HEAD 与 `results_ledger_git_head` 一致；`.tmp` 和已有 runtime
   ignore 集合中的 scratch/cache 不属于 candidate artifact；
6. 在同一个 run transaction 内为 `len(record.iterations) + 1` 原子创建 plan 文件；
7. 返回 score/disposition/commit 均为空的 entry。

第 5 步保证 plan 在代码修改前提交。candidate 如果已经修改或手动 commit 代码，plan
submission 必须失败；worker 需要先回到 runtime 已结算状态，而不是补写一条事后计划。

## 与 `search_run_verifier` 的绑定

candidate worker 调用 `scope="process"` 且提供 `agent_session_id` 时：

1. runtime 确认 run 仍允许 process iteration，再计算下一 iteration number；
2. 要求对应 plan 文件存在；
3. plan description 成为 canonical `IterationRecord.hypothesis` 和 `results.tsv`
   hypothesis；
4. verifier 按现有流程建立 attempt commit、评分和 candidate-local settlement；settlement
   在 `run.lock` 下再次检查 run state/invalidation，防止长 verifier 运行期间越过终态；
5. 写入 `IterationRecord` 后不修改 plan 文件；
6. 下一次 Global Plan 读取自然把结果 join 到原 plan。

candidate worker 不再单独提交 `hypothesis`；plan description 是唯一描述来源。
parent-owned final verification 没有 `agent_session_id`，不要求 plan，也不进入 Global
Plan。它仍作为 selection/promotion 的内部 verifier evidence 保存在现有 runtime history。
process verification 只能发生在上述可迭代状态；`ready_to_promote`、`promoted`、`aborted`
和 `failed` 都拒绝新增 process iteration。promotion verifier 继续使用独立的
`ready_to_promote` 契约。

## Candidate 每轮协议

```text
settled candidate-local best
  -> search_get_global_plan
  -> inspect own code/evidence and think
  -> search_submit_iteration_plan(one-line description)
  -> modify allowed candidate files
  -> search_run_verifier
  -> keep/discard/failure settlement
  -> repeat
```

`search_get_global_plan` 的“先读再计划”由 worker contract 和 host assets 明确要求。
runtime 机械强制的是更关键、可观测的边界：plan 文件必须在 workspace 仍 settled/Git-clean
时创建，且 verifier 必须消费对应 plan。

### 每次读取都重新投影

第一版不增加 revision marker、cache token 或 `known_revision`。每个 candidate 每轮只调用
一次 `search_get_global_plan`，runtime 重新扫描小型 plan JSON 和 candidate iteration
records 并生成完整视图。

marker 在当前循环中的收益很小：candidate 自己每轮都会新增 plan 和 result，所以它下一轮
读取时视图正常情况下已经发生变化。即使增加 content hash，runtime 仍需先重建视图才能
判断是否相同，只能节省少量响应 payload，不能省掉整合逻辑。真实运行证明视图规模成为
瓶颈后，再向 API 兼容增加 hash/delta 协议。

第一版也不为“读取过 Global Plan”增加 read receipt。它会把只读调用变成写状态，且不能
证明模型实际使用了视图。

## 并发语义

### 不同 Candidate

- 各自写 `candidates/<id>/plans/`，不存在共享 append 点；
- plan submission 的 workspace/iteration 所有权由 candidate-local lock 保护；最终 state
  check 与原子写入短暂经过共享 `run.lock`；
- verifier 继续并行执行；
- Global Plan 读取不持有 run lock；
- candidate JSON 和 plan JSON 均使用原子 rename，reader 不会读取半写入文件。

Global Plan 是弱一致视图。并发读取可能看到 c001 的新 plan 和 c002 的旧结果；下一次读取
会收敛。短暂的 `run.lock` 不是 plan admission/barrier：candidate 不等待 peer 思考或
verifier，只在持久化提交点与 invalidation/state transition 排序。系统不提供 batch
barrier 或全局 snapshot isolation。

### 同一 Candidate

同一 candidate 同时运行两个 worker/verifier 不属于支持模型。plan submission 与 verifier
复用同一个 candidate-local lock，防止两个调用争用相同 iteration number。
所有需要两个锁的路径统一使用 `candidate verifier.lock -> run.lock`，不允许反向嵌套。

### Invalidation Fence

`search_invalidate_run` 与 plan 最终提交使用同一个 `run.lock`，因此并发结果只有两种：

1. plan 先完成原子写入，随后 invalidation fence 才返回；
2. invalidation 先写入 `aborted/invalidated_at`，plan 获取锁后拒绝且不写文件。

不会出现 invalidation 已返回后又新增 plan 的第三种状态。

## 与 Rollback 的关系

Global Plan 历史不参与 Git rollback：

```text
runtime candidate metadata:
  immutable plan files
  IterationRecord[]

candidate Git history:
  settled best -> attempt -> optional restoration -> ledger
```

`discard`/`failure` 时：

- attempt commit 保留；
- `IterationRecord` 保留 score、disposition 和 attempt hash；
- plan 文件保留；
- candidate code 恢复到 prior best；
- Global Plan entry 仍指向 attempt commit，不指向 restoration/ledger commit；
- 其他 candidate 的 branch、HEAD、index、workspace 和 local-best 判断不变化。

selection/promotion 也不得删除 Global Plan 历史或使已记录 attempt/ledger commit 不可达。
进入 `ready_to_promote` 后停止新增 process iteration；进入 `promoted` 后旧 worker session 的
plan 和 verifier 调用均拒绝，promotion patch、candidate ledger 与 workspace HEAD 不会再分叉。

## Commit 与渐进式代码披露

`IterationRecord.git_head` 是 verifier 实际测试的完整 Git tree snapshot，不是 promotion
patch，也不是只包含修改的文本文件。

在默认 `git_worktree` backend 下，同一 run 的 candidate 共享 Git common directory 和
object database。Global Plan 给出 peer attempt hash 后，candidate 可以在自己的 workspace
中进行只读 Git 检查，不需要知道 peer workspace 或 peer `workspace_base_revision`。
worker 已经知道自己的 settled `HEAD` 和 `candidate_task.allowed_files`，因此只提供一条
命令示例：

```bash
git diff HEAD <commit> -- <allowed-file>
```

该命令比较自己的 candidate-local best 与 peer 的完整 attempt snapshot，不需要访问其他
目录。commit 在语义上指向完整 Git tree；上述命令只是把两个 snapshot 渲染成 diff。

candidate 不应 checkout/reset 到 peer commit。若决定复用某个思路，应在自己的 settled
best 上重新实现或移植允许文件中的相关部分，提交自己的 plan，并重新 verifier；peer score
不能直接成为自己的排名证据。

promotion patch 只是 selected commit 相对冻结源码导出的交付格式，不替代或删除 Git
commit。

### Worker 提示边界

worker contract 只增加中性说明，不推荐查看具体 candidate：

> Global Plan 包含其他 candidate 的已验证尝试。对于共享 Git object database 的
> workspace，只有在你独立判断代码级证据确有必要时，才通过 commit hash 在当前
> workspace 中使用 `git diff HEAD <commit> -- <allowed-file>` 进行只读比较；不要访问
> 其他 candidate 的 workspace 目录。

第一版不增加 `search_get_commit_diff` 或 `search_get_peer_code`。Git 已经提供准确的只读
能力；额外工具会重复实现 Git 语义并主动鼓励广泛浏览。

### Copy Backend

`copy` backend 的 candidate 是独立 Git repository：

- Global Plan metadata 仍然可读；
- peer commit hash 不保证能在当前 candidate repository 中解析；
- 不自动复制 Git objects；
- 不新增跨 repository diff 服务。

因此 Global Plan 的完整“按 commit 渐进披露代码”能力以 `git_worktree` backend 为准；
它也是当前默认 backend。

## Candidate Context 的披露边界

当前 `search_get_agent_context` 会自动嵌入 run-wide 富 `history`，其中可能包含 peer
workspace、changed files、metrics、日志路径、handoff feature ledger 等信息。仅新增一个
窄 Global Plan 工具并不能真正实现渐进式披露。

本功能同步调整 candidate-facing context：

- 保留该 candidate 自己的 `iterations`、`results.tsv`、resume 和 session handoff；
- 不再自动注入跨 candidate 富 history；
- peer 尝试统一通过 `search_get_global_plan` 获取；
- parent/monitor 使用的公共 `search_list_history` 保持不变；
- Codex/Pi worker contract 不允许 worker 主动调用 parent-facing `search_list_history`。

删除的是 `search_get_agent_context` 返回对象中的 run-wide `history` 字段，不是当前
candidate 的 `iterations`、`results` 或同 candidate 的 previous sessions。这样 peer
信息只有 Global Plan 一条 candidate-facing 路径。

## 故障与恢复

| 故障点 | 结果 |
|---|---|
| plan 文件写入前失败 | 无 plan；worker 不能开始 verifier-backed iteration |
| plan 文件写入后 worker 退出 | plan 永久保留，结果字段为空 |
| attempt/verifier 正常返回 failure | entry 填充 `failure`、可选 score 和 attempt commit |
| verifier 抛异常且没有 IterationRecord | plan 保留且结果字段为空；run 按现有规则 fail closed |
| rollback/restoration 失败 | plan 和已有 evidence 保留；run fail closed |
| Global Plan 读取恰逢并发写入 | 看到原子写入前或后的状态，不会看到损坏 JSON |
| 重复提交同一 plan | 相同内容幂等；不同内容拒绝覆盖 |
| plan submission 与 invalidation 并发 | 由 `run.lock` 排序；plan 要么在 fence 前完成，要么拒绝 |
| 旧 worker 在 promotion 后继续 | plan/process verifier 在修改 Git 或账本前按 run state 拒绝 |

第一版不增加 plan 的取消、修改、超时或垃圾回收。历史是研究证据，不能因 worker 退出
或代码回滚而自动删除。

## 最小实现切片

### Slice 1: Model 与文件存储

- 增加 `CandidateIterationPlan`；
- 增加 candidate plan path/load/write helpers；
- 单文件原子写入和幂等检查；
- 不修改 `CandidateRecord` schema。

### Slice 2: Global Plan 投影与 API

- 实现 plan/result join helper；
- 增加 `search_get_global_plan`；
- 增加 `search_submit_iteration_plan`；
- 接入 `SearchTools`、FastMCP、Pi facade/schema 和 worker tool allowlist。

### Slice 3: Verifier 绑定

- worker process verifier 要求对应 plan；
- plan description 成为 canonical hypothesis；
- parent final verifier 维持内部 evidence 路径，但不进入 Global Plan；
- settlement 后不修改 plan 文件。

### Slice 4: Worker Contract 与披露边界

- 更新 Codex candidate agent/search skill；
- 更新 Pi prompt/skill/extension descriptions；
- 更新 runtime `CandidateTask.instructions` 和共享 worker boundary；
- 删除 candidate context 的跨 candidate history。

### Slice 5: 文档与测试

- 更新 API、flow、design、debugging 文档；
- 保留本设计文档作为实现合同；
- 不在第一版增加 report/HTML Global Plan 展示。

## 测试方案

测试应聚焦，避免为相同字段重复覆盖。

### 1. Plan/View 生命周期

一个测试完成：

- 两个 candidate 初始同时读取空视图；
- 分别并发提交 plan；
- 视图同时出现两个结果字段为空的 entry；
- 一个 verifier `keep`，另一个 `discard` 或 `failure`；
- 视图准确填充 score、disposition、attempt commit；
- plan 文件内容未被修改。

### 2. 顺序与所有权边界

一个测试完成：

- workspace dirty 后不能补交 plan；
- worker verifier 没有 plan 时拒绝；
- parent final verifier 不要求 plan；
- parent final verifier 不进入 Global Plan；
- 没有 plan 文件的 iteration 不被合成到 Global Plan。
- promotion 后旧 session 的 plan/process verifier 均拒绝且 candidate/promotion artifact 不变；
- plan submission 与 invalidation fence 按 `run.lock` 原子排序。

### 3. Rollback 与 Git 渐进披露

扩展现有 rollback 测试，不重复构建整套 fixture：

- `discard/failure` 后 plan/result entry 仍存在；
- peer `git_worktree` 可从自己的 workspace 解析 attempt commit；
- peer 无需访问对方 workspace；
- attempt commit 内容是 verifier 实际测试代码；
- select/promotion 后 commit 仍可达；
- `copy` backend 只验证 metadata view，不承诺 commit resolution。

### 4. Assets/API

- server/tool registry 暴露两个新工具；
- Pi worker allowlist 包含两个工具；
- Codex/Pi worker 文案要求每轮 get -> submit -> edit -> verify；
- worker 文案只提供中性 commit 披露说明，不推荐 peer 方向。

默认门禁使用当前仓库源码：

```bash
cd /home/jenkins/cwy/gp/goal-plus
PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" \
python -m pytest -n 16 -q
git diff --check
```

## 验收标准

实现完成后必须同时成立：

1. candidate 未提交 plan 时不能开始 worker-owned process verifier；
2. plan 必须在 workspace settled/Git-clean 时创建；
3. 不同 candidate 可以无 barrier 地并发读取、提交和验证；
4. 无 result 的 Global Plan entry 结果字段为空，结算后准确 join 到同一 iteration；
5. Global Plan 包含全部 plan-backed、keep、discard 和 failure 尝试；
6. plan 文件从创建后不修改、不删除、不参与 Git rollback；
7. score/disposition/attempt commit 只有 `IterationRecord` 一个事实来源；
8. Global Plan 不公开代码细节、workspace path、metrics 或日志；
9. `git_worktree` peer 可以仅凭 hash 在自己的 workspace 读取 attempt snapshot；
10. candidate 复用 peer 实现后必须在自己的 workspace 重新计划和验证；
11. candidate-local rollback、selection 和 promotion 不影响 Global Plan 历史；
12. parent final verification 不进入 Global Plan，`copy` backend 只提供 metadata view；
13. candidate context 不再自动提供其他 candidate 的富 history；
14. 第一版不建立 Global AtomicPlan admission 或 shared plan revision；
15. invalidation 返回后不能新增 plan，promotion 后不能新增 process iteration。

## 已确认的设计决定

1. plan 使用每 iteration 一个不可变 JSON 文件，不写 lifecycle 状态字段；
2. result 继续使用现有 `IterationRecord`，不新增 result 文件；
3. 没有 result 时 `score/disposition/commit = null`，不增加完成状态字段；
4. disposition 保持现有 `keep|discard|failure` 命名；
5. Global Plan 第一版返回当前 run 的全部 plan-backed 历史，不分页、不排名；
6. Global Plan 只遍历 plan 文件，不兼容或合成无 plan 的 iteration；
7. 每轮重新投影视图，不增加 revision marker 或 cache token；
8. peer code inspection 只使用共享 Git objects 和一条只读 diff 示例，不新增工具；
9. `copy` backend 只保证 metadata view；
10. 删除 candidate context 自动注入的跨 candidate 富 history；
11. 第一版不接 Global AtomicPlan、admission 或 reservation。
