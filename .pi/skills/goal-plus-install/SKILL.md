---
name: goal-plus-install
description: 安装、部署、全局化 goal-plus + Pi（含 MCP 配置与常见故障排查）。当用户问"部署 goal-plus"、"安装 goal-plus"、"在其他目录使用 goal-plus"、"goal-plus 需要什么环境"、"MCP 怎么配"、"goal-plus 报 ModuleNotFoundError / fastmcp 错误"时使用。
---

# goal-plus 安装与部署（Pi）

## 前置条件

- 本机可运行 `pi`（交互 / `--mode rpc`），worker 需要模型凭据。
- 有 Python 3.10+ 环境。**关键：goal-plus 必须装进"启动 Pi 的那个 Python 环境"**，因为 Pi 扩展通过 PATH 里的 `goal-plus-pi-tool`（或在源码目录里用 `python -c`）调用 Python 运行时。

## 安装（link 形式，不是 copy）

`pip install -e` 本身就是"符号链接式"安装：`src/` 的改动立即生效，无需重装、无需同步。

```bash
cd <goal-plus 仓库根目录>
python -m pip install -e ".[dev]"
# 可选：HTML 报告带 Plotly 轨迹图
python -m pip install -e ".[dev,report]"
```

安装后应有这些命令（`pyproject.toml` 的 `[project.scripts]`）：

```text
goal-plus                  # stdio MCP server + host hook 入口
goal-plus-pi-tool          # Pi facade（扩展实际调用它）
goal-plus-pi-worker        # 前台 pi --mode rpc worker 启动器
goal-plus-pi-pool          # detached pool supervisor worker
goal-plus-evidence-annotator
```

## 验证安装

```bash
# 1. 从任意目录 import（验证 editable 安装生效）
cd /tmp && python -c "import goal_plus; print(goal_plus.__file__)"

# 2. facade 能跑（read-only 监控，返回 JSON 即正常）
goal-plus-pi-tool goal_plus_monitor_snapshot \
  --root /tmp/gp-verify --args-json '{}' --pretty

# 3. MCP server 入口存在
goal-plus --help
```

## Pi 集成：项目本地 vs 全局

- **在 goal-plus 仓库内**：`.pi/extensions/goal-plus.ts` 和 `.pi/skills/goal-plus/` 自动发现，前提是**信任该项目**（Pi 项目级扩展只在信任后加载）。零配置。
- **在别的目录使用**：Pi 的加载器显式支持 symlink（`entry.isSymbolicLink()`），所以用 link 而不是 copy——改仓库立刻全局生效：

```bash
mkdir -p ~/.pi/agent/extensions ~/.pi/agent/skills
ln -sfn /Users/qiaolina/Code/goal-plus/.pi/extensions/goal-plus.ts ~/.pi/agent/extensions/goal-plus.ts
ln -sfn /Users/qiaolina/Code/goal-plus/.pi/skills/goal-plus           ~/.pi/agent/skills/goal-plus
```

Python 侧无需 link：editable 安装已指向源码；换目录后扩展找不到 `src/goal_plus` 会自动 fallback 到 PATH 里的 `goal-plus-pi-tool`。

### 换目录后的语义（重要）

goal-plus 是文件状态机，以**当前目录**为边界：

| 项 | 行为 |
|---|---|
| `source_path` | 扩展传 `ctx.cwd` → 作用于当前目录的源码 |
| `.gp/` 状态 | 默认相对当前目录，每目录各一套，不共享 |
| `.tmp/`、`.goal-plus-verifiers/` | 每目录各一份，verifier 按项目重写 |
| worker prompt / worker 扩展路径 | 从 **Python 包安装位置**解析（`runtime.py` / `pi_worker.py`），与当前目录无关 |

## 坑 1：仓库内双重加载（全局 + 项目本地）

Pi 的扩展去重按字符串路径，不认 symlink 真实路径。在 goal-plus 仓库内跑 Pi 时，全局 symlink 和项目本地 `.pi/extensions/` 会**各加载一份**，导致：

- `/goal-plus` 命令被注册成 `/goal-plus` 和 `/goal-plus:2`；
- 所有事件 handler（`input` / `tool_call` / `session_start` / `before_agent_start`）执行两遍 → 重复建 Goal Plus 记录、重复注入上下文。

**对策**：在仓库内开发/运行 Pi 时临时移开全局 symlink（项目本地那份自动顶上）；出仓库再恢复。

```bash
mv ~/.pi/agent/extensions/goal-plus.ts ~/.pi/agent/extensions/goal-plus.ts.bak   # 仓库内
mv ~/.pi/agent/extensions/goal-plus.ts.bak ~/.pi/agent/extensions/goal-plus.ts   # 仓库外
```

skill 同名碰撞（全局 + 项目本地）只会 warning 且内容相同，无害。

## 坑 2：editable 安装指向旧路径

症状：`goal-plus-pi-tool` 报 `ModuleNotFoundError: No module named 'goal_plus'`，但源码 import 正常。

原因：`site-packages/_editable_impl_goal_plus.pth` 指向了旧 checkout（如 `~/Code/oh-my-knowledge/code/goal-plus/src`，已不存在）。

修复：在**当前**仓库根目录重跑 `python -m pip install -e ".[dev]"`，确认 `.pth` 内容更新为当前 `src` 绝对路径。

## 坑 3：fastmcp 损坏（MCP 路径崩）

症状：`import fastmcp` 报 `ImportError: cannot import name 'PrivateKeyJWTClientAuthenticator' from 'fastmcp.server.auth.auth'`，或 `JSONDecodeError: Unterminated string`（下载/缓存损坏）。

原因：断点续传或缓存损坏导致 site-packages 里 `fastmcp/` 文件是两版混搭。

修复（清干净重装）：

```bash
SP=$(python -c "import site; print(site.getsitepackages()[0])")
rm -rf "$SP/fastmcp" "$SP"/fastmcp-*.dist-info
python -m pip cache purge
python -m pip install "fastmcp>=2.3,<3.0"
python -c "import fastmcp; print(fastmcp.__version__)"
```

注意：goal-plus 固定 `fastmcp>=2.3,<3.0`（pyproject.toml）。若环境里其他包（如 code-review-graph）要求 fastmcp 3.x，那是既有冲突，**不要为它升 3.x**，否则 goal-plus MCP server 起不来。

## MCP 需要额外设置吗？

- **Pi 路径不需要 MCP**：扩展是 in-process 注册工具（`pi.registerTool`），底层走 `goal-plus-pi-tool` facade / 源码 `python -c`，完全不经过 MCP server。
- MCP server（`goal-plus --root .gp`）只给 **Codex**（`.codex/config.toml` 的 `[mcp_servers.gp-runtime]`）或任意通用 MCP 客户端用。参考 `.codex/config.example.toml`：

```toml
[mcp_servers.gp-runtime]
command = "goal-plus"
args = ["--root", ".gp"]
env_vars = ["GOAL_PLUS_OUTER_DEADLINE_AT", "GOAL_PLUS_EVIDENCE_ANNOTATOR_MODEL", "..."]
startup_timeout_sec = 10
tool_timeout_sec = 300
enabled = true
```

Codex 还要 `cp .codex/config.example.toml .codex/config.toml`（忽略不提交）并在 `/hooks` 里信任 `.codex/hooks.json`。

## 可选环境变量

| 变量 | 作用 |
|---|---|
| `GOAL_PLUS_ROOT` | 运行时状态目录，默认 `.gp`（gitignored） |
| `GOAL_PLUS_OUTER_DEADLINE_AT` | 外层 deadline 时间戳 |
| `GOAL_PLUS_EVIDENCE_ANNOTATOR_MODEL` / `_REASONING_EFFORT` / `_BASE_URL` / `_PROVIDER_ID` / `_PROVIDER_NAME` / `_API_KEY_ENV` / `_WIRE_API` | 异步 Evidence 标注配置 |
| `GOAL_PLUS_PI_RAW_LOG=1` | 仅调试：记录 worker 完整 transcript（可能很大） |
| `PI_CODING_AGENT_DIR` | annotator 读取 provider 配置的目录 |

## 完整自检清单

```bash
python -c "import goal_plus, fastmcp" && echo OK          # 包可 import
goal-plus --help | head -1                                  # MCP 入口在
goal-plus-pi-tool goal_plus_monitor_snapshot --root /tmp/x --args-json '{}' --pretty | head -3   # facade 在
ls -la ~/.pi/agent/extensions/goal-plus.ts ~/.pi/agent/skills/goal-plus   # 全局 symlink 在
```

最后在目标目录跑一次 `pi`，`/goal-plus <一个简单目标>` 确认端到端可用。
