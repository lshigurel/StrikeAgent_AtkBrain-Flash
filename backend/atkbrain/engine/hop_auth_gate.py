"""过门判定：假否证不能关 hop_auth；SSH 先 banner、只用字面量。

赛道无关。不写题面路径、厂商口令或网段口诀。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .intranet_reach import (
    has_verified_precondition,
    kali_direct_intranet_reason,
)

HOP_AUTH_FALSE_DISPROVE_MSG = (
    "未证明认证处理接口收到方法与请求体（或 SSH 尚未出 banner）之前，"
    "不能否证 hop_auth。"
)
HOP_AUTH_NUDGE_MSG = (
    "经已验证跳板看到活着的邻机后，本轮主线是 hop_auth："
    "用图上或简报已有字面量账密/token（含授权测试身份），经该跳板把认证请求体送到邻机处理接口。"
    "无请求体的空 POST 不能否证。禁止本机直连，禁止喷字典，禁止再把扫段空号扩进 Scope。"
)
SITUATION_HOP_AUTH = (
    "【局面·邻机过门】本轮第一动作必须经已有立足点 shell、已验证 SSRF/代理参数、"
    "或入口上的转发端口，把认证请求体或 SSH 横幅送到已认领 hop_auth 的那一跳。"
    "禁止本机直连，禁止喷字典，禁止回头打已交过旗的入口。"
    "另两格仍可打未授权/跳板正交面，但不能替代这一跳过门。"
)
DELIVERY_FILE = ".atkbrain_hop_delivery.json"
HOP_AUTH_NO_PRECONDITION_MSG = (
    "没有可达前置条件，尚未碰到该跳身份面，不能否证 hop_auth。"
)
SSH_NEED_BANNER_MSG = (
    "该入口转发端口还没有 SSH 横幅。先用 nc 或 ssh -o BatchMode 取 banner，"
    "不要把超时当成口令失败。"
)
SSH_NEED_LITERAL_MSG = (
    "sshpass 只用题面或图上已经出现的口令字面量；没有字面量时禁止喷口令。"
)
SSH_NO_SPRAY_MSG = "禁止用 hydra/medusa/ncrack 喷 SSH。banner 通了只试已出现的字面量。"
TIMEOUT_NOT_PASSWORD_NOTE = (
    "【系统】通道超时不是口令否证，不能 resolve_intent 关掉 hop_auth。先修转发。"
)
CHANNEL_FILE = ".atkbrain_ssh_channel.json"
_AUTH_METHOD_RE = re.compile(r"^(?:POST|PUT|PATCH)$", re.I)

_WRAPPERISH_RE = re.compile(
    r"外壳|根路径|无请求体|没有(?:请求)?体|登录页|未登录|"
    r"timeout|超时|短转发|通道(?:死|不通)|只收公钥|publickey",
    re.I,
)
_DELIVERED_RE = re.compile(
    r"认证(?:处理)?接口.{0,24}(?:收到|送达).{0,24}(?:请求体|body)|"
    r"表单\s*action.{0,16}(?:收到|送达)|"
    r"banner.{0,16}(?:已通|已出|SSH-)|"
    r"字面量.{0,24}Permission denied|"
    r"请求体.{0,16}已(?:收到|送达)",
    re.I,
)
_SSH_BANNER_RE = re.compile(r"SSH-[12]\.\d+", re.I)
_SSHPASS_RE = re.compile(r"\bsshpass\b", re.I)
_SPRAY_RE = re.compile(r"\b(?:hydra|medusa|ncrack)\b", re.I)
_SSH_BIN_RE = re.compile(r"(?:^|[/\s])ssh(?:\s|$)", re.I)
_TIMEOUT_RE = re.compile(r"timeout after\s+\d+s", re.I)
_LOGIN_PAGE_RE = re.compile(
    r'type\s*=\s*["\']password|name\s*=\s*["\']pass(?:word)?|'
    r"<form[^>]{0,80}(?:login|登录)|"
    r"(?:用户名|密码|登录)(?:</|\s)",
    re.I,
)
_INTENT_HOP_RE = re.compile(r"(?:^|::)hop_auth$", re.I)


def is_hop_auth_intent(intent: dict | None) -> bool:
    sk = str((intent or {}).get("strategy_key") or "")
    tac = sk.split("::")[-1] if "::" in sk else sk
    return tac == "hop_auth" or bool(_INTENT_HOP_RE.search(sk))


def false_hop_auth_disprove_reason(summary: str | None, fingerprint: str | None = None) -> str | None:
    blob = f"{summary or ''} {fingerprint or ''}"
    delivered = bool(_DELIVERED_RE.search(blob))
    wrapperish = bool(_WRAPPERISH_RE.search(blob))
    if delivered and not wrapperish:
        return None
    return HOP_AUTH_FALSE_DISPROVE_MSG


def refuse_hop_auth_disprove(
    intent: dict | None,
    *,
    verified: bool,
    summary: str | None = None,
    fingerprint: str | None = None,
    graph: dict | None = None,
) -> str | None:
    if verified or not is_hop_auth_intent(intent):
        return None
    if graph is not None and not has_verified_precondition(graph):
        return HOP_AUTH_NO_PRECONDITION_MSG
    return false_hop_auth_disprove_reason(summary, fingerprint)


def _channel_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir or "", CHANNEL_FILE)


def load_ssh_banners(workspace_dir: str) -> dict[str, dict]:
    path = _channel_path(workspace_dir)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.loads(fh.read() or "{}")
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def remember_ssh_banner(workspace_dir: str, host: str, port: int | None, output: str) -> bool:
    if not workspace_dir or not _SSH_BANNER_RE.search(output or ""):
        return False
    h = (host or "").strip().lower()
    if not h:
        return False
    key = f"{h}:{int(port)}" if port else h
    data = load_ssh_banners(workspace_dir)
    data[key] = {"banner": True}
    if port:
        data[h] = {"banner": True}
    try:
        os.makedirs(workspace_dir, exist_ok=True)
        with open(_channel_path(workspace_dir), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except Exception:
        return False
    return True


def banner_ok(workspace_dir: str, host: str, port: int | None) -> bool:
    data = load_ssh_banners(workspace_dir)
    h = (host or "").strip().lower()
    if not h:
        return False
    if port and data.get(f"{h}:{int(port)}", {}).get("banner"):
        return True
    return bool(data.get(h, {}).get("banner"))


def looks_like_ssh_spray(command: str) -> bool:
    return bool(_SPRAY_RE.search(command or ""))


def looks_like_ssh_auth(command: str) -> bool:
    cmd = command or ""
    if _SSHPASS_RE.search(cmd) or looks_like_ssh_spray(cmd):
        return True
    if _SSH_BIN_RE.search(cmd) and "BatchMode" not in cmd:
        return True
    return False


def looks_like_ssh_probe(command: str) -> bool:
    cmd = command or ""
    if _SSHPASS_RE.search(cmd) or looks_like_ssh_spray(cmd):
        return False
    if re.search(r"\bnc\b", cmd) or "BatchMode" in cmd:
        return True
    return False


def looks_like_timeout_transport(stderr: str, stdout: str = "") -> bool:
    return bool(_TIMEOUT_RE.search(f"{stderr or ''} {stdout or ''}"))


def ssh_auth_block_reason(
    command: str,
    *,
    host: str,
    port: int | None = None,
    workspace_dir: str = "",
    allowed_secrets: set[str] | None = None,
) -> str | None:
    """入口转发上的 SSH 认证闸。内网 IP 直连由 kali_direct 先拦。"""
    cmd = command or ""
    if looks_like_ssh_spray(cmd):
        return SSH_NO_SPRAY_MSG
    if not looks_like_ssh_auth(cmd):
        return None
    if not banner_ok(workspace_dir, host, port):
        return SSH_NEED_BANNER_MSG
    if not _SSHPASS_RE.search(cmd):
        return None
    from ..agents.brief_creds import sshpass_password_from_cmd
    pw = sshpass_password_from_cmd(cmd)
    allowed = {str(x).lower() for x in (allowed_secrets or ()) if x}
    if not pw:
        return SSH_NEED_LITERAL_MSG
    if pw.lower() not in allowed:
        return SSH_NEED_LITERAL_MSG
    return None


def command_timeout_note(command: str, stderr: str, stdout: str = "") -> str:
    cmd = command or ""
    if not looks_like_timeout_transport(stderr, stdout):
        return ""
    if _SSHPASS_RE.search(cmd) or _SSH_BIN_RE.search(cmd) or re.search(r"\bnc\b", cmd):
        return TIMEOUT_NOT_PASSWORD_NOTE
    return ""


def http_login_notes(method: str, data: str | None, body: str | None, status: int | None = None) -> str:
    notes: list[str] = []
    if str(method or "GET").upper() == "POST" and not str(data or "").strip():
        notes.append("【系统】无请求体的 POST 不能作为口令否证，不能关闭 hop_auth。")
    hay = body or ""
    if _LOGIN_PAGE_RE.search(hay):
        notes.append("【系统】响应仍像登录页，未过身份门，不能否证 hop_auth。")
    elif status is not None and int(status) in (301, 302, 303, 307, 308) and _LOGIN_PAGE_RE.search(hay):
        notes.append("【系统】重定向后仍像未登录，不能否证 hop_auth。")
    return "\n".join(notes)


def _delivery_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir or "", DELIVERY_FILE)


def load_hop_deliveries(workspace_dir: str) -> dict:
    path = _delivery_path(workspace_dir)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.loads(fh.read() or "{}")
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def hop_delivered(workspace_dir: str, host: str = "") -> bool:
    data = load_hop_deliveries(workspace_dir)
    if not data:
        return False
    if host:
        h = (host or "").strip().lower()
        rec = data.get(h) or {}
        return bool(rec.get("http") or rec.get("ssh"))
    return any(
        isinstance(v, dict) and (v.get("http") or v.get("ssh"))
        for v in data.values()
    )


def remember_hop_delivery(workspace_dir: str, host: str, kind: str) -> bool:
    h = (host or "").strip().lower()
    if not workspace_dir or not h or kind not in ("http", "ssh"):
        return False
    data = load_hop_deliveries(workspace_dir)
    rec = dict(data.get(h) or {})
    rec[kind] = True
    data[h] = rec
    try:
        os.makedirs(workspace_dir, exist_ok=True)
        with open(_delivery_path(workspace_dir), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except Exception:
        return False
    return True


def looks_like_http_auth_delivery(
    method: str,
    data: str | None,
    *,
    url: str = "",
    hop_host: str = "",
) -> bool:
    """带 body 的认证请求才算送达；GET / 空 POST 不算。"""
    if not _AUTH_METHOD_RE.match(str(method or "GET").strip()):
        return False
    if not str(data or "").strip():
        return False
    if not hop_host:
        return True
    from .intranet_reach import private_hosts_from_text
    blob = f"{url or ''} {data or ''}"
    hosts = private_hosts_from_text(blob, limit=8)
    h = hop_host.strip().lower()
    return (not hosts) or h in hosts or h in (url or "").lower()


def maybe_record_http_delivery(
    workspace_dir: str,
    *,
    method: str,
    data: str | None,
    url: str = "",
    hop_host: str = "",
) -> bool:
    if not looks_like_http_auth_delivery(method, data, url=url, hop_host=hop_host):
        return False
    host = (hop_host or "").strip().lower()
    if not host:
        from .intranet_reach import private_hosts_from_text
        found = private_hosts_from_text(f"{url or ''} {data or ''}", limit=2)
        host = found[0] if found else ""
    if not host:
        return False
    return remember_hop_delivery(workspace_dir, host, "http")


def maybe_record_ssh_delivery(
    workspace_dir: str,
    command: str,
    *,
    host: str,
    port: int | None = None,
    allowed_secrets: set[str] | None = None,
) -> bool:
    if not looks_like_ssh_auth(command) or looks_like_ssh_spray(command):
        return False
    if ssh_auth_block_reason(
        command, host=host, port=port, workspace_dir=workspace_dir,
        allowed_secrets=allowed_secrets,
    ):
        return False
    if not _SSHPASS_RE.search(command or ""):
        return False
    return remember_hop_delivery(workspace_dir, host, "ssh")


def hop_auth_followup_note(
    *,
    situation: bool,
    workspace_dir: str = "",
    hop_host: str = "",
    allowed_secrets: set[str] | None = None,
) -> str:
    if not situation:
        return ""
    if hop_delivered(workspace_dir, hop_host):
        return ""
    extra = f"目标邻机 {hop_host}。" if hop_host else ""
    note = "【系统】" + extra + HOP_AUTH_NUDGE_MSG
    if allowed_secrets:
        note += "有授权测试身份时第一动作必须用这组字面量过登录口。"
    return note


def apply_kali_direct_reason(
    host: str,
    guard: Any,
) -> str | None:
    scope = getattr(guard, "scope", None)
    primary = ""
    try:
        primary = str((scope.targets or [""])[0] or "").split(":")[0]
    except Exception:
        primary = ""
    return kali_direct_intranet_reason(
        host,
        primary=primary,
        own_hosts=set(getattr(guard, "own_addrs", None) or ()),
        scope=scope,
        has_precondition=bool(getattr(guard, "has_intranet_precondition", False)),
        via_hosts=set(getattr(guard, "via_capability_hosts", None) or ()),
    )
