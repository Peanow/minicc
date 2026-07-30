# CoreCoder 实验平台路线图

本 Fork 基于 [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder)
二次开发。目标不是复刻成熟 Coding Agent 的全部功能，而是构建一个面向本地及
多模型、策略可插拔、执行可观察、结果可复现的实验平台。

## Milestone 1：可靠运行时与 Trace

- [x] OpenAI-compatible DeepSeek 配置与安全的 `.env.example`
- [x] 实例级 `ToolRegistry`，避免 Agent 之间共享工具绑定
- [x] Bash 工作目录和修改文件记录实例化
- [x] 只并行执行显式标记为安全的只读工具
- [x] SQLite 单库存储文本与可选 embedding
- [x] JSONL Trace、脱敏和结构化 `RunResult`
- [x] Clean install 与全量测试基线

## Milestone 2：策略与安全

- [x] 分层加载 `AGENTS.md`
- [x] `.agents/skills/<name>/SKILL.md` 与渐进式加载
- [x] `truncate`、`summary`、`hybrid` 可插拔上下文策略
- [x] TokenCounter 抽象、可选 tiktoken 与未知模型显式回退
- [x] `read-only`、`workspace-write`、`full-access` 权限模式
- [x] 路径与 symlink 越界防护、Shell 审批骨架
- [ ] 命令参数与网络行为细粒度分类

## Milestone 3：评测与报告

- [x] 无副作用 Trace 生命周期 Replay 与指标重建
- [ ] 基于录制响应的 Agent Runtime 确定性 Replay
- [ ] 18 个本地确定性任务与 6 个外部任务（当前 6/18、0/6）
- [x] 多模型、多策略评测 manifest 与选择性执行
- [x] 成功率、token、耗时、可选成本和策略拒绝指标
- [x] 校验器防篡改、fixture/manifest 哈希与隔离运行
- [x] 离线 HTML 单次运行报告
- [ ] 多模型、多策略对比报告

所有简历数字必须来自提交到仓库的原始评测结果，不使用预估提升。
