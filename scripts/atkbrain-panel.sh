#!/usr/bin/env bash
# 打印控制台入口 URL / 用户名 / 可读口令。
# Docker 一键部署：进容器跑（宿主机 python 没有 pydantic 等依赖）。
# 本机 systemd：优先使用仓库 .venv312 的 Python。
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

run_host() {
  cd "$REPO/backend"
  if [[ -x "$REPO/.venv312/bin/python" ]]; then
    exec "$REPO/.venv312/bin/python" -m atkbrain.panel "$@"
  fi
  exec /usr/bin/python3 -m atkbrain.panel "$@"
}

if [[ -f /.dockerenv ]]; then
  cd /opt/atkbrain/backend 2>/dev/null || cd "$REPO/backend"
  exec python -m atkbrain.panel "$@"
fi

if command -v docker >/dev/null 2>&1 && [[ -f "$REPO/compose.yaml" ]]; then
  if docker compose -f "$REPO/compose.yaml" ps --status running --services 2>/dev/null | grep -qx atkbrain \
    || docker ps --format '{{.Names}}' 2>/dev/null | grep -qx strikeagent-atkbrain-flash; then
    exec docker compose -f "$REPO/compose.yaml" exec -T atkbrain python -m atkbrain.panel "$@"
  fi
fi

run_host "$@"
