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

# 安装最新版（静默模式）
pip install -e . -q

# 进入 workspace 验证目录
cd workspace

# 启动 corecoder
corecoder -m glm-5.1-external
