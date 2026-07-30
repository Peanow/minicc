# CoreCoder

> 原名 **NanoCoder**，为避免与 [Nano-Collective/nanocoder](https://github.com/Nano-Collective/nanocoder) 混淆而改名。旧链接自动跳转到这里。


[English](README.md) | [中文](README_CN.md) | [Claude Code 源码深度导读（7 篇）](article/)

[![PyPI](https://img.shields.io/pypi/v/corecoder)](https://pypi.org/project/corecoder/)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://github.com/he-yufeng/CoreCoder/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/CoreCoder/actions)

> **分支说明：** 本仓库是在上游
> [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder) 基础上的实验性增强
> Fork。上游提供最小 Agent Loop、基础工具和架构文章；本分支正在扩展实例级
> 工具注册、Skills、Hooks、长期记忆和结构化 Trace，目标是构建面向多模型、
> 本地模型的可观测 Coding Agent 实验平台。

成熟 Coding Agent 已经证明了产品价值，但上下文、记忆和工具策略通常难以观察、
修改和复现。本分支不仅关心“能否完成任务”，还关心为什么成功、失败发生在哪一轮、
消耗了多少上下文，以及切换模型或策略后结果如何变化。

---

```
$ corecoder -m kimi-k2.5

You > 读一下 main.py，修掉拼错的 import

  > read_file(file_path='main.py')
  > edit_file(file_path='main.py', ...)

--- a/main.py
+++ b/main.py
@@ -1 +1 @@
-from utils import halper
+from utils import helper

修好了：halper → helper。
```

## 你能得到什么

Claude Code 51 万行源码提炼出来的 7 个核心模式：

| 设计模式 | Claude Code | CoreCoder |
|---|---|---|
| 搜索替换编辑（唯一匹配 + diff） | FileEditTool | `tools/edit.py` — 70 行 |
| 并行工具执行 | StreamingToolExecutor（530行） | `agent.py` — ThreadPool |
| 三层上下文压缩 | HISTORY_SNIP → Microcompact → CONTEXT_COLLAPSE | `context.py` — 145 行 |
| 子代理隔离上下文 | AgentTool（1,397行） | `tools/agent.py` — 50 行 |
| 危险命令拦截 | BashTool（1,143行） | `tools/bash.py` — 95 行 |
| 会话持久化 | QueryEngine（1,295行） | `session.py` — 65 行 |
| 动态系统提示词 | prompts.ts（914行） | `prompt.py` — 35 行 |

每个模式都是可运行的实现，不是流程图，不是博客文章。

## 安装

```bash
pip install corecoder
```

选你的模型，任何 OpenAI 兼容 API 都行。可以 `export` 环境变量，也可以在项目根目录放一个 `.env` 文件：

```bash
# Kimi K2.5
export OPENAI_API_KEY=你的key OPENAI_BASE_URL=https://api.moonshot.ai/v1
corecoder -m kimi-k2.5

# Claude Opus 4.6（通过 OpenRouter）
export OPENAI_API_KEY=你的key OPENAI_BASE_URL=https://openrouter.ai/api/v1
corecoder -m anthropic/claude-opus-4-6

# OpenAI GPT-5
export OPENAI_API_KEY=sk-...
corecoder -m gpt-5

# DeepSeek V3
export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.deepseek.com
corecoder -m deepseek-chat

# Qwen 3.5
export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
corecoder -m qwen-max

# Ollama（本地）
export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1
corecoder -m qwen3:32b

# 单次模式
corecoder -p "给 parse_config() 加上错误处理"

# 同时记录 JSONL 执行轨迹
corecoder -p "修复测试失败" --trace .tmp/run.jsonl

# 只读分析，不允许文件写入
corecoder --permission-mode read-only
```

## 项目指令与 Skills

- CoreCoder 从 Git 根目录到当前目录依次加载 `AGENTS.md`；
  同目录中的 `AGENTS.override.md` 优先。
- 如果根目录没有 AGENTS 文件，会兼容读取根目录 `CLAUDE.md`。
- 推荐 Skill 结构为 `.agents/skills/<name>/SKILL.md`，系统提示只放名称、
  描述和路径，调用时才加载完整内容。
- 旧 `.corecoder/skills/*.md` 仍可使用，但仅作为兼容格式。

## 权限模式

- `read-only`：允许读取、搜索和少量只读 Shell 命令。
- `workspace-write`：允许工作区内编辑和一小组已分类的只读 Shell 命令；代码执行、
  联网、破坏性、Shell 组合或未知命令需要交互确认，非交互模式默认拒绝。
- `full-access`：跳过应用权限层，仍会经过 Bash 工具自身的危险命令检查。

每次 Shell 决策都会记录 `read-only`、`workspace-execution`、`network`、
`destructive`、`shell-composition` 或 `unknown` 风险类别；评测汇总会按风险类别
统计拒绝次数。

这些规则是 Agent 运行时的应用层控制，不是操作系统沙箱。

## 上下文策略

```bash
corecoder --context-strategy truncate --tokenizer approx
corecoder --context-strategy summary
corecoder --context-strategy hybrid
```

- `truncate`：裁剪旧工具输出，紧急情况下做确定性折叠，不额外调用 LLM。
- `summary`：跳过早期裁剪，直接用 LLM 总结旧消息。
- `hybrid`：工具裁剪、结构化摘要和硬折叠组合，也是默认策略。

`--tokenizer auto` 会对 tiktoken 支持且本地编码可用的模型使用精确计数；
未知模型（包括当前 DeepSeek 配置）明确回退到 `approx`。Trace 会记录实际使用的
计数器，避免把估算 token 当成精确结果。精确计数支持通过
`pip install "corecoder[tokenizer]"` 安装。

## Trace Replay 与 HTML 报告

```bash
corecoder replay .tmp/run.jsonl
corecoder report .tmp/run.jsonl -o .tmp/run.html
```

Replay 不调用模型、也不重新执行工具，只校验 LLM/工具/Run 生命周期是否完整，
重建调用数、token、耗时、状态和修改文件摘要。HTML 报告是无外部资源的单文件，
可以直接用于调试或项目演示；工具输出会经过 HTML 转义。

Trace 还会为每轮模型请求记录规范化指纹。Runtime Replay 不调用 API，而是把已录制
响应重新送入一个新的 Agent，在复制出的 fixture 中执行受支持的文件工具：

```bash
corecoder runtime-replay benchmarks/results/run/cases/case/trace.jsonl \
  --fixture benchmarks/tasks/python-inclusive-range \
  -o .tmp/runtime-replay
```

回放会比较请求指纹、工具结果、最终回答和修改文件。出于安全边界，它拒绝
`full-access` 录制，以及实际执行过 Bash 或子 Agent 的录制；回放期间也不会执行
项目 Shell Hook。

## 可复现评测

```bash
# 只校验并展开任务 × 模型 × 策略矩阵，不调用 API
corecoder eval benchmarks/local-v1.json --dry-run

# 隔离运行一个 case，并保留 Trace、日志、哈希和指标
corecoder eval benchmarks/local-v1.json \
  --task python-safe-path --strategy hybrid-workspace \
  -o benchmarks/results/local-v1-smoke
```

当前包含 18 个刻意保持未解决状态的本地任务，覆盖边界修复、解析、状态、路径安全、
多文件修改、分层指令、重试、配置合并、依赖排序、脱敏、批处理、游标分页、配置
优先级、事件去重、SSE、工具参数校验、消息预算和熔断器。评测器会在运行前后校验
`verify.py` 哈希，避免 Agent 通过篡改测试“刷成功率”。证据目录格式和指标口径见
[`benchmarks/README.md`](benchmarks/README.md)。

多个结果目录可以生成单文件对比报告：

```bash
corecoder compare benchmarks/results/run-a benchmarks/results/run-b \
  -o .tmp/comparison.html
```

报告按模型/策略汇总成功率、token、墙钟时间、可选成本、策略拒绝和校验器完整性，
并生成逐任务结果矩阵。

提交评测证据前，先审计原始 Trace 并只导出可移植指标与哈希：

```bash
corecoder evidence .tmp/local-v1-run \
  -o benchmarks/results/local-v1-reviewed
```

导出器会逐 case 对照 Trace 生命周期和结果指标、检查汇总、拒绝结果中的疑似凭证、
净化可提交的 manifest，并保留源文件 SHA-256。Trace 正文、Agent 日志、SQLite
Memory 和临时工作区不会进入证据目录，符合仓库的安全提交规则。

## 架构

整个项目一目了然：

```
corecoder/
├── cli.py            REPL + 命令                   218 行
├── agent.py          Agent 循环 + 并行执行          122 行
├── llm.py            流式客户端 + 重试              156 行
├── context.py        三层压缩                       196 行
├── session.py        会话保存/恢复                   68 行
├── prompt.py         系统提示词                      33 行
├── config.py         环境变量配置                    55 行
└── tools/
    ├── bash.py       Shell + 安全 + cd 追踪         115 行
    ├── edit.py       搜索替换 + diff                  85 行
    ├── read.py       文件读取                         53 行
    ├── write.py      文件写入                         36 行
    ├── glob_tool.py  文件搜索                         47 行
    ├── grep.py       内容搜索                         78 行
    └── agent.py      子代理生成                       58 行
```

## 当库用

```python
from corecoder import Agent, LLM

llm = LLM(model="kimi-k2.5", api_key="your-key", base_url="https://api.moonshot.ai/v1")
agent = Agent(llm=llm)
response = agent.chat("找出项目里所有 TODO 注释并列出来")
```

## 加自定义工具（约 20 行）

```python
from corecoder.tools.base import Tool

class HttpTool(Tool):
    name = "http"
    description = "请求一个 URL。"
    parameters = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}

    def execute(self, url: str) -> str:
        import urllib.request
        return urllib.request.urlopen(url).read().decode()[:5000]
```

## 命令

```
/model           查看当前模型
/model <名称>    切换模型
/compact         压缩上下文（对标 Claude Code 的 /compact）
/tokens          查看 token 用量 + 费用估算
/diff            查看本次会话修改的文件
/save            保存会话
/sessions        列出已保存的会话
/reset           清空历史
quit             退出
```

保存的会话 ID 会先安全化再作为文件名，恢复数据始终留在 `~/.corecoder/sessions` 目录内。

## 对比

|  | Claude Code | Claw-Code | Aider | CoreCoder |
|---|---|---|---|---|
| 代码量 | 51万行（闭源） | 10万+行 | 5万+行 | **最小核心 + 可测试扩展层** |
| 模型 | 仅 Anthropic | 多模型 | 多模型 | **任意 OpenAI 兼容** |
| 能通读吗？ | 不能 | 很难 | 有点费劲 | **模块化 Python** |
| 适合 | 直接用 | 直接用 | 直接用 | **理解、观测、评测 Agent** |

## 源码导读

我还写了 [7 篇 Claude Code 架构深度导读](article/)：Agent 循环、工具系统、上下文压缩、流式执行、多 Agent、隐藏功能。想知道 CoreCoder 为什么这样设计，从那里开始。

## FAQ

**这个 Fork 支持哪些扩展能力？**

当前支持项目级 Skills、生命周期 Hooks、只读子 Agent、SQLite
跨会话记忆和 JSONL Trace。MCP、操作系统级沙箱、评测报告与完整 Replay
仍在后续路线中；当前 Bash 防护属于应用层策略，不能替代容器或 OS 沙箱。

## License

MIT。Fork，然后拿去造更好的东西，如果能标注此出处就更好了。

---

作者 **[何宇峰](https://github.com/he-yufeng)** · Agentic AI Researcher @ Moonshot AI (Kimi)

[Claude Code 源码分析（知乎 17 万阅读，6000收藏）](https://zhuanlan.zhihu.com/p/1898797658343862272)
