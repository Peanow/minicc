# CLAUDE.md — CoreCoder 项目指南

## 项目概览

本仓库是上游 CoreCoder 的实验性增强 Fork。上游提供极简 Agent 核心和 7 篇架构文章；当前分支增加 Skills、Hooks、SQLite 长期记忆、实例级工具注册和 JSONL Trace，目标是形成可观测、可评测的多模型 Coding Agent 实验平台。

## 两种模式

### 学习模式

用户想理解 coding agent 的核心设计思想。基于 `corecoder/` 源码和 `article/` 下的 7 篇架构文章，解答问题、对比分析、引导学习。

关键参考材料：

| 源码文件 | 对应文章 | 核心主题 |
|----------|----------|----------|
| `corecoder/agent.py` | `02-agent-loop.md` | Agent 循环：消息 → LLM → 工具调用 → 执行 → 循环 |
| `corecoder/tools/edit.py` | `03-tool-system.md` | 搜索替换编辑（唯一匹配 + diff） |
| `corecoder/tools/bash.py` | `03-tool-system.md` | 危险命令拦截 + 工作目录跟踪 |
| `corecoder/tools/agent.py` | `06-multi-agent.md` | 子 Agent 隔离上下文 |
| `corecoder/context.py` | `04-context-compression.md` | 三层上下文压缩（snip → summarize → hard collapse） |
| `corecoder/llm.py` | `05-streaming-executor.md` | 流式 LLM 调用 + 工具调用增量解析 + 重试 |
| `corecoder/prompt.py` | `01-architecture-overview.md` | 动态系统提示词 |
| `corecoder/session.py` | `01-architecture-overview.md` | 会话持久化 |
| `corecoder/cli.py` | `01-architecture-overview.md` | REPL + 命令系统 |

学习模式下应做到：

- 引用源码和文章的具体位置回答问题
- 对比 Claude Code 原版实现与 CoreCoder 精简版的取舍
- 解释 **为什么** 这样设计，而非仅描述代码做了什么
- 中英文文章均可参考（`_EN` 后缀为英文版）

### 开发模式

为了更好的通过实践学习Coding Agent的设计思想，用户要在 CoreCoder 基础上二次开发并验证。需要帮助改代码、装包、在 workspace 中测试。

#### 开发迭代流程

```
改源码 → pip install -e . → 进 workspace 验证 → 重复
```

快捷命令：

```bash
./dev.sh    # 一键：激活 venv + 安装最新包 + 进 workspace + 启动 corecoder
```

手动步骤：

```bash
source .venv/bin/activate
pip install -e . -q
cd workspace
corecoder
```

设计新功能时优先依据公开文档、当前仓库代码和可复现实验，不依赖机器外的私有参考路径。

#### 开发模式工作规范

- 改完代码后提醒用 `./dev.sh` 或 `pip install -e .` 安装
- 新功能在 `workspace/` 下验证，不要改 workspace 外的文件做测试
- 运行 `pytest` 确保不破坏现有功能
- 新增工具参照 `corecoder/tools/base.py` 的 Tool 基类，并在 `corecoder/tools/__init__.py` 注册
- 新增运行时能力必须补充 Trace 事件与自动化测试

## 项目结构

```
corecoder/
├── cli.py            REPL + 命令系统              218 行
├── agent.py          Agent 循环 + 并行工具执行     122 行
├── llm.py            流式 LLM 客户端 + 重试        156 行（含 LiteLLM 后端）
├── context.py        三层上下文压缩                 196 行
├── session.py        会话保存/恢复                  68 行
├── prompt.py         动态系统提示词                 33 行
├── config.py         环境变量配置                   55 行
└── tools/
    ├── base.py       Tool 基类（新增工具继承此类）
    ├── bash.py       Shell 执行 + 安全检查          115 行
    ├── edit.py       搜索替换 + diff                85 行
    ├── read.py       文件读取                       53 行
    ├── write.py      文件写入                       36 行
    ├── glob_tool.py  文件搜索                       47 行
    ├── grep.py       内容搜索                       78 行
    └── agent.py      子 Agent 生成                  58 行

article/              7 篇 Claude Code 架构深度分析（中英双语）
workspace/            功能验证沙盒（CoreCoder 在此操作，不影响源码）
dev.sh                开发验证一键启动脚本
.env                  API 密钥和 Base URL（已 gitignore）
```

## 技术栈

- Python 3.10+，构建系统 hatchling
- 依赖：openai, rich, prompt_toolkit, python-dotenv
- 可选：litellm（非 OpenAI 兼容提供商）
- 默认开发配置：DeepSeek OpenAI 兼容端点，具体模型和密钥只保存在 `.env`

## 测试

```bash
source .venv/bin/activate
pytest
```

## 判断用户模式

如果用户问的是"为什么""怎么设计""Claude Code 是怎么做的"→ 学习模式。
如果用户说"加个功能""改一下""验证一下"→ 开发模式。
不明确时，优先按学习模式回应，开发意图明显时切换。
