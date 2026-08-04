#!/bin/bash
# dev.sh — 开发验证一键启动
# 安装最新 corecoder 包 + 进入 workspace 目录 + 启动
#
# 用法:
#   source dev.sh          # 推荐：在当前 shell 执行
#   bash dev.sh            # 也可以

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
source .venv/bin/activate

# 安装最新版与本地观测依赖（uv 创建的虚拟环境不一定包含 pip）
uv pip install --python "$SCRIPT_DIR/.venv/bin/python" -e '.[observability]' -q

# 进入 workspace 验证目录
cd workspace

# 启动 CoreCoder 并在 Agent 创建前挂载本地 OTLP exporter。
# 仅安装 observability 依赖并不会自动启用 Trace 导出。
corecoder --observe
