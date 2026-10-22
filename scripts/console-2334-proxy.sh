#!/usr/bin/env bash
# 控制台 :2334 HTTPS → 后端 HTTP :2333（安全入口生效）。
set -euo pipefail
BACKEND="${ATKBRAIN_PORT:-2333}"
FRONT="${ATKBRAIN_FRONTEND_PORT:-2334}"
BIND="${ATKBRAIN_CONSOLE_BIND:-0.0.0.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
bash "$REPO/scripts/ensure-console-tls.sh" "$REPO/backend/data/tls"
CERT="$REPO/backend/data/tls/combined.pem"
if command -v socat >/dev/null 2>&1; then
  exec socat "OPENSSL-LISTEN:${FRONT},fork,reuseaddr,bind=${BIND},cert=${CERT},verify=0" "TCP:127.0.0.1:${BACKEND}"
fi
echo "error: 需要 socat（OPENSSL-LISTEN）才能在 :${FRONT} 提供 HTTPS" >&2
exit 1
