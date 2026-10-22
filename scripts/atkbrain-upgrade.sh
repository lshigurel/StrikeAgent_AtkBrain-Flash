#!/usr/bin/env bash
# 把本机源码升到指定 GitHub tag，然后按部署方式重启。
# 用法: scripts/atkbrain-upgrade.sh <tag>
# 不碰 backend/data、*.env、node_modules。不改 git config、不 force push。
set -euo pipefail

TAG="${1:-}"
[[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "error: 非法 tag: ${TAG}" >&2; exit 1; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv312"
PY="$VENV/bin/python"
SLUG="${ATKBRAIN_GITHUB_REPO:-Yean-Sec/StrikeAgent_AtkBrain-Flash}"
SLUG="${SLUG#https://github.com/}"
SLUG="${SLUG#http://github.com/}"
SLUG="${SLUG%.git}"
LOG_DIR="$REPO/backend/data/logs"
mkdir -p "$LOG_DIR"

NODE_BIN="$(find "$REPO/.runtime" -maxdepth 4 -type f -name node -perm -u+x 2>/dev/null | head -n 1)"
if [[ -n "$NODE_BIN" ]]; then
  export PATH="$(dirname "$NODE_BIN"):$REPO/.runtime/pi/node_modules/.bin:$VENV/bin:$PATH"
else
  export PATH="$VENV/bin:$PATH"
fi

IN_DOCKER=0
if [[ -f /.dockerenv ]]; then
  IN_DOCKER=1
fi

echo "[*] $(date -Iseconds) upgrade → $TAG  repo=$REPO slug=$SLUG docker=$IN_DOCKER"

hash_of() {
  if [[ -f "$1" ]]; then sha256sum "$1" | awk '{print $1}'; else echo ""; fi
}

REQ_BEFORE="$(hash_of "$REPO/backend/requirements.txt")"
LOCK_BEFORE="$(hash_of "$REPO/frontend/package-lock.json")"
PKG_BEFORE="$(hash_of "$REPO/frontend/package.json")"

if [[ -d "$REPO/.git" ]]; then
  echo "[*] git fetch --tags"
  git -C "$REPO" fetch --tags origin
  if git -C "$REPO" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    git -C "$REPO" checkout --detach "tags/$TAG"
  elif git -C "$REPO" rev-parse -q --verify "refs/tags/v$TAG" >/dev/null; then
    git -C "$REPO" checkout --detach "tags/v$TAG"
  else
    git -C "$REPO" checkout --detach "$TAG"
  fi
else
  echo "[*] 无 .git，下载 GitHub source tarball"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  AUTH=()
  if [[ -n "${ATKBRAIN_GITHUB_TOKEN:-}" ]]; then
    AUTH=(-H "Authorization: Bearer ${ATKBRAIN_GITHUB_TOKEN}")
  fi
  ARCHIVE="$TMP/src.tgz"
  URL="https://api.github.com/repos/${SLUG}/tarball/${TAG}"
  if ! curl -fsSL "${AUTH[@]}" -o "$ARCHIVE" "$URL"; then
    URL="https://github.com/${SLUG}/archive/refs/tags/${TAG}.tar.gz"
    curl -fsSL "${AUTH[@]}" -o "$ARCHIVE" "$URL"
  fi
  mkdir -p "$TMP/unpacked"
  tar -xzf "$ARCHIVE" -C "$TMP/unpacked"
  SRC="$(find "$TMP/unpacked" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "$SRC" && -d "$SRC" ]] || { echo "error: tarball 里没有目录" >&2; exit 1; }
  if command -v rsync >/dev/null; then
    rsync -a \
      --exclude '.git/' \
      --exclude 'backend/data/' \
      --exclude 'frontend/node_modules/' \
      --exclude 'frontend/dist/' \
      --exclude '*.env' \
      --exclude 'backend/.env' \
      --exclude 'backend/data/atkbrain-claude.env' \
      "$SRC"/ "$REPO"/
  else
    echo "[*] 无 rsync，用 tar 覆盖（仍跳过 data/node_modules）"
    tar -C "$SRC" --exclude='backend/data' --exclude='frontend/node_modules' --exclude='.git' -cf - . \
      | tar -C "$REPO" --exclude='backend/data' --exclude='frontend/node_modules' -xf -
  fi
fi

REQ_AFTER="$(hash_of "$REPO/backend/requirements.txt")"
LOCK_AFTER="$(hash_of "$REPO/frontend/package-lock.json")"
PKG_AFTER="$(hash_of "$REPO/frontend/package.json")"

pip_install() {
  if [[ -x "$VENV/bin/python" ]]; then
    echo "[*] 安装到 $VENV"
    "$VENV/bin/python" -m pip install -r "$REPO/backend/requirements.txt"
  elif [[ -x /opt/atkbrain/venv/bin/pip ]]; then
    /opt/atkbrain/venv/bin/pip install -r "$REPO/backend/requirements.txt"
  else
    echo "error: 找不到 $VENV/bin/python 或 /opt/atkbrain/venv/bin/pip" >&2
    exit 1
  fi
}

if [[ -n "$REQ_AFTER" && "$REQ_AFTER" != "$REQ_BEFORE" ]]; then
  echo "[*] requirements.txt 有变，pip install"
  pip_install
fi
if [[ ("$LOCK_AFTER" != "$LOCK_BEFORE" || "$PKG_AFTER" != "$PKG_BEFORE") && -d "$REPO/frontend" ]]; then
  echo "[*] frontend 依赖有变，npm install"
  command -v npm >/dev/null || { echo "error: 找不到 npm" >&2; exit 1; }
  (cd "$REPO/frontend" && npm install)
fi

if [[ "$IN_DOCKER" -eq 1 ]]; then
  if [[ -f "$REPO/frontend/package.json" ]]; then
    echo "[*] 容器内编前端"
    command -v npm >/dev/null || { echo "error: 找不到 npm" >&2; exit 1; }
    (cd "$REPO/frontend" && npm install && npx vite build)
  fi
  echo "[*] 重启控制台进程"
  sleep 1
  if [[ -n "${ATKBRAIN_UPGRADE_PID:-}" ]]; then
    kill -TERM "${ATKBRAIN_UPGRADE_PID}" 2>/dev/null || true
  fi
  pkill -f 'python.*atkbrain.main' || true
  echo "[*] upgrade done $(date -Iseconds)"
  exit 0
fi

if systemctl cat atkbrain-flash-backend.service >/dev/null 2>&1; then
  echo "[*] 重新渲染 unit 并重启 systemd"
  if [[ -x "$REPO/scripts/atkbrain-backend.sh" ]]; then
    "$REPO/scripts/atkbrain-backend.sh" restart
  else
    systemctl restart atkbrain-flash-backend.service
  fi
  if [[ -x "$REPO/scripts/atkbrain-frontend.sh" ]]; then
    "$REPO/scripts/atkbrain-frontend.sh" restart
  else
    systemctl restart atkbrain-flash-frontend.service
  fi
elif [[ -f "$REPO/compose.yaml" ]] && command -v docker >/dev/null 2>&1; then
  echo "[*] docker compose 重建镜像"
  extra=()
  if [[ -f "$REPO/deploy/compose.build.yaml" ]]; then
    extra=(-f "$REPO/deploy/compose.build.yaml")
  fi
  docker compose -f "$REPO/compose.yaml" "${extra[@]}" up -d --build
else
  echo "error: 没有 systemd unit，也没有 docker compose" >&2
  exit 1
fi
echo "[*] upgrade done $(date -Iseconds)"
