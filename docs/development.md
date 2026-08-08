# CoreCoder 开发说明

本文是后续维护和扩展 CoreCoder 的工作手册。工程规则以根目录
[AGENTS.md](../AGENTS.md) 为准；本文件解释如何把这些规则落到一次具体
开发中。

## 1. 先理解边界

CoreCoder 的核心不是某个 UI，而是一个可观测、可恢复、可测试的 Agent
runtime。主要边界如下：

```text
CLI / Terminal
        │ Agent.run + RunEvent observer
        ▼
Agent ── ModelGateway ── LLM provider
  │
  ├── Context strategy
  ├── ToolRegistry ── ExecutionPolicy ── ToolResult
  ├── MemoryService
  ├── SessionStore / AppPaths
  └── Trace schema v2 / Replay
```

源码职责：

| 区域 | 责任 |
|---|---|
| `corecoder/commandline/` | 解析命令、组合运行时、输出和退出码 |
| `corecoder/terminal/` | PromptSession、slash command、补全、审批、Rich 渲染 |
| `corecoder/agent.py` | 对话、单次 run、状态、工具编排和生命周期 |
| `corecoder/runtime/` | Workspace、RunEvent、Agent/Run state、ModelGateway |
| `corecoder/tools/` | Effect 声明、工具实现、结构化 ToolResult |
| `corecoder/policy.py` | 应用权限、风险分类、审批和并行边界 |
| `corecoder/session.py` / `paths.py` | 项目隔离的 session/history/memory/trace 路径 |
| `corecoder/trace.py` / `replay.py` | Trace 写入、v1/v2 Replay、报告 |
| `specs/` / `scripts/spec.py` | 轻量 SDD 和 capability 文档 |
| `tests/` | 行为、Trace、CLI、Terminal 和安全边界验证 |

不要把 `eval.py`、`memory.py`、`trace.py` 为了目录好看而整体搬迁；先为
真实行为建立边界，再以行为保持不变的 refactor change 拆分。

## 2. 不可破坏的工程约束

### 状态所有权

- runtime 状态必须属于 Agent 实例，禁止模块级可变的全局 ToolRegistry、
  session store、workspace 或 changed-files 集合。
- `WorkspaceState` 是路径解析的唯一来源。Policy、Prompt、Bash 和文件工具
  必须使用同一个对象。
- `RunState` 只描述一次任务；`RunResult` 只返回本次增量 token、cost 和
  changed files。
- 取消/异常时撤销不完整的 assistant/tool 协议和孤立 user message，Trace
  仍保留失败生命周期。

### 工具和权限

- 新工具必须声明 Effect；未知 Effect 不能默认当作只读。
- 工具实现返回 `ToolResult`，不要用 `"Error"`、`"Blocked"` 等文本判断
  成功与否。
- 只有 `parallel_safe=True` 且 Effect 完全为 `READ_FS` 的工具可以并行。
- 权限策略负责应用层审批；Agent-owned Bash 另外使用实例级 OS sandbox，
  默认以物理 workspace 为边界并拒绝网络。直接 Python/subprocess 调用仍不
  自动受保护，这条边界必须在代码和文档中保持明确。

### 事件和 Trace

- 新 runtime 行为必须有 unit test 和可观察 Trace event。
- 模型调用统一经过 `ModelGateway`，并标记 `purpose=agent|compaction|memory`。
- TextDelta 默认只用于实时 observer，不写入持久 Trace；最终回答进入完成事件。
- 修改公共事件或 Trace schema 时，必须补 v1/v2 Replay 或兼容测试。

## 3. 一次变更的核心流程

### 第一步：确认是否需要 SDD

以下变化必须创建 change：用户可见行为、公共 API、Trace schema、权限、
并发、工具、上下文、memory、session 或 Terminal UX。拼写、纯文档和测试
数据修正可以跳过，但不能借此绕过行为变更。

```bash
python scripts/spec.py new short-slug
python scripts/spec.py status short-slug
```

不要为旧代码库一次性补全所有规格。只为下一项真实变更建立 spec，并随
行为逐步完善 `specs/capabilities/`。

### 第二步：写 spec.md

只写可观察契约，不把函数名和具体行号塞进需求：

- Why、Goals、Non-goals
- `R1`、`R2` 等独立需求
- `AC1` 等 Given/When/Then 验收场景
- 兼容性、约束、Trace contract、风险和回滚

每个需求至少有一个场景；每个场景必须能在测试和 Trace 中找到证据。

### 第三步：审批意图

把 `spec.md`、`tasks.md`、`checklist.md` 填完整后执行：

```bash
python scripts/spec.py check 001-short-slug
python scripts/spec.py approve 001-short-slug
```

审批前只问两个问题：问题和范围是否正确，AC 是否能判断完成与否。范围
改变或明显膨胀时，修改 spec 或新开 change，不要把无关工作塞入当前目录。

### 第四步：拆 tasks.md

任务要能在一个会话中完成，并指向真实文件和测试节点：

```text
- [ ] T1 [R1, AC1] tests/...::test_behavior（先写失败测试）
- [ ] T2 [R1, AC1] corecoder/... 实现最小行为
- [ ] T3 [AC1] 运行定点验证并记录 Trace assertion
```

只有不同文件、无共享状态且相关工具明确 `parallel_safe` 时才标 `[P]`。
先写失败测试，再实现最小行为，最后清理重复代码。

### 第五步：实现和验证

常规本地门禁：

```bash
python scripts/spec.py check --strict
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q corecoder tests
.venv/bin/python -m corecoder --help
.venv/bin/python -m corecoder run --help
git diff --check
```

Ruff 由开发依赖提供，CI 执行关键规则：

```bash
.venv/bin/python -m ruff check --select E4,E7,E9,F corecoder tests scripts
```

测试必须使用临时 `AppPaths`，不得触碰真实 `~/.corecoder`。不要把 session、
Trace、模型文件或密钥加入提交。

### 第六步：补 capability 并归档

完成后更新对应的 `specs/capabilities/*.md`，在 checklist 填写每个 AC 的
pytest 节点和 Trace assertion：

```bash
python scripts/spec.py check 001-short-slug --strict
python scripts/spec.py archive 001-short-slug
```

`archive` 只接受 DONE change，并要求 capability 文件已存在。归档后的 change
是历史证据，不是下一次变更的工作区。

## 4. 常见扩展方式

### 新工具

1. 在 `corecoder/tools/` 实现 `Tool` 子类。
2. 声明 `effects`、参数 schema 和必要的 `parallel_safe`。
3. 所有路径通过传入的 `WorkspaceState` 解析。
4. 返回 `ToolResult`，包括失败类型、退出码、修改文件和 diff。
5. 在 Agent 的工具 registry 中实例化，不创建模块全局单例。
6. 添加 Policy、并发、Trace 和回归测试。

### 新 Terminal command

1. 在 `corecoder/terminal/commands.py` 注册命令、别名、usage 和 handler。
2. handler 只调用 Agent 的公开方法，例如 `clear/compact/status/close`。
3. 为参数错误、未知命令和补全增加测试。
4. 不在 prompt redraw/render callback 中访问网络；toolbar 只读缓存。

### 新 CLI command

1. 在 `commandline/parser.py` 添加命令和参数。
2. 在 `commandline/handlers.py` 实现业务处理和退出码。
3. 确保 help 不需要模型密钥。
4. 明确 stdout/stderr 归属，并为 TTY、非 TTY、JSONL 增加测试。

### 修改模型或上下文

1. 通过 `ModelGateway` 调用，不直接在 Terminal 或工具中调用 provider。
2. 明确 `purpose`，记录 model started/finished/failed。
3. 保持 token/cost 是本次 run 的增量。
4. 修改摘要或协议时验证 `tool_protocol_valid` 和 Replay 兼容性。

### 修改 session 或 memory

1. 使用注入的 `AppPaths`，按 Git root 隔离项目。
2. session 使用同目录临时文件、flush/fsync、`os.replace` 和私有权限。
3. 不保存密钥，不恢复权限模式；损坏文件只报错不删除。
4. `--ephemeral` 下禁止 history/session/memory 写入。
5. 为跨项目、损坏文件、取消和恢复增加临时目录测试。

## 5. 文档职责

- `README.md`：只保留入口和版本/fork 一行说明。
- `docs/user-guide.md`：面向成品用户的安装、配置、Terminal、CLI、权限、
  session 和 Trace 使用方式。
- `docs/development.md`：本文件，面向后续开发者的边界、流程和门禁。
- `AGENTS.md`：唯一工程宪章，不在其他文档复制规则。
- `specs/capabilities/`：当前已经承诺的可观察行为。
- `specs/changes/archive/`：已完成变更的 SDD 证据。
- `CHANGELOG.md`：版本变更记录；不作为使用教程。
- `benchmarks/`：评测协议和结果证据；不作为 runtime 使用说明。
- 上游历史文章已移除；当前实现只以本文件、`AGENTS.md`、`specs/` 和代码测试为准。

新增说明优先补到两份主文档，避免再产生 README、quickstart、架构说明
互相漂移的第三套契约。

## 6. 0.4 的刻意暂缓项

不要在普通修复中顺手引入全屏 Textual TUI、MCP、Worktree、Agent Teams、
自动 Git commit/undo 或 TOML/keyring。OS sandbox 已由 014 change 定义；
后续扩大其平台或覆盖范围仍必须单独开 SDD change，先定义可观察边界、
迁移策略和回滚路径。
