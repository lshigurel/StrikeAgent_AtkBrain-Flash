"""设置里的一个出站 webhook。失败可重发，失败不回滚漏洞入库。"""
from __future__ import annotations

import json
from typing import Any

from .db import db, new_id, now
from .proxy.pool import _merge_settings, _settings_path

KEY_URL = "webhook_url"
KEY_SEV = "webhook_severities"
KEY_PROJECTS = "webhook_projects"
KEY_ASSETS = "webhook_assets"


def _read() -> dict:
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def get_webhook() -> dict[str, Any]:
    data = _read()
    return {
        "url": str(data.get(KEY_URL) or "").strip(),
        "severities": _as_list(data.get(KEY_SEV)),
        "projects": _as_list(data.get(KEY_PROJECTS)),
        "assets": _as_list(data.get(KEY_ASSETS)),
    }


def set_webhook(*, url: str | None = None, severities=None, projects=None, assets=None) -> dict:
    updates: dict[str, Any] = {}
    if url is not None:
        updates[KEY_URL] = str(url or "").strip()
    if severities is not None:
        updates[KEY_SEV] = _as_list(severities)
    if projects is not None:
        updates[KEY_PROJECTS] = _as_list(projects)
    if assets is not None:
        updates[KEY_ASSETS] = _as_list(assets)
    if updates:
        _merge_settings(updates)
    return get_webhook()


def _wanted(finding: dict, cfg: dict) -> bool:
    sev = _as_list(cfg.get("severities"))
    if sev and str(finding.get("severity") or "").lower() not in {s.lower() for s in sev}:
        return False
    projects = _as_list(cfg.get("projects"))
    if projects and str(finding.get("project_id") or "") not in projects:
        return False
    assets = {s.lower() for s in _as_list(cfg.get("assets"))}
    if assets:
        have = {str(x).lower() for x in (finding.get("assets") or [])}
        if not have.intersection(assets):
            return False
    return True


async def _asset_names(finding_id: str) -> list[str]:
    rows = await db.fetchall(
        """SELECT a.identity FROM assets a
           JOIN finding_assets fa ON fa.asset_id=a.id
           WHERE fa.finding_id=?""",
        (finding_id,),
    )
    return [str(r.get("identity") or "") for r in rows if r.get("identity")]


async def _post(url: str, payload: dict) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 300:
            raise RuntimeError(f"webhook {resp.status_code}")


async def enqueue_finding(project_id: str, finding: dict) -> None:
    """推送失败只留下可重发记录，不影响已经入库的漏洞。"""
    cfg = get_webhook()
    url = cfg.get("url") or ""
    if not url or not finding:
        return
    body = {
        "finding_id": finding.get("id"),
        "project_id": project_id,
        "title": finding.get("title"),
        "severity": finding.get("severity"),
        "category": finding.get("category"),
        "assets": await _asset_names(str(finding.get("id") or "")),
    }
    if not _wanted(body, cfg):
        return
    try:
        await _post(url, body)
    except Exception as exc:
        await db.execute(
            """INSERT INTO webhook_outbox(id, finding_id, payload, attempts, last_error, created_at)
               VALUES(?,?,?,?,?,?)""",
            (new_id("wh_"), finding.get("id"), json.dumps(body, ensure_ascii=False),
             1, str(exc)[:300], now()),
        )


async def retry_outbox(limit: int = 20) -> dict:
    cfg = get_webhook()
    url = cfg.get("url") or ""
    rows = await db.fetchall(
        """SELECT * FROM webhook_outbox WHERE sent_at IS NULL AND attempts < 8
           ORDER BY created_at ASC LIMIT ?""",
        (limit,),
    )
    sent = 0
    failed = 0
    for row in rows:
        if not url:
            failed += 1
            continue
        try:
            payload = json.loads(row.get("payload") or "{}")
        except Exception:
            payload = {}
        try:
            await _post(url, payload if isinstance(payload, dict) else {})
        except Exception as exc:
            failed += 1
            await db.execute(
                "UPDATE webhook_outbox SET attempts=attempts+1, last_error=? WHERE id=?",
                (str(exc)[:300], row["id"]),
            )
            continue
        sent += 1
        await db.execute(
            "UPDATE webhook_outbox SET sent_at=?, last_error=NULL WHERE id=?",
            (now(), row["id"]),
        )
    return {"sent": sent, "failed": failed}
