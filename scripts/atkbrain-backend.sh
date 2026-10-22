#!/usr/bin/env bash
# StrikeAgent_AtkBrain-Flash 后端常驻管理：经 systemd 拉起，崩溃自动重启。
# 用法: scripts/atkbrain-backend.sh {install|start|stop|restart|status|logs|uninstall}
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="$REPO/deploy/systemd/atkbrain-backend.service"
UNIT_DST="/etc/systemd/system/atkbrain-flash-backend.service"
LOG_DIR="$REPO/backend/data/logs"
PY="$REPO/.venv312/bin/python"

die() { echo "error: $*" >&2; exit 1; }
need_root() { [[ "$(id -u)" -eq 0 ]] || die "需要 root（sudo）"; }

# shellcheck source=/dev/null
source "$REPO/scripts/_atkbrain-systemd.sh"
# shellcheck source=/dev/null
source "$REPO/scripts/_atkbrain-render.sh"

require_runtime() {
  [[ -x "$PY" ]] || die "找不到 venv Python: $PY（先创建 .venv312 并安装 backend/requirements.txt）"
  [[ -f "$REPO/.env" ]] || die "缺少 $REPO/.env（cp .env.example .env）"
  "$PY" -c 'import fastapi, uvicorn, pydantic' >/dev/null 2>&1 \
    || die "venv 依赖不完整：$PY -m pip install -r $REPO/backend/requirements.txt"
}

wait_health() {
  local i out
  out="$(mktemp /tmp/atkbrain-health.XXXXXX.json)"
  for i in $(seq 1 30); do
    if (cd "$REPO/backend" && "$PY" -m atkbrain.healthcheck) >"$out" 2>/dev/null; then
      rm -f "$out"
      return 0
    fi
    sleep 1
  done
  rm -f "$out"
  return 1
}

cmd_install() {
  need_root
  require_runtime
  [[ -f "$UNIT_SRC" ]] || die "找不到 unit: $UNIT_SRC"
  mkdir -p "$LOG_DIR"
  retire_legacy_units
  migrate_legacy_runtime
  snapshot_claude_env
  kill_stray_backend
  render_atkbrain_unit "$UNIT_SRC" "$UNIT_DST"
  systemctl daemon-reload
  systemctl enable atkbrain-flash-backend.service
  systemctl restart atkbrain-flash-backend.service
  wait_health || true
  cmd_status
  echo "[*] 已安装并启动（venv: $PY）。之后请用本脚本 restart，勿在 shell 里前台跑 python -m atkbrain.main"
}

cmd_start() {
  need_root
  require_runtime
  if [[ ! -f "$UNIT_DST" ]]; then
    cmd_install
    return
  fi
  mkdir -p "$LOG_DIR"
  snapshot_claude_env
  systemctl start atkbrain-flash-backend.service
  wait_health || true
  cmd_status
}

cmd_stop() {
  need_root
  systemctl stop atkbrain-flash-backend.service
  cmd_status
}

cmd_restart() {
  need_root
  require_runtime
  mkdir -p "$LOG_DIR"
  if [[ ! -f "$UNIT_DST" ]]; then
    cmd_install
    return
  fi
  # 每次 restart 都从模板重新渲染，确保不会退回系统 Python。
  migrate_legacy_runtime
  snapshot_claude_env
  render_atkbrain_unit "$UNIT_SRC" "$UNIT_DST"
  systemctl daemon-reload
  systemctl restart atkbrain-flash-backend.service
  wait_health || true
  cmd_status
}

cmd_status() {
  local out
  systemctl --no-pager --full status atkbrain-flash-backend.service || true
  echo "---"
  out="$(mktemp /tmp/atkbrain-health.XXXXXX.json)"
  if [[ -x "$PY" ]] && (cd "$REPO/backend" && "$PY" -m atkbrain.healthcheck) >"$out" 2>/dev/null; then
    "$PY" - "$out" <<'PY' || echo "health: $(cat "$out")"
import json, sys
d = json.load(open(sys.argv[1]))
sdk = d.get("claude_sdk") or {}
print(f"health: ok={d.get('ok')} label={sdk.get('label')} running={len(d.get('running') or [])}")
PY
  else
    echo "health: DOWN (2333 无响应或 venv 不可用)"
  fi
  rm -f "$out"
}

cmd_logs() {
  need_root
  journalctl -u atkbrain-flash-backend.service -n "${1:-80}" --no-pager
}

cmd_uninstall() {
  need_root
  systemctl disable --now atkbrain-flash-backend.service 2>/dev/null || true
  rm -f "$UNIT_DST"
  systemctl daemon-reload
  echo "[*] 已卸载 systemd unit（进程已停）"
}

usage() {
  echo "用法: $0 {install|start|stop|restart|status|logs|uninstall}"
}

case "${1:-}" in
  install) cmd_install ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  logs) cmd_logs "${2:-80}" ;;
  uninstall) cmd_uninstall ;;
  *) usage; exit 1 ;;
esac
