# CoreCoder

> Formerly **NanoCoder** — renamed to avoid confusion with [Nano-Collective/nanocoder](https://github.com/Nano-Collective/nanocoder). All links from the old repo redirect here automatically.


[![PyPI](https://img.shields.io/pypi/v/corecoder)](https://pypi.org/project/corecoder/)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://github.com/he-yufeng/CoreCoder/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/CoreCoder/actions)

[中文](README_CN.md) | [English](README.md) | [Claude Code Architecture Deep Dive (7 articles)](article/)

> **Fork notice:** This repository is an experimental extension of
> [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder). The upstream
> project provides the minimal agent loop, base tools, and architecture
> articles. This fork adds instance-local tools, skills, hooks, cross-session
> memory, and structured traces toward an observable multi-model coding-agent
> experimentation platform.

The focus is not only whether an agent completes a task, but why it succeeds,
where it fails, how much context it consumes, and how model or strategy changes
affect the result.

## Project instructions, skills, and permissions

- `AGENTS.md` files load from the Git root down to the current directory;
  `AGENTS.override.md` wins within a directory.
- Skills use `.agents/skills/<name>/SKILL.md` and load progressively.
- Permission modes are `read-only`, `workspace-write`, and `full-access`.
  Workspace-write confines file tools to the workspace, directly allows a
  narrow set of classified read-only shell commands, and asks before code
  execution, network, destructive, composed, or unknown commands.

Every Shell decision records one of six risk classes: `read-only`,
`workspace-execution`, `network`, `destructive`, `shell-composition`, or
`unknown`. Non-interactive runs deny requests that require approval, and
evaluation summaries preserve denial counts by risk class.

The permission engine is an application policy layer, not an OS sandbox.

## Context strategy experiments

Choose `truncate`, `summary`, or `hybrid` with `--context-strategy`.
Truncate is deterministic and does not spend tokens on summarization; summary
uses an LLM to compact old turns; hybrid combines tool-output snipping,
structured summaries, and an emergency collapse.

`--tokenizer auto` uses tiktoken only when the optional package and a supported
local encoding are available, otherwise it records an explicit `approx`
fallback in the trace. Install exact OpenAI-model counting with
`pip install "corecoder[tokenizer]"`.

## Trace replay and local reports

```bash
corecoder replay .tmp/run.jsonl
corecoder report .tmp/run.jsonl -o .tmp/run.html
```

Replay is side-effect free: it neither calls a model nor executes a tool. It
validates run, LLM, tool, and result lifecycles and reconstructs aggregate
metrics. The report is a self-contained HTML timeline with escaped tool output.

For a stronger reproducibility check, traces now include a canonical fingerprint
of every model request. Runtime Replay feeds the recorded responses back through
a fresh Agent and re-executes supported file tools inside a copied fixture:

```bash
corecoder runtime-replay benchmarks/results/run/cases/case/trace.jsonl \
  --fixture benchmarks/tasks/python-inclusive-range \
  -o .tmp/runtime-replay
```

Runtime Replay does not call an API. It compares request fingerprints, tool
results, the final answer, and changed files. For safety it refuses full-access
recordings and recordings that actually executed Bash or a sub-agent; project
shell hooks are disabled during replay.

## Reproducible evaluations

```bash
# Validate and inspect the task × model × strategy matrix; no API call.
corecoder eval benchmarks/local-v1.json --dry-run

# Run one isolated case and preserve trace, logs, hashes, and metrics.
corecoder eval benchmarks/local-v1.json \
  --task python-safe-path --strategy hybrid-workspace \
  -o benchmarks/results/local-v1-smoke
```

The benchmark currently contains eighteen deliberately unsolved fixtures across
bug fixing, parsing, state, path security, multi-file editing, scoped
instructions, retries, configuration merging, dependency ordering, redaction,
lazy batching, cursor pagination, configuration precedence, event
deduplication, SSE parsing, tool argument validation, message budgeting, and
circuit breaking. Verifiers are hash-protected so an agent cannot pass by
rewriting its checks. See
[`benchmarks/README.md`](benchmarks/README.md) for the evidence format and
metric policy.

Compare one or more result directories in a self-contained report:

```bash
corecoder compare benchmarks/results/run-a benchmarks/results/run-b \
  -o .tmp/comparison.html
```

The report groups success, tokens, wall time, optional cost, policy denials,
and verifier-integrity failures by model/strategy, then builds a per-task
outcome matrix.

Before committing benchmark evidence, audit the source traces and export only
portable metrics and hashes:

```bash
corecoder evidence .tmp/local-v1-run \
  -o benchmarks/results/local-v1-reviewed
```

The exporter verifies trace lifecycles against every result, checks aggregate
totals, rejects credentials in run results, sanitizes the portable manifest,
and retains source SHA-256 hashes. Trace
bodies, agent logs, SQLite memory, and temporary workspaces are deliberately
excluded in accordance with the repository security rules.

---

```
$ corecoder -m kimi-k2.5

You > read main.py and fix the broken import

  > read_file(file_path='main.py')
  > edit_file(file_path='main.py', ...)

--- a/main.py
+++ b/main.py
@@ -1 +1 @@
-from utils import halper
+from utils import helper

Fixed: halper → helper.
```

## What You Get

The upstream minimal core distills seven architectural patterns; this fork adds
experimental strategy and observability layers:

| Pattern | Claude Code | CoreCoder |
|---|---|---|
| Search-and-replace editing (unique match + diff) | FileEditTool | `tools/edit.py` — 70 lines |
| Parallel tool execution | StreamingToolExecutor (530 lines) | `agent.py` — ThreadPool |
| 3-layer context compression | HISTORY_SNIP → Microcompact → CONTEXT_COLLAPSE | `context.py` — 145 lines |
| Sub-agent with isolated context | AgentTool (1,397 lines) | `tools/agent.py` — 50 lines |
| Dangerous command blocking | BashTool (1,143 lines) | `tools/bash.py` — 95 lines |
| Session persistence | QueryEngine (1,295 lines) | `session.py` — 65 lines |
| Dynamic system prompt | prompts.ts (914 lines) | `prompt.py` — 35 lines |

Every pattern is a real, runnable implementation — not a diagram or a blog post.

## Install

```bash
pip install corecoder
```

Pick your model — any OpenAI-compatible API works. You can `export` env vars or drop a `.env` file in your project root:

```bash
# Kimi K2.5
export OPENAI_API_KEY=your-key OPENAI_BASE_URL=https://api.moonshot.ai/v1
corecoder -m kimi-k2.5

# Claude Opus 4.6 (via OpenRouter)
export OPENAI_API_KEY=your-key OPENAI_BASE_URL=https://openrouter.ai/api/v1
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

# Ollama (local)
export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1
corecoder -m qwen3:32b

# One-shot mode
corecoder -p "add error handling to parse_config()"
```

### Non-OpenAI providers (Bedrock, Vertex, Cohere, …)

For providers without an OpenAI-compatible endpoint, install the optional LiteLLM extra:

```bash
pip install 'corecoder[litellm]'

export CORECODER_PROVIDER=litellm
export CORECODER_MODEL=anthropic/claude-3-haiku   # any LiteLLM model string
export ANTHROPIC_API_KEY=sk-ant-...
corecoder
```

LiteLLM routes through to 100+ providers (Bedrock, Vertex AI, Cohere, Groq, Replicate, Anyscale, etc.) using one model-string convention. The default `openai` backend is unchanged.

## Architecture

The whole thing fits in your head:

```
corecoder/
├── cli.py            REPL + commands               218 lines
├── agent.py          Agent loop + parallel tools    122 lines
├── llm.py            Streaming client + retry       156 lines
├── context.py        3-layer compression            196 lines
├── session.py        Save/resume                     68 lines
├── prompt.py         System prompt                   33 lines
├── config.py         Env config                      55 lines
└── tools/
    ├── bash.py       Shell + safety + cd tracking   115 lines
    ├── edit.py       Search-replace + diff            85 lines
    ├── read.py       File reading                     53 lines
    ├── write.py      File writing                     36 lines
    ├── glob_tool.py  File search                      47 lines
    ├── grep.py       Content search                   78 lines
    └── agent.py      Sub-agent spawning               58 lines
```

## Use as a Library

```python
from corecoder import Agent, LLM

llm = LLM(model="kimi-k2.5", api_key="your-key", base_url="https://api.moonshot.ai/v1")
agent = Agent(llm=llm)
response = agent.chat("find all TODO comments in this project and list them")
```

## Add Your Own Tools (~20 lines)

```python
from corecoder.tools.base import Tool

class HttpTool(Tool):
    name = "http"
    description = "Fetch a URL."
    parameters = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}

    def execute(self, url: str) -> str:
        import urllib.request
        return urllib.request.urlopen(url).read().decode()[:5000]
```

## Commands

```
/model           Show current model
/model <name>    Switch model mid-conversation
/compact         Compress context (like Claude Code's /compact)
/tokens          Token usage + cost estimate
/diff            Show files modified this session
/save            Save session to disk
/sessions        List saved sessions
/reset           Clear history
quit             Exit
```

Saved session IDs are sanitized before they become filenames, so resume data stays inside `~/.corecoder/sessions`.

## How It Compares

|  | Claude Code | Claw-Code | Aider | CoreCoder |
|---|---|---|---|---|
| Code | 512K lines (closed) | 100K+ lines | 50K+ lines | **Minimal core + testable extensions** |
| Models | Anthropic only | Multi | Multi | **Any OpenAI-compatible** |
| Readable? | No | Hard | Medium | **Small, modular Python** |
| Purpose | Use it | Use it | Use it | **Understand, instrument, evaluate** |

## The Deep Dive

I wrote [7 articles](article/) breaking down Claude Code's architecture — the agent loop, tool system, context compression, streaming executor, multi-agent, and 44 hidden feature flags. If you want to understand *why* CoreCoder is designed this way, start there.

## FAQ

**Which extension features does this fork support?**

It currently supports project skills, lifecycle hooks, read-only subagents,
SQLite cross-session memory, and JSONL execution traces. MCP, an OS-level
sandbox, evaluation reports, and full replay remain roadmap items. The current
Bash checks are an application policy layer, not a security sandbox.

## Related Projects

- **[CodeJoust](https://github.com/he-yufeng/CodeJoust)** — a CLI arena that races Claude Code, aider, Codex, and Gemini (Cursor + OpenHands next) on the same bug in isolated git worktrees, scores by tests+cost+diff+time, hands you the winning patch. If you ever wondered *which* AI coding CLI is actually better for your task, CodeJoust answers it empirically.
- **[AnyCoder](https://github.com/he-yufeng/AnyCoder)** — a practical terminal AI coding agent built on the same architecture as CoreCoder but with litellm, session persistence, and 100+ model support. Use this one if you want a tool; use CoreCoder if you want to read source.
- **[LiteBench](https://github.com/he-yufeng/LiteBench)** — one-command LLM / agent benchmark. Ships 7 built-in tasks (HumanEval/GSM8K/MMLU/...) and YAML-defined custom tasks, with a single-file HTML dashboard.
- **[RepoWiki](https://github.com/he-yufeng/RepoWiki)** — open-source DeepWiki alternative. `pip install repowiki`, one command to turn any local or GitHub repo into a wiki with dependency graph, architecture diagram, and LLM-generated module pages.

## License

MIT. Fork it, learn from it, ship something better. A mention of this project is appreciated.

---

Built by **[Yufeng He](https://github.com/he-yufeng)** · Agentic AI Researcher @ Moonshot AI (Kimi)

[Claude Code Source Analysis — 170K+ reads, 6000 bookmarks on Zhihu](https://zhuanlan.zhihu.com/p/1898797658343862272)
