#!/bin/bash
# 启动文档解析任务消费者

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE_DIR="$SCRIPT_DIR"

echo "========================================="
echo "  Starting Document Parse Task Consumer"
echo "========================================="
echo ""

# 设置 PYTHONPATH（确保能找到 common 和 services 模块）
export PYTHONPATH="/Users/caijing/projects/galaxy_rag/jusure_microservices:/Users/caijing/projects/galaxy_rag:$PYTHONPATH"

# 日志文件
LOG_FILE="/tmp/parse_task_consumer.log"

echo "Project Root: $PROJECT_ROOT"
echo "Service Dir:  $SERVICE_DIR"
echo "Log File:     $LOG_FILE"
echo ""

# 启动服务
echo "Starting consumer..."
cd "$SERVICE_DIR"
nohup python -u parse_task_consumer.py > "$LOG_FILE" 2>&1 &
PID=$!

echo "Consumer started with PID: $PID"
echo ""
echo "To view logs:"
echo "  tail -f $LOG_FILE"
echo ""
echo "To stop:"
echo "  kill $PID"
echo ""
echo "========================================="
echo "  Consumer is running"
echo "========================================="
