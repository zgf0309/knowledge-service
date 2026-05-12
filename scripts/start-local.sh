#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE_DIR="$(cd "$ROOT_DIR/.." && pwd)"
WEB_DIR="$WORKSPACE_DIR/knowledge-web"
cd "$ROOT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PYTHONPATH="$ROOT_DIR"
export NACOS_ENABLED="${NACOS_ENABLED:-false}"
export DEBUG="${DEBUG:-false}"
export PARSE_CONSUMER_WORKERS="${PARSE_CONSUMER_WORKERS:-4}"
export START_INFRA="${START_INFRA:-true}"
export START_DOCKER_MYSQL="${START_DOCKER_MYSQL:-false}"
export START_WEB="${START_WEB:-true}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-knowledge_service_local}"
LEGACY_COMPOSE_PROJECT="${LEGACY_COMPOSE_PROJECT:-jusure_microservices2}"
case "${DEBUG}" in
  true|false|0|1|yes|no|on|off) ;;
  *) DEBUG=false ;;
esac
mkdir -p logs

info() {
  echo ""
  echo "==> $1"
}

warn() {
  echo "[warn] $1"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

stop_pid_file() {
  local pid_file="$1"
  local name
  local pid

  [ -e "$pid_file" ] || return 0
  name="$(basename "$pid_file" .pid)"
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "[stop] ${name} pid=${pid}"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "[kill] ${name} pid=${pid}"
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
      echo "[stop] matching process: ${pattern}"
      pkill -f "$pattern" >/dev/null 2>&1 || true
    fi
  done
}

clean_local_processes() {
  info "清理旧本地服务进程"
  if [ -d logs ]; then
    for pid_file in logs/*.pid; do
      [ -e "$pid_file" ] || continue
      stop_pid_file "$pid_file"
    done
  fi
  stop_matching_processes
}

wait_url() {
  local name="$1"
  local url="$2"
  local max_attempts="${3:-45}"
  local attempt=1

  while [ "$attempt" -le "$max_attempts" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[ok]   ${name} ready"
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  warn "${name} 未在预期时间内就绪：${url}"
  return 0
}

wait_port() {
  local name="$1"
  local port="$2"
  local max_attempts="${3:-45}"
  local attempt=1

  while [ "$attempt" -le "$max_attempts" ]; do
    if lsof -i ":${port}" -sTCP:LISTEN -t >/dev/null 2>&1; then
      echo "[ok]   ${name} ready on port ${port}"
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  warn "${name} 未在预期时间内监听端口：${port}"
  return 0
}

start_infra() {
  case "${START_INFRA}" in
    false|0|no|off)
      warn "已跳过 Docker 存储环境启动（START_INFRA=${START_INFRA}）"
      return 0
      ;;
  esac

  if ! command_exists docker; then
    echo "[error] 未找到 docker，请先安装并启动 Docker Desktop"
    exit 1
  fi

  if [ -n "$LEGACY_COMPOSE_PROJECT" ] && [ "$LEGACY_COMPOSE_PROJECT" != "$COMPOSE_PROJECT_NAME" ]; then
    info "删除旧 Docker 项目：${LEGACY_COMPOSE_PROJECT}"
    docker compose -p "$LEGACY_COMPOSE_PROJECT" down --remove-orphans
  fi

  info "启动 Docker 存储环境（默认不启动 Docker MySQL，使用本机 MySQL: ${MYSQL_HOST:-127.0.0.1}:${MYSQL_PORT:-3306}）"
  docker compose --profile mysql down --remove-orphans
  if [ "${START_DOCKER_MYSQL}" = "true" ] || [ "${START_DOCKER_MYSQL}" = "1" ] || [ "${START_DOCKER_MYSQL}" = "yes" ] || [ "${START_DOCKER_MYSQL}" = "on" ]; then
    docker compose --profile mysql up -d mysql redis minio elasticsearch
  else
    docker compose up -d redis minio elasticsearch
  fi

  info "等待基础服务就绪"
  wait_port mysql "${MYSQL_PORT:-3306}"
  wait_port redis "${REDIS_PORT:-6379}"
  wait_url minio "http://localhost:${MINIO_PORT:-9000}/minio/health/live"
  wait_url elasticsearch "http://localhost:${ES_PORT:-9200}"
}

start_service() {
  local name="$1"
  local module="$2"
  local port="$3"
  local pid_file="logs/${name}.pid"
  local log_file="logs/${name}.log"

  if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1; then
    echo "[skip] ${name} already running pid $(cat "$pid_file")"
    return 0
  fi

  if lsof -i ":${port}" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "[skip] ${name} port ${port} already in use"
    return 0
  fi

  echo "[start] ${name} -> ${log_file}"
  SERVICE_NAME="$name" SERVICE_PORT="$port" .venv/bin/python -m "$module" > "$log_file" 2>&1 &
  echo $! > "$pid_file"
}

start_web() {
  case "${START_WEB}" in
    false|0|no|off)
      warn "已跳过前端启动（START_WEB=${START_WEB}）"
      return 0
      ;;
  esac

  if [ ! -d "$WEB_DIR" ]; then
    warn "未找到 knowledge-web 目录，跳过前端启动"
    return 0
  fi

  local pid_file="logs/knowledge-web.pid"
  local log_file="logs/knowledge-web.log"

  if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" >/dev/null 2>&1; then
    echo "[skip] knowledge-web already running pid $(cat "$pid_file")"
    return 0
  fi

  if lsof -i ":8000" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "[skip] knowledge-web port 8000 already in use"
    return 0
  fi

  if [ ! -d "$WEB_DIR/node_modules" ]; then
    warn "knowledge-web/node_modules 不存在，跳过前端启动。请先执行：cd ../knowledge-web && yarn install"
    return 0
  fi

  info "启动前端开发服务"
  if command_exists yarn; then
    (cd "$WEB_DIR" && yarn start:dev > "$ROOT_DIR/$log_file" 2>&1 & echo $! > "$ROOT_DIR/$pid_file")
  elif command_exists npm; then
    (cd "$WEB_DIR" && npm run start:dev > "$ROOT_DIR/$log_file" 2>&1 & echo $! > "$ROOT_DIR/$pid_file")
  else
    warn "未找到 yarn/npm，跳过前端启动"
  fi
}

clean_local_processes

if [ ! -x .venv/bin/python ]; then
  echo "[error] 未找到 .venv/bin/python，请先在 knowledge-service 下创建虚拟环境并安装依赖"
  echo "        python3 -m venv .venv"
  echo "        source .venv/bin/activate"
  echo "        pip install -r common/requirements.txt -r services/gateway/requirements.txt -r services/parser_service/requirements.txt -r services/knowledge_service/requirements.txt"
  exit 1
fi

start_infra

info "启动 Python 后端服务"
start_service knowledge_service services.knowledge_service.main 7101
start_service file_service services.file_service.main 7103
start_service model_service services.model_service.main 7104
start_service chat_service services.chat_service.main 7105
start_service parser_service services.parser_service.main 7106
start_service parse_task_consumer services.knowledge_service.parse_task_consumer 7111
start_service gateway services.gateway.main 8010

start_web

echo ""
echo "本地开发环境启动命令已发出。"
echo "后端网关：http://localhost:8010/health"
echo "前端页面：http://localhost:8000"
echo "查看网关日志：tail -f logs/gateway.log"
echo "查看前端日志：tail -f logs/knowledge-web.log"
echo "健康检查：./scripts/check-local.sh"
