# CoreCoder Quick Start

## 日常使用

```bash
cd /path/to/minicc
source .venv/bin/activate
corecoder
```

## 开发验证（推荐）

改完源码后，一键安装最新包 + 进入 workspace 验证：

```bash
./dev.sh
```

这会自动完成：
1. 激活虚拟环境
2. `pip install -e .` 安装最新代码
3. 进入 `workspace/` 目录
4. 启动 `corecoder`（模型配置从 `.env` 读取）

### 手动步骤

```bash
source .venv/bin/activate
pip install -e . -q          # 安装最新版
cd workspace                  # 进入验证目录
corecoder
```

## 退出

输入 `quit` 或按 `Ctrl+D`。

## 常用命令

| 命令 | 说明 |
|------|------|
| `/model` | 查看当前模型 |
| `/model <name>` | 切换模型 |
| `/compact` | 压缩上下文 |
| `/tokens` | 查看 token 用量和费用 |
| `/diff` | 查看本次会话修改的文件 |
| `/save` | 保存会话 |
| `/sessions` | 列出已保存的会话 |
| `/reset` | 清空历史 |
| `quit` | 退出 |

## 环境变量

已配置在 `.env` 中，启动时自动加载：

```
OPENAI_API_KEY=replace-with-your-api-key
OPENAI_BASE_URL=https://api.deepseek.com
CORECODER_MODEL=deepseek-v4-flash
CORECODER_PROVIDER=openai
CORECODER_EMBEDDING_PROVIDER=none
```

不要把真实密钥写入 README 或提交到 Git。复制 `.env.example` 为 `.env` 即可，
后者已经被 `.gitignore` 忽略。

## 记录执行轨迹

```bash
corecoder -p "分析 sample.py" --trace .tmp/sample-run.jsonl
```

Trace 会记录 LLM 轮次、工具调用、耗时、token 和上下文压缩事件，并对常见密钥格式脱敏。

## Workspace 验证目录

`workspace/` 是独立的功能验证沙盒，CoreCoder 在此操作不会影响项目源码。

- `workspace/sample.py` — 含故意 bug 的示例脚本，可让 CoreCoder 读取、修复、运行
- CoreCoder 产生的其他文件会被 `.gitignore` 忽略
