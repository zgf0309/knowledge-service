#!/usr/bin/env bash
set -euo pipefail

check_url() {
  local name="$1"
  local url="$2"
  if curl -fsS "$url" >/dev/null; then
    echo "[ok]   $name $url"
  else
    echo "[fail] $name $url"
  fi
}

check_url gateway "http://localhost:8010/health"
check_url knowledge_service "http://localhost:7101/health"
check_url file_service "http://localhost:7103/health"
check_url model_service "http://localhost:7104/health"
check_url chat_service "http://localhost:7105/health"
check_url parser_service "http://localhost:7106/health"
check_url knowledge_web "http://localhost:8000"
check_url minio "http://localhost:9000/minio/health/live"
check_url elasticsearch "http://localhost:9200"
