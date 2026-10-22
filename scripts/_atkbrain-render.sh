#!/usr/bin/env bash
# 渲染 systemd unit：把仓库路径、运行用户和 Node 运行时写入模板。
# 由 atkbrain-backend.sh / atkbrain-frontend.sh source。

_atkbrain_stat_user() {
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    printf '%s\n' "$SUDO_USER"
  else
    stat -c '%U' "$REPO"
  fi
}

atkbrain_runtime_user() {
  _atkbrain_stat_user
}

atkbrain_runtime_group() {
  local u
  u="$(atkbrain_runtime_user)"
  id -gn "$u" 2>/dev/null || printf '%s\n' "$u"
}

atkbrain_runtime_home() {
  local u h
  u="$(atkbrain_runtime_user)"
  h="$(getent passwd "$u" 2>/dev/null | cut -d: -f6)"
  if [[ -n "$h" ]]; then
    printf '%s\n' "$h"
  else
    printf '/home/%s\n' "$u"
  fi
}

atkbrain_node_bin() {
  local n
  n="$(find "$REPO/.runtime" -maxdepth 4 -type f -name node -perm -u+x 2>/dev/null | head -n 1)"
  if [[ -n "$n" ]]; then
    dirname "$n"
  else
    printf '/usr/bin\n'
  fi
}

render_atkbrain_unit() {
  local src="$1" dst="$2"
  local run_user run_group run_home node_bin

  run_user="$(atkbrain_runtime_user)"
  run_group="$(atkbrain_runtime_group)"
  run_home="$(atkbrain_runtime_home)"
  node_bin="$(atkbrain_node_bin)"

  sed \
    -e "s|__REPO__|$REPO|g" \
    -e "s|__RUN_USER__|$run_user|g" \
    -e "s|__RUN_GROUP__|$run_group|g" \
    -e "s|__RUN_HOME__|$run_home|g" \
    -e "s|__NODE_BIN__|$node_bin|g" \
    "$src" > "$dst"
  chmod 644 "$dst"
}
