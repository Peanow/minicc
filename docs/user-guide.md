# CoreCoder 使用文档

CoreCoder 是一个运行在终端中的 coding agent。它可以读取和修改当前
workspace、运行经过权限策略检查的工具、流式展示模型输出，并将会话和
Trace 保存为可恢复、可审计的数据。

本文只描述 0.4 版本的用户契约；架构和后续开发请看
[开发说明](development.md)。

## 1. 安装

CoreCoder 要求 Python 3.10 或更高版本：

```bash
pip install corecoder
```

从源码运行：

```bash
git clone <repository-url>
cd minicc
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## 2. 配置模型

密钥只从环境变量或项目 `.env` 文件读取，不支持命令行传入密钥。常用
配置如下：

```bash
export OPENAI_API_KEY='your-key'
export CORECODER_MODEL='gpt-4o'
```

OpenAI-compatible 服务：

```bash
export OPENAI_API_KEY='your-key'
export OPENAI_BASE_URL='https://api.example.com/v1'
export CORECODER_MODEL='your-model'
```

本地 Ollama（兼容 OpenAI API）：

```bash
export OPENAI_API_KEY='ollama'
export OPENAI_BASE_URL='http://localhost:11434/v1'
export CORECODER_MODEL='qwen3:32b'
```

配置优先级为：内置默认值 → 环境变量 → CLI 参数。常用环境变量：

| 变量 | 用途 |
|---|---|
| `CORECODER_MODEL` | 默认模型 |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `CORECODER_API_KEY` | 模型密钥 |
| `OPENAI_BASE_URL` / `CORECODER_BASE_URL` | OpenAI-compatible 地址 |
| `CORECODER_PERMISSION_MODE` | 默认权限模式 |
| `CORECODER_CONTEXT_STRATEGY` | `truncate`、`summary` 或 `hybrid` |
| `CORECODER_TOKENIZER` | `auto`、`approx` 或 `tiktoken` |

检查本地配置：

```bash
corecoder doctor
corecoder doctor --connect
```

## 3. 交互式 Terminal

在目标项目目录启动：

```bash
corecoder
```

启动后输入自然语言任务，例如：

```text
读取 auth.py，修复测试失败的异常处理，并运行相关测试。
```

一次成功的 turn 会自动 checkpoint。恢复当前项目最近一次完整会话：

```bash
corecoder --continue
```

不保存 session、history、memory 的临时模式：

```bash
corecoder --ephemeral
```

### 输入控制

- `Enter` 提交输入。
- `Esc` 后按 `Enter` 插入换行；`/multiline` 可以切换 Enter 的行为。
- 输入状态按 `Ctrl+C` 清空当前 buffer；任务运行时按 `Ctrl+C` 取消任务。
- 空 buffer 按 `Ctrl+D` 退出；非空 buffer 不会误退出。
- `/editor` 使用 `$VISUAL` 或 `$EDITOR` 编辑多行 prompt。
- `//foo` 会把 `/foo` 作为普通文本发送给模型。
- 不要把用户输入当作命令参数处理；只有判断空输入时才使用 `strip()`。

### Slash commands

```text
/help       查看帮助和快捷键
/clear      清空当前对话
/resume     恢复最近一次 session；可追加 session ID
/model      查看或切换模型
/tokens     查看 token 和费用
/compact    手动压缩上下文
/diff       查看本次 session 的修改
/session    列出、恢复或删除 session
/skills     查看项目 Skills
/skill      激活一个 Skill
/memory     查看、搜索、保存或清理 memory
/observe    打开 Phoenix 状态
/multiline  切换多行输入模式
/editor     使用外部编辑器输入
/verbose    切换详细工具输出
/exit       退出
```

`/resume` 无参数时恢复当前项目最近一次 session，`/resume SESSION_ID`
恢复指定 session；恢复后会在终端滚动区显示完整的历史消息。原有的
`/session resume SESSION_ID` 仍然可用。

命令、模型、Skill、session ID 和文件路径均支持补全。未知 slash command
只显示建议，不会发送给模型。

## 4. 非交互运行

一次运行只能有一个输入来源：位置参数、`--prompt-file` 或 stdin。

```bash
corecoder run '解释这个项目的入口'
corecoder run --prompt-file task.md
corecoder run --prompt-file - < task.md
```

多个输入来源会返回参数错误。非交互运行默认 ephemeral；显式保存才会
写入 session：

```bash
corecoder run '修复解析器' --save-session
```

输出格式：

```bash
corecoder run '总结项目' --format auto
corecoder run '总结项目' --format plain
corecoder run '修复测试' --format jsonl > events.jsonl
```

- `auto`：TTY 使用 pretty，非 TTY 使用 plain。
- `plain`：stdout 只有最终回答；工具诊断写 stderr。
- `jsonl`：每行是 `{schema,event,run_id,timestamp,data}`，最后一行一定是
  `run_finished`。

退出码：

| 代码 | 含义 |
|---:|---|
| `0` | 任务完成 |
| `1` | 运行失败或被策略阻塞 |
| `2` | 参数或配置错误 |
| `130` | 用户中断 |

## 5. 权限和安全边界

启动时选择应用层权限策略：

```bash
corecoder --permission-mode read-only
corecoder --permission-mode workspace-write
corecoder --permission-mode full-access
corecoder --sandbox-network deny
corecoder --sandbox-network allow
```

工具必须声明 Effect：

```text
READ_FS | WRITE_FS | EXECUTE | NETWORK | APP_STATE_WRITE
```

- `read-only` 允许读取，禁止 workspace、memory 和应用状态写入。
- `workspace-write` 允许 workspace 内文件修改；执行、联网和未知 Effect
  需要交互审批，非交互模式拒绝。
- `full-access` 显式绕过 Bash 的 OS sandbox，但仍会经过工具自身的危险命令检查。
- 只有显式 `parallel_safe` 且完全只读的工具可以并行执行。

- Bash 默认使用 macOS `sandbox-exec` 将文件系统访问限制在 Agent 启动时的
  workspace，并默认禁止网络。`--sandbox-network allow` 或
  `CORECODER_SANDBOX_NETWORK=allow` 只解除 OS 网络限制，仍不会绕过 Policy
  审批。
- 应用层权限检查和 OS sandbox 是两层边界。沙箱覆盖 Agent 运行时的
  BashTool；直接调用任意 Python/subprocess API 仍不自动受保护。macOS 之外
  或找不到可用 OS sandbox 时，sandbox-required 的 Bash 执行会失败关闭，不会
  静默降级。

审批卡片会展示 Effect、风险、cwd、完整脱敏命令和目标路径。可选操作为
一次允许、拒绝、查看详情；只有 Policy 能生成精确规则时才会提供 session
允许。

## 6. Session

Session 按规范化 Git root 隔离，默认位置为：

```text
~/.corecoder/projects/<project-hash>/sessions/<session-id>.json
```

管理命令：

```bash
corecoder session list
corecoder session resume SESSION_ID
corecoder session delete SESSION_ID
```

Session 使用 schema v2、同目录临时文件和 `os.replace` 原子写入，并尽量
设置为 `0600`。损坏文件只报可读错误，不删除原文件；跨项目 resume 会被
拒绝。Session 不保存密钥，也不恢复上一次启动时的权限模式。

## 7. Trace、Replay 和实验

写入 Trace schema v2：

```bash
corecoder run '修复 bug' --trace .tmp/run.jsonl
corecoder trace replay .tmp/run.jsonl
corecoder trace report .tmp/run.jsonl -o .tmp/run.html
```

Replay 同时读取 v1 和 v2 Trace。当前版本的 Trace 可以在干净 fixture 中
进行 runtime replay：

```bash
corecoder trace runtime-replay .tmp/run.jsonl \
  --fixture benchmarks/tasks/python-inclusive-range \
  -o .tmp/runtime-replay
```

评测工具位于 `lab` 命令组：

```bash
corecoder lab eval benchmarks/local-v1.json --dry-run
corecoder lab compare results-a results-b -o .tmp/comparison.html
corecoder lab evidence .tmp/run -o benchmarks/results/reviewed
```

Phoenix 是可选能力：

```bash
pip install 'corecoder[observability]'
corecoder observe up
corecoder observe status
corecoder observe down
```

## 8. Python API

```python
import os
from pathlib import Path

from corecoder import Agent, LLM

agent = Agent(
    llm=LLM(model="gpt-4o", api_key=os.environ["OPENAI_API_KEY"]),
    workspace=Path.cwd(),
)
try:
    result = agent.run("找出所有 TODO 并给出修复建议")
    print(result.final_answer)
finally:
    agent.close()
```

稳定入口是 `Agent.run(prompt, observer=None)`。返回值 `RunResult` 包含本次
任务的 `run_id`、`status`、`final_answer`、`changed_files`、token、cost、
error 和 trace path。运行事件可以通过 observer 消费。

## 9. 当前限制

0.4 暂不提供全屏 TUI、MCP、Worktree、Agent Teams、自动 Git commit/undo、
TOML/keyring 配置和 OS sandbox。大模块的全面目录重构也不会脱离行为变更
单独进行。
