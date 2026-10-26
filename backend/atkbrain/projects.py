"""项目管理：单目标/集群项目的 CRUD、Scope 构建、目标解析。"""
from __future__ import annotations

import asyncio
import json
import re
import socket
from pathlib import Path

from .db import db, new_id, now, _dumps, _loads
from .objective import AGENT, FLAG, normalize_objective, objective_allows_flag
from .scope import Scope, forbidden_project_target_reason, is_loopback, is_private

_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _clean_target(raw: str) -> tuple[str, str | None]:
    """从输入里剥离协议/端口，返回 (host, port_or_None)。"""
    t = raw.strip()
    t = re.sub(r"^\w+://", "", t)          # 去协议
    t = t.split("/")[0]                     # 去路径
    port = None
    if t.count(":") == 1:                   # host:port（忽略 IPv6 简化处理）
        host, p = t.split(":")
        if p.isdigit():
            t, port = host, p
    return t.strip().lower(), port


def assert_safe_project_target(target: str) -> str:
    """校验项目主目标，不安全则抛 ValueError；返回规范化 host。"""
    host, _ = _clean_target(target or "")
    reason = forbidden_project_target_reason(host)
    if reason:
        raise ValueError(reason)
    return host


async def ensure_project_target_safe(pid: str) -> dict:
    """启动前校验：项目存在且 target 非本机/回环/Fake-IP。返回项目 dict。"""
    p = await get_project(pid)
    if not p:
        raise ValueError("项目不存在")
    tgt = (p.get("target") or "").strip()
    if tgt:
        assert_safe_project_target(tgt)
    return p


async def _resolve(host: str) -> set[str]:
    if _IP_RE.match(host):
        return {host}
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        return {i[4][0] for i in infos if _IP_RE.match(i[4][0])}
    except Exception:
        return set()


def _filter_scope_ips(host: str, ips: set[str], objective: str | None) -> tuple[set[str], str | None]:
    """创建期 DNS 去漂移：域名解析结果剔除回环；红队额外剔除私网。显式 IP 目标原样保留。"""
    if _IP_RE.match(host):
        return set(ips), None
    external = not objective_allows_flag(objective)
    kept: set[str] = set()
    for ip in ips:
        if is_loopback(ip):
            continue
        if external and is_private(ip):
            continue
        kept.add(ip)
    warning = None
    if ips and not kept:
        warning = (f"授权域名 {host} 仅解析到回环/内网（{sorted(ips)}），"
                   f"已不写入 scope.ips。")
    return kept, warning


async def create_offline_ctf_project(name: str, config: dict | None = None) -> dict:
    """没有远程入口的 CTF：只分析附件和附加信息。"""
    cfg = dict(config or {})
    cfg["offline"] = True
    cfg["track"] = "ctf"
    cfg["objective"] = FLAG
    pid = new_id("p_")
    ts = now()
    scope = Scope(targets=[], ips=[], ports=None, allow_subdomains=False, mode="strict")
    await db.execute(
        """INSERT INTO projects(id, name, kind, target, ports, scope, config, status, parent_id, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, (name or "").strip() or "本地题目", "single", "", _dumps(None), _dumps(scope.to_dict()),
         _dumps(cfg), "idle", None, ts, ts),
    )
    return await get_project(pid)


async def create_single_project(
    name: str,
    target: str,
    ports: list[int] | None = None,
    *,
    allow_subdomains: bool = False,
    mode: str = "strict",
    config: dict | None = None,
    parent_id: str | None = None,
    extra_targets: list[str] | None = None,
    extra_ips: set[str] | None = None,
) -> dict:
    host, inline_port = _clean_target(target)
    assert_safe_project_target(host)
    if inline_port and not ports:
        ports = [int(inline_port)]
    extra: list[str] = []
    seen_t = {host}
    for raw in extra_targets or []:
        h, _p = _clean_target(str(raw or ""))
        if not h or h in seen_t:
            continue
        assert_safe_project_target(h)
        seen_t.add(h)
        extra.append(h)
    all_targets = [host, *extra]
    cfg = dict(config or {})
    ips_raw = await _resolve(host)
    for h in extra:
        ips_raw |= await _resolve(h)
    if extra_ips:
        ips_raw |= {str(x) for x in extra_ips if x}
    ips, dns_warning = _filter_scope_ips(host, ips_raw, cfg.get("objective"))
    if dns_warning:
        cfg["dns_warning"] = dns_warning
    kept_extra = {str(x) for x in (extra_ips or set()) if x}
    ips = set(ips) | kept_extra
    hit_loop = sorted(ip for ip in ips if is_loopback(ip))
    if hit_loop and not _IP_RE.match(host):
        raise ValueError(f"目标 {host} 解析到回环地址（{hit_loop}），禁止创建项目")
    cfg["vhosts"] = list(all_targets)
    # 边界按主机身份（域名/IP）；ports 只记在 projects.ports 供展示/探测，不写入 Scope 收紧端口
    scope = Scope(
        targets=all_targets, ips=ips, ports=None, allow_subdomains=allow_subdomains, mode=mode,
    )
    pid = new_id("p_")
    ts = now()
    await db.execute(
        """INSERT INTO projects(id, name, kind, target, ports, scope, config, status, parent_id, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, name or host, "single", host, _dumps(ports), _dumps(scope.to_dict()),
         _dumps(cfg), "idle", parent_id, ts, ts),
    )
    from .assets import seed_declared
    await seed_declared(
        pid, all_targets, list(ips),
        vendor_name=(cfg.get("vendor") or host),
    )
    return await get_project(pid)


def _audit_cluster_rejections(name: str, rejected: list[tuple[str, str]]) -> None:
    """把被拒绝的集群资产按 JSONL 追加到本地审计日志。"""
    if not rejected:
        return
    path = Path(__file__).resolve().parents[1] / "data" / "logs" / "cluster-rejections.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = now()
    with path.open("a", encoding="utf-8") as fh:
        for asset, reason in rejected:
            host, _ = _clean_target(asset)
            rec = {"ts": ts, "project": name, "asset": asset, "host": host, "reason": reason}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _format_cluster_rejection(rejected: list[tuple[str, str]]) -> str:
    details = "；".join(f"{asset} -> {reason}" for asset, reason in rejected[:5])
    more = f"；另有 {len(rejected) - 5} 条" if len(rejected) > 5 else ""
    return f"集群资产全部被拒绝：{details}{more}"


async def create_cluster_project(name: str, assets: list[str], config: dict | None = None) -> dict:
    """集群项目（Phase 2 深化）：先建父项目并登记资产列表，存活快筛与子项目划分后续进行。"""
    from .cluster import compact_assets_by_host, parse_asset_lines, _normalize_asset
    cleaned: list[str] = []
    rejected: list[tuple[str, str]] = []
    for raw in parse_asset_lines(assets):
        try:
            assert_safe_project_target(raw)
        except ValueError as exc:
            rejected.append((raw, str(exc)))
            continue
        cleaned.append(raw)
    cleaned, _duped = compact_assets_by_host(cleaned)
    if rejected:
        try:
            await asyncio.to_thread(_audit_cluster_rejections, name, rejected)
        except OSError as exc:
            print(f"[cluster-audit] 写审计日志失败：{exc}", flush=True)
    if not cleaned:
        if not rejected:
            raise ValueError("集群资产为空或没有可用资产")
        raise ValueError(_format_cluster_rejection(rejected))
    pid = new_id("p_")
    ts = now()
    hosts: list[str] = []
    seen: set[str] = set()
    for a in cleaned:
        info = _normalize_asset(a)
        h = str(info.get("host") or "").strip().lower().rstrip(".")
        if h and h not in seen:
            seen.add(h)
            hosts.append(h)
    scope = Scope(targets=hosts or [a.lower() for a in cleaned], mode="strict")
    cfg = {**(config or {}), "assets": cleaned}
    if rejected:
        cfg["assets_rejected"] = [asset for asset, _reason in rejected]
        cfg["assets_rejected_detail"] = [
            {"asset": asset, "reason": reason} for asset, reason in rejected
        ]
    await db.execute(
        """INSERT INTO projects(id, name, kind, target, ports, scope, config, status, parent_id, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, name, "cluster", None, None, _dumps(scope.to_dict()),
         _dumps(cfg), "idle", None, ts, ts),
    )
    from .assets import seed_declared
    await seed_declared(pid, hosts, vendor_name=(cfg.get("vendor") or name))
    return await get_project(pid)


async def create_benchmark_project(
    name: str, base_url: str, token: str, config: dict | None = None
) -> dict:
    """评测父项目。incoming 为 src 时只叠胶水：复用拉题/起容器，不夺旗。"""
    pid = new_id("p_")
    ts = now()
    scope = Scope(targets=[], mode="strict")
    incoming = dict(config or {})
    raw_obj = str(incoming.get("objective") or incoming.get("track") or "").strip()
    is_agent = bool(raw_obj) and normalize_objective(raw_obj) == AGENT
    cfg = {
        **incoming,
        "objective": "agent" if is_agent else "flag",
        "track": "agent" if is_agent else incoming.get("track") or "ctf",
        "benchmark": {"base_url": (base_url or "").rstrip("/"), "token": token or ""},
        "autopilot": False if is_agent else (
            True if incoming.get("autopilot") is None else bool(incoming.get("autopilot"))
        ),
    }
    await db.execute(
        """INSERT INTO projects(id, name, kind, target, ports, scope, config, status, parent_id, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, name or "benchmark", "benchmark", None, None, _dumps(scope.to_dict()),
         _dumps(cfg), "idle", None, ts, ts),
    )
    return await get_project(pid)


def _backfill_track(kind: str, cfg: dict) -> dict:
    """序列化时只露出 agent 或 ctf。旧的 redteam / src 都写成 agent。"""
    explicit = str(cfg.get("track") or cfg.get("objective") or "").strip().lower()
    if kind == "benchmark" and not explicit:
        return {**cfg, "track": "ctf", "objective": "flag"}
    if normalize_objective(explicit or cfg.get("objective")) == FLAG:
        return {**cfg, "track": "ctf", "objective": "flag"}
    return {**cfg, "track": "agent", "objective": "agent"}


def project_track(kind: str | None, config: dict | None = None) -> str:
    """项目赛道：agent | ctf。"""
    cfg = _backfill_track(kind or "single", dict(config or {}))
    return "ctf" if str(cfg.get("track") or "") == "ctf" else "agent"


def _serialize(row: dict) -> dict:
    kind = row["kind"]
    cfg = _loads(row["config"]) or {}
    cfg = _backfill_track(kind, cfg)
    from .project_status import hunt_hard_stop_info
    obj = (cfg or {}).get("objective") or (cfg or {}).get("track")
    return {
        "id": row["id"], "name": row["name"], "kind": kind, "target": row["target"],
        "ports": _loads(row["ports"]), "scope": _loads(row["scope"]) or {},
        "config": cfg, "status": row["status"],
        "parent_id": row["parent_id"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "hard_stop": hunt_hard_stop_info(obj),
        "category": row.get("category"),
        "archived": int(row.get("archived") or 0),
        "queued_at": row.get("queued_at"),
        "vendor_id": row.get("vendor_id"),
    }


async def get_project(pid: str) -> dict | None:
    row = await db.fetchone("SELECT * FROM projects WHERE id=?", (pid,))
    return _serialize(row) if row else None


async def list_projects() -> list[dict]:
    # 只返回顶层项目：子项目（集群每主机）通过其父项目的面板进入。
    rows = await db.fetchall("SELECT * FROM projects WHERE parent_id IS NULL ORDER BY created_at DESC")
    return [_serialize(r) for r in rows]


async def update_status(pid: str, status: str) -> None:
    ts = now()
    if status == "queued":
        await db.execute(
            """UPDATE projects SET status=?, updated_at=?,
                   queued_at=COALESCE(queued_at, ?)
               WHERE id=?""",
            (status, ts, ts, pid),
        )
        return
    await db.execute(
        "UPDATE projects SET status=?, updated_at=?, queued_at=NULL WHERE id=?",
        (status, ts, pid),
    )


def _row_config(row: dict) -> dict:
    cfg = _loads(row.get("config")) or {}
    return cfg if isinstance(cfg, dict) else {}


async def unstick_transient_resource_errors() -> int:
    """把 FD/SQLite 资源抖动误标成 error 的项目改回 idle，使其可再次调度。"""
    from .project_status import HUNT_FAILED_REASONS

    rows = await db.fetchall(
        """SELECT id, config FROM projects WHERE status='error' AND id IN (
             SELECT DISTINCT project_id FROM events
             WHERE type='log' AND (
               payload LIKE '%unable to open database%'
               OR payload LIKE '%Too many open files%'
               OR payload LIKE '%[Errno 24]%'
             )
           )"""
    )
    ids = [
        r["id"] for r in (rows or [])
        if _row_config(r).get("completion_reason") not in HUNT_FAILED_REASONS
    ]
    if not ids:
        return 0
    q = ",".join("?" * len(ids))
    await db.execute(
        f"UPDATE projects SET status='idle', updated_at=? WHERE status='error' AND id IN ({q})",
        (now(), *ids),
    )
    return len(ids)


async def reclassify_hunt_failures() -> int:
    """图空转 / 时长硬停的存量项目从 idle/completed/stopped 改到 error（失败区）。"""
    from .project_status import HUNT_FAILED_REASONS

    rows = await db.fetchall(
        "SELECT id, config FROM projects WHERE status IN ('idle','completed','stopped')"
    )
    ids = [
        r["id"] for r in (rows or [])
        if _row_config(r).get("completion_reason") in HUNT_FAILED_REASONS
    ]
    if not ids:
        return 0
    q = ",".join("?" * len(ids))
    await db.execute(
        f"UPDATE projects SET status='error', updated_at=? WHERE id IN ({q})",
        (now(), *ids),
    )
    return len(ids)


async def update_config(pid: str, config: dict) -> None:
    await db.execute("UPDATE projects SET config=?, updated_at=? WHERE id=?", (_dumps(config), now(), pid))


async def rename_project(pid: str, name: str) -> dict:
    """修改项目显示名。集群会同步改写「旧名 · host」形式的子项目名前缀。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    if len(name) > 80:
        raise ValueError("名称过长（最多 80 字）")
    row = await db.fetchone("SELECT * FROM projects WHERE id=?", (pid,))
    if not row:
        raise ValueError("项目不存在")
    old = (row["name"] or "").strip()
    ts = now()
    await db.execute("UPDATE projects SET name=?, updated_at=? WHERE id=?", (name, ts, pid))
    renamed_children = 0
    if row["kind"] in ("cluster", "benchmark") and old and old != name:
        prefix = f"{old} · "
        children = await db.fetchall(
            "SELECT id, name FROM projects WHERE parent_id=?", (pid,),
        )
        for c in children:
            cname = c["name"] or ""
            if cname.startswith(prefix):
                new_c = name + " · " + cname[len(prefix):]
                await db.execute(
                    "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                    (new_c, ts, c["id"]),
                )
                renamed_children += 1
            elif cname == old:
                await db.execute(
                    "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                    (name, ts, c["id"]),
                )
                renamed_children += 1
    proj = await get_project(pid)
    assert proj is not None
    return {**proj, "renamed_children": renamed_children}


async def update_scope_and_config(pid: str, scope: dict, config: dict) -> None:
    """同步更新集群父项目的 scope + config（新增资产时用）。"""
    await db.execute(
        "UPDATE projects SET scope=?, config=?, updated_at=? WHERE id=?",
        (_dumps(scope), _dumps(config), now(), pid),
    )


# 随项目一并清掉的关联表。
_PROJECT_DATA_TABLES = (
    "nodes", "edges", "findings", "runs", "events", "steering", "intents", "flags",
)


async def _purge_project_rows(pid: str) -> None:
    await db.execute(
        "DELETE FROM finding_http WHERE finding_id IN (SELECT id FROM findings WHERE project_id=?)",
        (pid,),
    )
    await db.execute("DELETE FROM http_exchanges WHERE project_id=?", (pid,))
    await db.execute("DELETE FROM project_assets WHERE project_id=?", (pid,))
    for tbl in _PROJECT_DATA_TABLES:
        await db.execute(f"DELETE FROM {tbl} WHERE project_id=?", (pid,))
    await db.execute("DELETE FROM projects WHERE id=?", (pid,))


async def list_child_ids(pid: str) -> list[str]:
    rows = await db.fetchall("SELECT id FROM projects WHERE parent_id=?", (pid,))
    return [r["id"] for r in rows]


async def delete_project(pid: str) -> None:
    """删除项目及其全部子项目（图数据/事件/意图/flags）。

    不负责停跑——由 API 层在删除前对整棵子树调用 manager.stop。
    """
    for child_id in await list_child_ids(pid):
        await delete_project(child_id)
    await _purge_project_rows(pid)


async def delete_projects(ids: list[str]) -> dict:
    """批量删除：去重后逐个级联删除。返回 {deleted, missing}。

    停跑由调用方在删除前完成（API 层对整棵子树 stop）。
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in ids or []:
        pid = str(raw or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)

    deleted: list[str] = []
    missing: list[str] = []
    for pid in ordered:
        if not await get_project(pid):
            missing.append(pid)
            continue
        await delete_project(pid)
        deleted.append(pid)
    return {"deleted": deleted, "missing": missing}


def build_scope(project: dict) -> Scope:
    return Scope.from_dict(project.get("scope"))
