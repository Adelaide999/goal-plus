# Candidate-Local Best Rollback

本文档定义 Goal Plus Search candidate 的 verifier 后结算与代码回滚机制。
这是 Global Plan 之前的第一阶段实现：每个被 verifier 测试的状态都保留真实
Git commit，但每轮结算完成后，candidate workspace 中的候选代码必须回到该
candidate 自己的历史最优状态。

同步结算核心已经实现：数据模型、strict-improvement 判定、线性 restoration
commit、candidate verifier lock、Codex/Pi worker contract 和聚焦回归测试均已落地。
完整 pending-settlement WAL 与 Global Plan 仍属于后续阶段。

## 目标

1. 每次 process-scope verifier 调用都绑定一个准确表示被测代码的 commit。
2. 严格改善的尝试标记为 `keep`，并成为 candidate-local best。
3. 同分、退化或无效的尝试分别标记为 `discard` 或 `failure`，其被测 commit
   仍保留在可达 Git 历史中。
4. `search_run_verifier` 完成结算后，workspace 中的候选代码等于该 candidate
   当前 best iteration 的代码。
5. `workspace/results.tsv` 继续保持运行时拥有、仅追加、每份返回报告恰好一行，
   并保留所有 KEEP、DISCARD 和 FAILURE 尝试。
6. 为后续 Global Plan 提供稳定映射：一句话描述、score、disposition 和被测
   commit，而不是恢复 commit。

这里的“workspace 永远最优”是一个 **settled-boundary invariant**：worker 在实现
实验以及 verifier 执行期间，workspace 必然暂时包含未验证代码；但一次
`search_run_verifier(scope="process")` 正常返回后，候选代码必须已经结算回
best-known 状态。

## 非目标

本阶段不实现：

- Global Plan 的读取、提交、聚合或并发协议；
- candidate 之间的 commit/diff 查看工具；
- 跨 candidate 的全局 incumbent 回滚；
- score epsilon、噪声容忍区间或可配置 improvement threshold；
- promotion-scope verifier 的回滚；
- 对 `.tmp/`、verifier diagnostics 或其他非候选产物的版本管理。

## 为什么不能直接复制 AR

`workspace_autoresearch` 的循环是：

```text
HEAD = 当前 best
  -> 在 working tree 中编辑，暂不提交
  -> eval
       -> 严格改善：提交 editable files，HEAD 前进
       -> 同分/退化/失败：checkout HEAD 中的 editable files，删除新增未跟踪文件
```

因此 AR 只有 KEEP 代码进入 Git；DISCARD/FAIL 只进入独立 history。

Goal Plus 有更强的 provenance 要求：candidate 代码在 verifier 前已经提交，
`IterationRecord.git_head` 必须指向 verifier 实际测试的不可变代码。未来 Global
Plan 还需要公开 DISCARD/FAIL 的 commit，让其他 candidate 渐进式查看这些尝试。
因此本设计保留 AR 的 KEEP/DISCARD 决策语义，但不采用“只提交 KEEP”的 Git
策略。

也不能在 verifier 后直接执行 `git reset --hard <best>`：

- DISCARD/FAIL commit 会只剩 JSON 中的 hash，未来可能被 Git GC；
- candidate branch 的线性 provenance 会被改写；
- 已提交的 `results.tsv` 历史可能被回退；
- worktree 可能进入与运行时记录不一致的 HEAD 状态。

本设计使用 **compensating restoration commit**：保留 attempt 及其祖先关系，
再提交一次把候选代码恢复到 best tree 的补偿变更。

## 术语

| 术语 | 含义 |
|---|---|
| settled head | 上一轮完整结算后的 workspace HEAD，包含 best 代码和当时完整账本 |
| attempt commit | verifier 执行前提交的当前候选代码；它是本轮真正被测的 commit |
| prior best | 本轮开始前，该 candidate 最佳的可选 process iteration |
| restoration target | DISCARD/FAIL 后需要恢复的 prior-best commit；没有 prior best 时使用 settled head |
| restoration commit | attempt 之后恢复候选代码的补偿 commit；它不是 verifier evidence |
| ledger commit | 为本轮报告向 `results.tsv` 追加一行后的 commit |
| disposition | iteration 的搜索结算结果：`keep`、`discard` 或 `failure` |

未来 Global Plan 的 `commit` 永远取 attempt commit，而不是 restoration commit
或 ledger commit。

## 必须保持的 Invariants

### 1. 被测 commit 准确

verifier 启动前，所有候选产物修改必须进入 attempt commit。verifier 报告、
`IterationRecord.git_head` 和 `results.tsv` 的 commit 列都引用这个 hash。

若工作区没有新的 Git diff，可复用当前 HEAD；不要求为了相同代码制造空 commit。
若存在候选产物 diff 但运行时无法提交，verifier 不应继续执行，因为此时无法建立
准确 provenance。

### 2. Best 是 candidate-local

回滚比较只使用同一个 `CandidateRecord.iterations`，不使用 `RunRecord.best_score`
或其他 candidate 的结果。一个 candidate 可以在后续主动移植其他 commit 的代码，
但必须在自己的 workspace 中重新验证后才可能成为自己的 best。

### 3. 只有可选 iteration 能成为 best

一个 iteration 必须同时满足以下条件：

- `process_passed is True`；
- score 是有限数值；
- attempt commit 存在；
- verifier 后候选产物 Git-clean；
- 没有触碰 denied files；
- 没有修改 allowed surface 之外的文件。

现有 `_best_git_iteration_record` 的筛选语义应成为统一的 eligibility 来源，避免
回滚、history、selection 分别实现不同规则。

### 4. 只有严格改善才 KEEP

```text
maximize: current_score > prior_best_score
minimize: current_score < prior_best_score
```

不使用 epsilon。相等分数不是严格改善，结算为 `discard`，并恢复原 incumbent。
这与 AR 的稳定 incumbent 语义一致，也避免同分代码在 workspace 中持续漂移。

### 5. 账本只追加

恢复旧 commit 的代码时，不得恢复旧版本的 `results.tsv`。结算仍然必须满足：

- 每份正常返回的 process verifier 报告产生一个 `IterationRecord`；
- 每份报告向 `results.tsv` 追加且只追加一行；
- 已有前缀逐字节不变；
- ledger commit 在本轮最终 workspace 历史中可达。

### 6. 尝试历史始终可达

DISCARD/FAILURE 的 attempt commit 必须是 restoration/ledger commit 的祖先，而
不是仅靠 candidate JSON 保存的悬空 Git object。其他 worktree 才能在未来长期通过
hash 使用 `git show` 或 `git diff` 查看它。

### 7. Fail closed

如果 candidate artifact 恢复、账本恢复或 restoration commit 失败，运行时不能返回
一个看似正常的 verifier 结果并继续搜索。它必须保留已有报告/日志，将 run 标为失败，
并显式报告 settlement failure。

## Disposition 判定

| 条件 | disposition | workspace 代码 |
|---|---|---|
| 没有 prior best，当前 iteration eligible | `keep` | 保留当前 attempt |
| 当前 eligible 且严格优于 prior best | `keep` | 保留当前 attempt |
| 当前 eligible，但同分或更差 | `discard` | 恢复 prior best |
| process verifier 失败或没有有效 score | `failure` | 恢复 prior best；若不存在则恢复 settled head |
| edit-surface/frozen-artifact 等策略检查失败 | `failure` | 同上 |
| attempt commit 无法建立 | settlement error | 不运行 verifier，run fail closed |
| restoration 无法完成 | settlement error | 不继续 candidate，run fail closed |

`failure` 表示本轮没有产生可参与排名的有效证据。即使失败报告内部带有 `0.0`
等占位 score，也不能因为 metric direction 是 `minimize` 而成为 best。

## Process Verifier 结算流程

仅 `scope="process"` 使用下面的流程。Promotion verifier 继续针对选定的不可变
revision 执行，不创建搜索 iteration，也不改变 candidate-local best。

### A. Verifier 前

1. 加载 run、frozen spec、candidate record 和可选 agent session。
2. 校验现有 `results.tsv` 与 runtime ledger 完全一致且 Git-clean。
3. 保存 `pre_attempt_settled_head = record.results_ledger_git_head`。上一轮按本设计
   结算后，latest ledger commit 同时也是 settled head。
4. 在追加当前 iteration 之前计算 `prior_best`。
5. 检测候选产物修改并建立 attempt commit。
6. 确认 attempt commit 存在，且正常情况下是 settled head 的后代。历史已经偏离、
   ledger 被 checkout 掉或候选产物仍 dirty 时 fail closed。
7. 记录 `attempt_git_head`、artifact hash 和待使用的 iteration number。

### B. 执行 verifier

运行冻结的 verifier，并保留现有 side-effect 快照、日志、diagnostics、timeout 和
invalidation fence 行为。此阶段不移动 HEAD。

### C. 判定

根据报告构造当前 iteration 的 eligibility，并与 verifier 前捕获的 `prior_best`
比较：

```text
eligible and no prior best       -> keep
eligible and strictly improved   -> keep
eligible and not improved        -> discard
not eligible                     -> failure
```

比较必须使用 verifier 前的 prior best，不能先把当前 iteration 加入列表再依赖排序
副作用决定 disposition。

### D. 恢复候选代码

`keep` 不恢复代码。

`discard` 和 `failure` 的 restoration target 为：

```text
prior_best.git_head              if prior best exists
pre_attempt_settled_head         otherwise
```

恢复必须留在当前 candidate branch 上，不能 detached checkout，也不能 hard reset。
建议实现专用 `_restore_candidate_artifact` helper：

1. 用 runtime ledger 渲染并保存当前 canonical `results.tsv` 内容。
2. 以 restoration target 为 source，对 index 和 working tree 执行 `git restore`。
3. 把 canonical `results.tsv` 重新写回并 stage，防止旧 commit 中的 ledger 覆盖当前
   前缀。
4. 提交 staged artifact restoration，commit message 包含 candidate、当前 iteration
   和目标 best iteration。
5. 如果 attempt 与 target 的候选代码树本来相同，允许 restoration 为 no-op，不制造
   空 commit。
6. 恢复后重新计算 artifact hash；有 prior best 时必须等于其 `artifact_hash`。
7. 确认 `results.tsv` 内容未变且 Git-clean。

示意命令不是公共 API，只表示目标 Git 语义：

```text
git restore --source=<target> --staged --worktree -- .
rewrite canonical results.tsv
git add results.tsv
git commit -m "goal-plus restore c001 best iteration 3 after iteration 5"
```

实现必须使用参数数组和现有 Git helper，不通过 shell 拼接命令。

### E. 记录报告和账本

artifact 已处于结算状态后：

1. 创建 `IterationRecord`，其中 `git_head` 仍是 attempt commit。
2. 向 `results.tsv` 追加本轮 attempt commit、score、pass/fail 和一句话 hypothesis。
3. 提交 ledger；此 ledger commit 成为新的 settled head。
4. 持久化 disposition、恢复目标和结算后 workspace HEAD。
5. 更新 candidate latest report、run-wide best 和 session verifier counter。
6. 只有以上步骤全部成功后才返回 `ScoreReport`。

把 restoration 放在本轮 ledger append 之前有两个好处：

- ledger commit 总是建立在已经恢复好的 best 代码上，天然成为下一轮 settled head；
- `run_verifier` 返回时不需要再移动 HEAD，context 中的 Git snapshot 与 ledger pointer
  一致。

## Git 历史形态

### KEEP

```text
previous settled head
  -> attempt commit (new best; verifier tests this hash)
  -> ledger commit (workspace HEAD after settlement)
```

### DISCARD 或 FAILURE

```text
previous settled head
  -> attempt commit (verifier tests this hash)
  -> restoration commit (best code restored; optional when tree already matches)
  -> ledger commit (workspace HEAD after settlement)
```

因此：

- `IterationRecord.git_head` = attempt commit；
- `ResultLedgerEntry.git_head` = attempt commit；
- `ResultLedgerEntry.ledger_git_head` = 最终 ledger commit；
- workspace HEAD = 最终 ledger commit；
- future Global Plan `commit` = attempt commit。

commit hash 表示完整 Git tree，而不是天然的“相对 init diff”。未来消费者可以选择：

```text
git show <attempt>                         # 相对父 commit 的本轮增量
git diff <run-baseline> <attempt>          # 相对 run 初始代码的完整方案
```

Global Plan 第一阶段只公开 hash；读取代码由后续渐进式披露工具或同一 Git common
directory 中的只读 Git 命令完成。

## 持久化字段

`IterationRecord.git_head` 已经承担 attempt commit 语义，不应改为 restoration 或
ledger commit。建议增加带默认值的向后兼容字段：

```text
disposition: keep | discard | failure | null
restored_to_iteration: int | null
restored_to_git_head: str | null
workspace_git_head_after_settlement: str | null
```

旧记录的 `disposition=null` 表示升级前 iteration，不应通过猜测回写。

`ScoreReport` 的工具响应应包含相同结算摘要，使 worker 无需从 Git 状态推断本轮是否
被恢复。`results.tsv` 在本阶段保持现有四列格式；其中 `status=pass|fail` 表示 verifier
有效性，不等同于搜索 disposition。未来 Global Plan 从 `IterationRecord.disposition`
读取 `keep|discard|failure`。

候选 history 必须继续同时展示：

- best score / best iteration：正式排名证据；
- latest score / latest process result：最近一次诊断；
- latest disposition：本轮 KEEP、DISCARD 或 FAILURE；
- settled workspace head：下一轮实际起点。

## VerifierWorkspaceSideEffect

`VerifierWorkspaceSideEffect` 是 verifier 基础设施故障，不是性能退化。它仍结算为
`failure`：

1. 保留 attempt commit、verifier report、side-effect 路径、hash、日志和 cleanup
   failures；
2. 按现有机制尝试恢复 verifier 自身造成的 workspace 副作用；
3. 按本设计把 candidate artifact 恢复到 prior best 或 settled head；
4. 返回/报告 `stop_and_report`，worker 不重试；
5. 如果 verifier side-effect cleanup 或 candidate restoration 失败，则 run fail
   closed，不能声称 settled-boundary invariant 已满足。

诊断证据以 report、diagnostics 和日志持久化，不依赖让退化候选代码继续留在工作区。

## 并发与锁

不同 candidate 的 verifier 进程继续并发执行。已有 run transaction 只在短暂的 durable
record/update 阶段串行化，不应扩展为包住 verifier 外部进程。

同一个 candidate 同时执行两个 process verifier 不属于支持的 worker 模型。实现应在
candidate settlement 上使用候选级互斥或等价 guard，防止两个调用交错提交、恢复同一
worktree。不同 candidate 不共享 index 或 branch，因此候选级锁不会降低正常并发度。

Git worktree backend 下，各 candidate 共享 object database，但使用不同 branch 和
worktree index。线性 restoration commit 会让所有 attempt objects 通过各自 candidate
branch 保持可达。`copy` backend 也必须具有相同本地结算语义，但不承诺跨 candidate
通过 hash 查看 commit。

## Worker 行为变更

runtime 成为 rollback 的唯一 owner 后，worker 不再负责在回归后执行
`git reset --hard HEAD~1`。Codex/Pi worker contract 应改为：

- 修改 allowed files；
- 调用 `search_run_verifier`；
- 根据返回的 disposition 和 best 信息选择下一条 hypothesis；
- 不自行 reset/restore verifier-backed iteration；
- 下一轮从 runtime 已结算的 workspace 继续。

这样可以避免 worker reset 掉 ledger commit、进入 detached history，或让 prompt 行为
与 runtime provenance 冲突。Main final verification、`search_select` 和 promotion 会在
当前历史之上恢复并重新验证最佳 immutable revision，而不 detached checkout；
candidate-local rollback 不替代最终选择。

## 故障与恢复

文件型 runtime 没有数据库事务，因此实现必须显式处理部分完成：

- attempt commit 后 verifier 进程崩溃：记录 failure report 后恢复；若没有形成可返回
  report，则 run fail closed，attempt commit 仍通过 branch 可达；
- restoration commit 后、ledger append 前崩溃：代码已经是 best，但本轮 durable
  ledger 可能未完成；恢复路径必须检测并完成或将 run 标为失败，不能重复追加；
- ledger commit 后、candidate JSON 写入前崩溃：使用 ledger commit/row identity 检测
  已完成 append，禁止第二次追加同一 iteration；
- candidate JSON 显示待恢复但 workspace 已恢复：通过 target artifact hash 和 HEAD
  ancestry 幂等完成 settlement。

建议在 CandidateRecord 中增加一个内部 `pending_settlement` marker，至少包含 iteration
number、attempt commit、disposition、restoration target 和 ledger row identity。marker
在 attempt/report 已持久化后建立，在 restoration 与 ledger/record 全部完成后清除。
所有新的 verifier、resume、select 路径在操作 workspace 前先恢复 pending settlement。

如果第一阶段为控制改动范围而暂不实现完整 WAL，最低要求仍是：所有 Git 结算步骤同步
执行、任何异常将 run 标为 failed、失败后禁止 candidate 继续；不得静默返回并留下退化
workspace。

## 实现切片

### Slice 1: 数据模型与判定 helper（已实现）

- 增加 disposition/settlement 字段和向后兼容默认值；
- 提取唯一的 iteration eligibility helper；
- 实现 candidate-local strict-improvement 判定；
- 保持 run-wide best 与 candidate-local best 概念分离。

### Slice 2: Git restoration primitive（已实现）

- 实现不 detached、不改写历史的 artifact restore；
- 保留 canonical `results.tsv`；
- 支持新增、修改和删除文件；
- 校验 target artifact hash、Git cleanliness 和 ancestry；
- 为 no-op restoration 返回当前 HEAD。

### Slice 3: `run_verifier` 结算（已实现）

- verifier 前捕获 settled head/prior best/attempt commit；
- 报告后判定 disposition；
- DISCARD/FAILURE 同步恢复；
- append ledger 并记录 settlement metadata；
- restoration failure 时 fail closed。

### Slice 4: Host contract（已实现）

- 更新 Codex/Pi worker prompt、skill 和 hook guidance；
- 删除 worker 自行 reset 回归 iteration 的要求；
- 在 verifier 返回中明确告知 disposition、best 和 settled head；
- 更新对应 asset tests。

### Slice 5: Global Plan（待后续独立实现）

Global Plan 只消费本阶段已经稳定的字段：

```text
description <- iteration hypothesis / future submitted plan sentence
score       <- iteration score
decision    <- iteration disposition
commit      <- iteration attempt git_head
```

Global Plan 不参与本阶段的回滚判定，也不改变 candidate-local best。

## 测试矩阵

### 核心行为

- maximize：首个有效结果 KEEP，改善 KEEP，退化 DISCARD；
- minimize：方向相反但行为一致；
- 同分 DISCARD；
- process failure、missing score、edit-surface violation 均为 FAILURE；
- 没有 prior best 的 FAILURE 恢复 pre-attempt settled head；
- restoration 后下一轮确实从 best artifact 开始。

### Git 与账本

- 每个 KEEP/DISCARD/FAILURE 都有可读取的 attempt commit；
- DISCARD/FAILURE commit 是最终 HEAD 的祖先，`git cat-file` 可长期读取；
- restoration 支持文件新增、删除、重命名和内容修改；
- `results.tsv` 每份返回报告只增加一行，旧前缀不变；
- iteration commit、restoration commit、ledger commit 三种 hash 不混淆；
- rollback 后 workspace Git-clean，artifact hash 等于 prior best；
- select 和 promotion 后所有 attempt/ledger commit 仍由 candidate 历史可达；
- `git_worktree` 与 `copy` backend 均通过本地结算测试。

### 失败路径

- attempt commit 失败时不运行 verifier；
- restoration Git 命令失败时 run fail closed；
- ledger commit 失败时不返回成功 settlement；
- VerifierWorkspaceSideEffect 保留诊断并恢复 candidate artifact；
- pending settlement 的幂等恢复不会重复 ledger row。

### 兼容性

- 旧 `disposition=null` iteration 仍可读取和选择；
- `search_select` 仍按 attempt commit 选择并执行 parent final verification；
- report/history 同时保留 best 与 latest regression/failure；
- Codex/Pi assets 不再要求 worker 手动 reset verifier-backed 状态。

## 验收标准

实现完成后，对任意正常完成的 process verifier 调用，应同时成立：

1. 本轮 Global-Plan-ready 记录可以唯一映射到真实 attempt commit；
2. KEEP、DISCARD、FAILURE 的 score 和诊断历史均未丢失；
3. `git merge-base --is-ancestor <attempt> <workspace-head>` 成功；
4. `results.tsv` 包含本轮且只新增一行；
5. workspace candidate artifact 等于 candidate-local best；
6. workspace Git status 对运行时管理的代码和账本为空；
7. select/promotion 不 detach 或丢弃已记录的 attempt/ledger 历史；
8. 下一轮无需 worker 手动 reset，即从 best-known 代码继续。
