#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

stop_pid_file() {
  local pid_file="$1"
  local pid
  local name

  [ -e "$pid_file" ] || return 0
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  name="$(basename "$pid_file" .pid)"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "[stop] $name pid=$pid"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "[kill] $name pid=$pid"
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$pid_file"
}

stop_matching_processes() {
  local patterns=(
    "services.knowledge_service.main"
    "services.file_service.main"
    "services.model_service.main"
    "services.chat_service.main"
    "services.parser_service.main"
    "services.knowledge_service.parse_task_consumer"
    "services.gateway.main"
    "max dev"
  )
  local pattern

  for pattern in "${patterns[@]}"; do
    if pgrep -f "$pattern" >/dev/null 2>&1; then
      echo "[stop] matching process: $pattern"
      pkill -f "$pattern" >/dev/null 2>&1 || true
    fi
  done
}

if [ -d logs ]; then
  for pid_file in logs/*.pid; do
    [ -e "$pid_file" ] || continue
    stop_pid_file "$pid_file"
  done
else
  echo "logs 目录不存在，继续检查残留进程"
fi

stop_matching_processes
