#!/bin/bash

# API Gateway 启动脚本

set -e

echo "╔══════════════════════════════════════════════════╗"
echo "║   jusure_microservices API Gateway               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误：需要 Python 3"
    exit 1
fi

# 进入网关目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 安装依赖
echo "📦 检查依赖..."
pip3 install -r requirements.txt -q

# 设置环境变量
export GATEWAY_PORT=${GATEWAY_PORT:-7000}
export DEBUG=${DEBUG:-false}
export GATEWAY_CONFIG=${GATEWAY_CONFIG:-gateway_config.yaml}

echo ""
echo "🚀 启动 API Gateway..."
echo "📍 端口：${GATEWAY_PORT}"
echo "🔧 调试模式：${DEBUG}"
echo "📄 配置文件：${GATEWAY_CONFIG}"
echo ""

# 启动服务
python3 main.py
