"""内网可达前置条件：没有 SSRF/shell/隧道就不能对内网操作。

赛道无关。不写题面路径、厂商口令或网段口诀。
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from ..scope import (
    Scope,
    _IP_RE,
    _norm_host,
    is_loopback,
    is_private,
    is_private_ip,
    same_pivot_lan,
)
from ..scope_pivot import PIVOT_MECHANISMS, SSRF_MECHANISMS

KIND_SHELL = "shell"
KIND_SSRF = "ssrf"
KIND_TUNNEL = "tunnel"

NO_PRECONDITION_MSG = (
    "只有内网线索，没有可达前置条件，不能对内网操作。"
    "先在已验证 SSRF、立足点 shell 或隧道上看到该主机，再经该能力访问。"
)
MUST_VIA_CAPABILITY_MSG = (
    "该主机是经跳板看见的本题内网，攻击机网卡到不了。"
    "把目标放进已验证 SSRF 参数，或在立足点 shell 上访问，"
    "或经入口上的转发端口；禁止本机直连。"
)
NOT_SEEN_VIA_CAPABILITY_MSG = (
    "该地址只是内网线索，尚未经已验证跳板观测到，不能从本机直连操作。"
)

_IPV4_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\b")
_TUNNEL_MARKERS = tuple(sorted(
    PIVOT_MECHANISMS - SSRF_MECHANISMS
)) + ("vpn", "socks", "端口转发", "隧道")
_RECON_SCAN_RE = re.compile(
    r"\b(?:arp|nmap|ping|ip\s+(?:neigh|a|addr|route)|hostname\s+-I)\b",
    re.I,
)
_HOSTS_FILE_CMD_RE = re.compile(
    r"\b(?:cat\s+/etc/hosts|getent\s+hosts)\b",
    re.I,
)
_RECON_CMD_RE = re.compile(
    r"\b(?:arp|nmap|ping|ip\s+(?:neigh|a|addr|route)|cat\s+/etc/hosts|"
    r"getent\s+hosts|hostname\s+-I)\b",
    re.I,
)
_LIVE_LINE_RE = re.compile(
    r"\b(?:open|http|https|ssh|登录|login|ssh-2\.0|\b220[\s-]|banner)\b",
    re.I,
)
TAG_LIVE = "via-live"
TAG_CLUE = "clue-only"
_VIA_TAGS = frozenset({
    "scope-expanded", "via-capability", "pivot", "ssrf",
    "shell_reachable", "port_forward", "socks_tunnel", TAG_LIVE,
})
_IDENTITY_RE = re.compile(
    r"登录|login|ssh(?:-|\b)|/22\b|\b22/tcp|password|pass(?:wd|word)|认证|口令",
    re.I,
)
_UNAUTH_LOOT_CATS = frozenset({
    "file_read", "lfi", "information_disclosure", "info_disclosure",
    "path_traversal", "arbitrary_file_read",
})


def _tagset(n: dict | None) -> set[str]:
    tags = (n or {}).get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {str(t).lower() for t in tags}


_PIVOT_TARGET_TAGS = frozenset({
    "lateral", "pivot", "internal", "scope-expanded", TAG_LIVE,
})


def node_is_entry_target(n: dict | None) -> bool:
    """入口黑点：带 entry，或未打跳板标签的 target。跳板发现的内网目标不算入口。"""
    n = n or {}
    key = str(n.get("key") or "")
    ntype = str(n.get("type") or "")
    if ntype != "target" and not key.startswith("target:"):
        return False
    tags = _tagset(n)
    if "entry" in tags:
        return True
    if tags & _PIVOT_TARGET_TAGS:
        return False
    return True


def _blob(n: dict | None) -> str:
    n = n or {}
    return f"{n.get('key') or ''} {n.get('title') or ''} {n.get('detail') or ''}"


def _confirmed_shell(n: dict | None) -> bool:
    n = n or {}
    ntype = str(n.get("type") or "")
    key = str(n.get("key") or "")
    tags = _tagset(n)
    if ntype == "goal" and (
        n.get("is_rce") or key.startswith("goal:shell") or "getshell" in tags
    ):
        return True
    if ntype == "foothold":
        return bool(n.get("is_rce") or "getshell" in tags)
    return False


def _looks_like_tunnel(blob: str, tags: set[str]) -> bool:
    hay = f"{blob} {' '.join(tags)}".lower()
    return any(m in hay for m in _TUNNEL_MARKERS)


def precondition_kinds(graph: dict | None) -> frozenset[str]:
    """图上已验证的可达前置条件种类。"""
    kinds: set[str] = set()
    if not graph:
        return frozenset()
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if _confirmed_shell(n):
            kinds.add(KIND_SHELL)
        tags = _tagset(n)
        blob = _blob(n)
        if _looks_like_tunnel(blob, tags):
            kinds.add(KIND_TUNNEL)
    try:
        from ..graph.hypothesize import live_gadget_tactics
        if live_gadget_tactics(graph):
            kinds.add(KIND_SSRF)
    except Exception:
        pass
    for f in graph.get("findings") or []:
        if not isinstance(f, dict):
            continue
        vs = str(f.get("verification_status") or "").lower()
        if vs in ("disproved", "false", "rejected"):
            continue
        cat = str(f.get("category") or "").lower()
        blob = f"{f.get('title') or ''} {f.get('description') or ''} {cat}"
        if cat in ("ssrf", "ssrf_internal") or "ssrf" in blob.lower():
            if vs in ("verified", "confirmed", "") or vs not in ("disproved",):
                kinds.add(KIND_SSRF)
        if _looks_like_tunnel(blob, set()):
            kinds.add(KIND_TUNNEL)
    for n in graph.get("nodes") or []:
        key = str((n or {}).get("key") or "")
        tags = _tagset(n)
        blob = _blob(n).lower()
        if not (
            key.startswith("info:scope-expanded:")
            or (
                key.startswith("target:")
                and ("ssrf" in tags or "scope-expanded" in tags or "ssrf" in blob)
            )
        ):
            continue
        if any(m in blob for m in SSRF_MECHANISMS) or "ssrf" in blob or "ssrf" in tags:
            kinds.add(KIND_SSRF)
        if _looks_like_tunnel(blob, tags):
            kinds.add(KIND_TUNNEL)
        if "shell_reachable" in blob or "shell" in tags:
            kinds.add(KIND_SHELL)
    return frozenset(kinds)


def has_verified_precondition(graph: dict | None) -> bool:
    return bool(precondition_kinds(graph))


def infer_pivot_mechanism(kinds: frozenset[str] | set[str] | None) -> str:
    ks = set(kinds or ())
    if KIND_SSRF in ks:
        return "ssrf_direct"
    if KIND_TUNNEL in ks:
        return "port_forward"
    return "shell_reachable"


def _host_from_node_key(key: str) -> str:
    kid = str(key or "")
    for p in ("info:scope-expanded:", "info:host:", "target:"):
        if kid.startswith(p):
            return _norm_host(kid[len(p):].split(":")[0])
    return ""


def via_capability_hosts(graph: dict | None, scope: Scope | None = None) -> set[str]:
    """经已验证能力看见、因而属于本题目标内网的主机。不含入口。"""
    out: set[str] = set()
    if not graph:
        return out
    entry: set[str] = set()
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        key = str(n.get("key") or "")
        ntype = str(n.get("type") or "")
        h = _host_from_node_key(key)
        if node_is_entry_target(n):
            if h:
                entry.add(h)
            continue
        tags = _tagset(n)
        via = (
            key.startswith("info:scope-expanded:")
            or (ntype == "target" and bool(tags & _PIVOT_TARGET_TAGS))
            or bool(tags & _VIA_TAGS)
            or any(str(t).startswith("host:") and "ssrf" in tags for t in tags)
        )
        if not via:
            continue
        if h and is_private_ip(h) and not is_loopback(h) and not is_ssrf_canary_host(h):
            out.add(h)
        for t in tags:
            if str(t).startswith("host:"):
                hh = _norm_host(str(t)[5:])
                if hh and is_private_ip(hh) and not is_loopback(hh) and not is_ssrf_canary_host(hh):
                    out.add(hh)
    out -= entry
    if scope is not None:
        for raw in list(scope.ips or []):
            h = _norm_host(str(raw))
            if not h or h in entry or not is_private_ip(h) or is_loopback(h):
                continue
            if is_ssrf_canary_host(h):
                continue
            if h in out or same_pivot_lan(h, scope):
                out.add(h)
    return out


def entry_hosts(scope: Scope | None, *, primary: str = "", own_hosts: set[str] | None = None) -> set[str]:
    out: set[str] = set()
    if primary:
        out.add(_norm_host(str(primary).split(":")[0]))
    for x in own_hosts or ():
        h = _norm_host(str(x).split(":")[0])
        if h:
            out.add(h)
    if scope is not None:
        for t in scope.targets or []:
            h = _norm_host(str(t).split(":")[0])
            if h:
                out.add(h)
    return {h for h in out if h}


def is_entry_identity(
    host: str,
    *,
    primary: str = "",
    own_hosts: set[str] | None = None,
    scope: Scope | None = None,
) -> bool:
    h = _norm_host(host)
    if not h:
        return False
    return h in entry_hosts(scope, primary=primary, own_hosts=own_hosts)


def kali_direct_intranet_reason(
    host: str,
    *,
    primary: str = "",
    own_hosts: set[str] | None = None,
    scope: Scope | None = None,
    has_precondition: bool = False,
    via_hosts: set[str] | None = None,
) -> str | None:
    """Kali 网卡直连该主机时的拦截原因。入口身份放行。"""
    h = _norm_host(host)
    if not h or not is_private(h) or is_loopback(h):
        return None
    if is_entry_identity(h, primary=primary, own_hosts=own_hosts, scope=scope):
        return None
    via = {_norm_host(x) for x in (via_hosts or ()) if x}
    in_scope = False
    if scope is not None:
        try:
            in_scope = bool(scope.host_in_scope(h))
        except Exception:
            in_scope = False
        if not in_scope and same_pivot_lan(h, scope):
            in_scope = True
    seen = h in via or in_scope
    if not has_precondition:
        return NO_PRECONDITION_MSG
    if not seen:
        return NOT_SEEN_VIA_CAPABILITY_MSG
    return MUST_VIA_CAPABILITY_MSG


def private_hosts_from_text(text: str, *, limit: int = 8) -> list[str]:
    """从正文抽出 RFC1918 主机。不含回环与网段标识。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _IPV4_RE.findall(text or ""):
        h = _norm_host(raw)
        if not h or h in seen or h.endswith(".0") or h.endswith(".255"):
            continue
        if not _IP_RE.match(h) or not is_private_ip(h) or is_loopback(h):
            continue
        seen.add(h)
        out.append(h)
        if len(out) >= max(1, int(limit or 8)):
            break
    return out


def should_absorb_from_command(command: str) -> bool:
    """扫段/邻居侦察才从输出抽活面；hosts 文件走线索通道。"""
    return bool(_RECON_SCAN_RE.search(command or ""))


def is_hosts_file_command(command: str) -> bool:
    return bool(_HOSTS_FILE_CMD_RE.search(command or ""))


def is_broadcast_or_net(host: str) -> bool:
    h = _norm_host(host)
    return bool(h) and (h.endswith(".0") or h.endswith(".255"))


def node_host(node: dict | None) -> str:
    n = node or {}
    h = _host_from_node_key(str(n.get("key") or ""))
    if h:
        return h
    for t in n.get("tags") or []:
        ts = str(t)
        if ts.lower().startswith("host:"):
            hh = _norm_host(ts.split(":", 1)[-1])
            if hh:
                return hh
    return ""


def _hosts_from_node(n: dict | None) -> set[str]:
    out: set[str] = set()
    n = n or {}
    h = node_host(n)
    if h and is_private_ip(h) and not is_loopback(h) and not is_broadcast_or_net(h):
        out.add(h)
    blob = f"{_blob(n)} {n.get('tags') or ''}"
    out.update(private_hosts_from_text(blob, limit=16))
    for t in n.get("tags") or []:
        ts = str(t)
        if ts.lower().startswith("host:"):
            hh = _norm_host(ts.split(":", 1)[-1])
            if hh and is_private_ip(hh) and not is_loopback(hh) and not is_broadcast_or_net(hh):
                out.add(hh)
    return out


def live_surface_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        tags = _tagset(n)
        if TAG_LIVE in tags or "via-live" in tags:
            out.update(_hosts_from_node(n))
    return out


def clue_only_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    live = live_surface_hosts(graph)
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        tags = _tagset(n)
        if TAG_CLUE in tags and TAG_LIVE not in tags:
            out.update(_hosts_from_node(n) - live)
    return out


def all_service_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if str(n.get("type") or n.get("kind") or "") != "service":
            continue
        out.update(_hosts_from_node(n))
    return out


def identity_service_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if str(n.get("type") or n.get("kind") or "") != "service":
            continue
        blob = f"{_blob(n)} {' '.join(str(t) for t in (n.get('tags') or []))}"
        if _IDENTITY_RE.search(blob):
            out.update(_hosts_from_node(n))
    return out


def cred_named_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        ntype = str(n.get("type") or "")
        tags = _tagset(n)
        if ntype not in ("credential", "cred") and "credential" not in tags and "cred" not in tags:
            if not _IDENTITY_RE.search(_blob(n)):
                continue
            if ntype not in ("info", "credential"):
                continue
        out.update(_hosts_from_node(n))
    return out


def foothold_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    entry: set[str] = set()
    for n in (graph or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        key = str(n.get("key") or "")
        ntype = str(n.get("type") or "")
        if node_is_entry_target(n):
            h = _host_from_node_key(key)
            if h:
                entry.add(h)
            continue
        if ntype == "foothold" or _confirmed_shell(n):
            out.update(_hosts_from_node(n))
    return {h for h in out if h not in entry}


def unauth_loot_hosts(graph: dict | None) -> set[str]:
    out: set[str] = set()
    nodes_by_key = {
        str(n.get("key") or ""): n
        for n in (graph or {}).get("nodes") or []
        if isinstance(n, dict)
    }
    for f in (graph or {}).get("findings") or []:
        if not isinstance(f, dict):
            continue
        vs = str(f.get("verification_status") or "").lower()
        if vs in ("disproved", "false", "rejected", "pending"):
            continue
        cat = str(f.get("category") or "").lower()
        blob = f"{f.get('title') or ''} {f.get('description') or ''} {cat}"
        if cat not in _UNAUTH_LOOT_CATS and not re.search(
            r"文件读|任意文件|信息泄露|directory traversal|local file", blob, re.I,
        ):
            continue
        if vs not in ("verified", "confirmed", ""):
            continue
        nk = str(f.get("node_key") or "")
        if nk and nk in nodes_by_key:
            out.update(_hosts_from_node(nodes_by_key[nk]))
        out.update(private_hosts_from_text(blob, limit=8))
    return out


def verified_hop_auth_hosts(graph: dict | None, intents: list[dict] | None = None) -> set[str]:
    out: set[str] = set()
    rows = list(intents or [])
    if not rows:
        rows = list((graph or {}).get("intents") or [])
    for it in rows:
        if not isinstance(it, dict):
            continue
        sk = str(it.get("strategy_key") or "")
        if not sk.endswith("hop_auth") and "::hop_auth" not in sk:
            continue
        if str(it.get("status") or "") != "verified":
            continue
        blob = (
            f"{it.get('from_keys') or ''} {it.get('description') or ''} "
            f"{it.get('strategy_key') or ''} {it.get('rationale') or ''}"
        )
        out.update(private_hosts_from_text(blob, limit=8))
    return out


def hop_auth_eligible(node: dict | None, graph: dict | None = None) -> bool:
    """是否给该内网节点派 hop_auth。空号/广播/已落地 foothold 不派。"""
    n = node or {}
    h = node_host(n)
    if h and (is_broadcast_or_net(h) or is_ssrf_canary_host(h)):
        return False
    if graph and h and h in foothold_hosts(graph):
        return False
    tags = _tagset(n)
    if TAG_LIVE in tags:
        return True
    blob = f"{_blob(n)} {' '.join(sorted(tags))}"
    if _IDENTITY_RE.search(blob):
        return True
    if graph and h:
        if h in identity_service_hosts(graph) or h in cred_named_hosts(graph):
            return True
        if h in live_surface_hosts(graph):
            return True
    return False


def node_is_live_intranet(node: dict | None) -> bool:
    """活面邻机：可派未授权差分。线索/空号不算。"""
    n = node or {}
    tags = _tagset(n)
    if TAG_CLUE in tags and TAG_LIVE not in tags:
        return False
    h = node_host(n)
    if h and (is_broadcast_or_net(h) or is_ssrf_canary_host(h)):
        return False
    if TAG_LIVE in tags:
        return True
    key = str(n.get("key") or "")
    if key.startswith("info:scope-expanded:") and TAG_CLUE not in tags:
        return True
    if n.get("type") == "target" and (tags & {"lateral", "pivot", "scope-expanded", TAG_LIVE}):
        return True
    return False


_LIVE_BODY_RE = re.compile(
    r"<form|登录|login|ssh-2\.0|\b220[\s-]|"
    r"username|password|set-cookie|www-authenticate",
    re.I,
)
_DEAD_BODY_RE = re.compile(
    r"connection timed out|no route to host|"
    r"empty reply|connection refused|timed?\s*out",
    re.I,
)
_ABSORB_STUB_EV = "via verified capability output"

# RFC 5737 / 3849：文档示例网段，不是可作业邻机。
_DOCUMENTATION_NETS = tuple(
    ipaddress.ip_network(n) for n in (
        "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32",
    )
)
# 云厂商实例元数据：链路本地已由 is_link_local 覆盖；这里只留非链路本地的公开 anycast。
_IMDS_ANYCAST = frozenset({"100.100.100.200"})
_IMDS_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata",
    "instance-data",
})
_NIP_REBIND = re.compile(r"(?:^|\.)(?:nip\.io|sslip\.io)$", re.I)

SSRF_NEIGHBOR_RULE = (
    "只有从目标响应里看见、或经 SSRF 拿到登录页/横幅/业务正文的具体内网主机才扩 Scope。"
    "链路本地与云元数据、文档网段、以及超时/无业务正文的错误码差分只证明 SSRF 原语，"
    "不要当成新邻机、不要 hop_auth。"
)


def looks_like_live_observation(output: str) -> bool:
    """跳板回包是否像活着的业务面（登录页/横幅/足够长的正文）。"""
    text = (output or "").strip()
    if len(text) < 40:
        return False
    if _LIVE_BODY_RE.search(text):
        return True
    if _DEAD_BODY_RE.search(text):
        return False
    return len(text) >= 400


def is_ssrf_canary_host(host: str) -> bool:
    """链路本地 / 文档网段 / 云元数据：SSRF 探测面，不是新邻机。

    不按 RFC1918 常见网关或某次狩猎用过的探测 IP 拉黑：10.0.0.1、192.168.1.1
    可以是真邻机；没有登录页/横幅时由 oracle 规则拒绝扩 Scope。
    """
    h = _norm_host(host)
    if not h:
        return False
    if is_loopback(h) or h in ("localhost", "0.0.0.0", "host.docker.internal"):
        return True
    if h in _IMDS_HOSTS:
        return True
    if "metadata" in h and (h.endswith(".internal") or "google" in h):
        return True
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return True
        if str(ip) in _IMDS_ANYCAST:
            return True
        if any(ip in net for net in _DOCUMENTATION_NETS):
            return True
    except ValueError:
        pass
    if _NIP_REBIND.search(h):
        dotted = h.replace("-", ".")
        for m in _IPV4_RE.finditer(dotted):
            inner = m.group(1)
            if inner and inner != h and is_ssrf_canary_host(inner):
                return True
    return False


def ssrf_evidence_is_oracle_only(evidence: str) -> bool:
    """没有登录页/横幅/足够业务正文：只证明 SSRF 原语，不是看见了邻机。"""
    text = (evidence or "").strip()
    if not text or text == _ABSORB_STUB_EV:
        return True
    return not looks_like_live_observation(text)


def live_hosts_from_recon_output(output: str, *, limit: int = 8) -> list[str]:
    """侦察输出里只收同一行带开放/协议/登录/横幅标记的主机。"""
    found: list[str] = []
    seen: set[str] = set()
    for line in (output or "").splitlines():
        if not _LIVE_LINE_RE.search(line):
            continue
        for h in private_hosts_from_text(line, limit=4):
            if h not in seen:
                seen.add(h)
                found.append(h)
            if len(found) >= max(1, int(limit or 8)):
                return found
    return found


def hosts_from_capability_observation(
    *,
    url: str = "",
    data: str = "",
    command: str = "",
    output: str = "",
) -> list[str]:
    """只吸收「这一跳真正打出业务面」的邻机，不把扫段空号写进 Scope。"""
    found: list[str] = []
    seen: set[str] = set()

    def _add(hosts: list[str]) -> None:
        for h in hosts:
            if not h or h in seen or is_ssrf_canary_host(h):
                continue
            seen.add(h)
            found.append(h)

    if is_hosts_file_command(command):
        return []
    live = looks_like_live_observation(output)
    if data:
        dh = private_hosts_from_text(data, limit=4)
        if live and 1 <= len(dh) <= 2:
            _add(dh)
    url_hosts = private_hosts_from_text(url, limit=4)
    if live and 1 <= len(url_hosts) <= 2:
        _add(url_hosts)
    cmd_hosts = private_hosts_from_text(command, limit=16)
    if live and 1 <= len(cmd_hosts) <= 2:
        _add(cmd_hosts)
    elif command and should_absorb_from_command(command) and output:
        _add(live_hosts_from_recon_output(output))
    return found[:8]


def clue_hosts_from_observation(
    *,
    command: str = "",
    output: str = "",
) -> list[str]:
    """hosts 文件等线索地址：落 info，不扩 Scope、不当活面。"""
    if not is_hosts_file_command(command) or not output:
        return []
    return [h for h in private_hosts_from_text(output, limit=8) if not is_ssrf_canary_host(h)]


def node_is_capability_intranet(node: dict | None) -> bool:
    """该节点是否已经是经跳板登记的内网主机。"""
    n = node or {}
    key = str(n.get("key") or "")
    tags = _tagset(n)
    if TAG_CLUE in tags and TAG_LIVE not in tags:
        return False
    if key.startswith("info:scope-expanded:"):
        return True
    if TAG_LIVE in tags:
        return True
    if n.get("type") == "target" and (tags & {"lateral", "pivot", "scope-expanded", TAG_LIVE}):
        return True
    if key.startswith("info:host:") and (tags & (_VIA_TAGS | {"lateral", "internal"})):
        return True
    return False


def junk_hop_auth_host(host: str, graph: dict | None) -> bool:
    """广播/网段标识/SSRF 探测地址不是邻机身份门。"""
    _ = graph
    return is_broadcast_or_net(host) or is_ssrf_canary_host(host)


def intent_private_hosts(intent: dict | None) -> list[str]:
    it = intent or {}
    blob = (
        f"{it.get('from_keys') or ''} {it.get('description') or ''} "
        f"{it.get('strategy_key') or ''} {it.get('rationale') or ''}"
    )
    return private_hosts_from_text(blob, limit=8)


def apply_gate_to_guard(
    guard: Any, graph: dict | None, *, brief: str = "", supplied_auth: Any = None,
) -> None:
    """把图上的前置条件刷进 Guard，供 check_command 使用。"""
    if guard is None:
        return
    kinds = precondition_kinds(graph)
    guard.has_intranet_precondition = bool(kinds)
    guard.via_capability_hosts = via_capability_hosts(graph, getattr(guard, "scope", None))
    try:
        from ..agents.brief_creds import (
            credential_candidates_from_brief,
            graph_cred_blob,
            password_values,
            secrets_from_supplied_auth,
        )
        blob = f"{brief or ''}\n{graph_cred_blob(graph)}"
        secrets = password_values(credential_candidates_from_brief(blob))
        secrets |= secrets_from_supplied_auth(supplied_auth)
        guard.allowed_secrets = secrets
    except Exception:
        guard.allowed_secrets = set(getattr(guard, "allowed_secrets", None) or ())
