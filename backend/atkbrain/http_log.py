"""猎面 HTTP 留在库里，清空会话或工作区时不删。"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from .db import db, new_id, now

_CAP = 200_000
ROLES = {
    "对照": "对照",
    "证明": "证明",
    "复核": "复核",
    "辅助": "辅助",
    "baseline": "对照",
    "proof": "证明",
    "review": "复核",
    "aux": "辅助",
}


def _clip(value, limit: int = _CAP) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…[已截断]"


def _summary(body: str) -> str:
    flat = re.sub(r"\s+", " ", body or "").strip()
    return flat[:180]


def _url_key(url: str) -> str:
    raw = (url or "").strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        u = urlparse(raw)
    except Exception:
        return (url or "").strip()
    port = f":{u.port}" if u.port else ""
    path = u.path or "/"
    query = f"?{u.query}" if u.query else ""
    return f"{u.scheme}://{(u.hostname or '').lower()}{port}{path}{query}"


async def record_exchange(
    project_id: str,
    *,
    run_id: str | None,
    method: str,
    url: str,
    request_headers=None,
    request_body: str | None = None,
    status: int | None = None,
    response_headers=None,
    response_body: str | None = None,
) -> str:
    eid = new_id("hx_")
    headers = request_headers if isinstance(request_headers, str) else json.dumps(request_headers or {}, ensure_ascii=False)
    resp_headers = response_headers if isinstance(response_headers, str) else json.dumps(response_headers or {}, ensure_ascii=False)
    body = _clip(response_body or "")
    await db.execute(
        """INSERT INTO http_exchanges(
               id, project_id, run_id, method, url, request_headers, request_body,
               status, response_headers, response_body, response_summary, created_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, project_id, run_id, (method or "GET").upper(), url or "",
         _clip(headers, 8000), _clip(request_body or "", 80_000),
         int(status or 0), _clip(resp_headers, 8000), body, _summary(body), now()),
    )
    return eid


def _matches(row: dict, ref: dict) -> bool:
    method = str(ref.get("method") or "").upper()
    url = str(ref.get("url") or "")
    status = ref.get("status")
    summary = str(ref.get("summary") or ref.get("response_summary") or "").strip()
    if not method or not url or status is None or status == "":
        return False
    try:
        want_status = int(status)
    except (TypeError, ValueError):
        return False
    if method != str(row.get("method") or "").upper():
        return False
    if _url_key(url) != _url_key(str(row.get("url") or "")):
        return False
    if want_status != int(row.get("status") or 0):
        return False
    stored = str(row.get("response_summary") or "")
    if summary and stored and summary[:80] not in stored and stored[:80] not in summary:
        return False
    return True


async def bind_finding(finding_id: str, refs: list | None) -> dict:
    """按复现顺序绑定。方法、URL、状态码或摘要对不上就留空，不按域名或时间猜。"""
    bound: list[str] = []
    skipped = 0
    ordinal = 0
    for ref in refs or []:
        if not isinstance(ref, dict):
            skipped += 1
            continue
        role = ROLES.get(str(ref.get("role") or "").strip())
        eid = str(ref.get("id") or ref.get("exchange_id") or "").strip()
        if not role or not eid:
            skipped += 1
            continue
        row = await db.fetchone("SELECT * FROM http_exchanges WHERE id=?", (eid,))
        if not row or not _matches(row, ref):
            skipped += 1
            continue
        await db.execute(
            """INSERT INTO finding_http(finding_id, exchange_id, ordinal, role)
               VALUES(?,?,?,?)
               ON CONFLICT(finding_id, exchange_id) DO UPDATE SET ordinal=excluded.ordinal, role=excluded.role""",
            (finding_id, eid, ordinal, role),
        )
        ordinal += 1
        bound.append(eid)
    return {"bound": bound, "skipped": skipped}


async def bound_exchanges(finding_id: str) -> list[dict]:
    rows = await db.fetchall(
        """SELECT h.*, f.ordinal, f.role FROM finding_http f
           JOIN http_exchanges h ON h.id=f.exchange_id
           WHERE f.finding_id=?
           ORDER BY f.ordinal ASC""",
        (finding_id,),
    )
    return rows
