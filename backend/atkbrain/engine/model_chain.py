"""一条模型失败后切下一条。已经写进图里的意图保持原状态。"""
from __future__ import annotations

from ..db import db, now
from ..projects import get_project, update_config

_HINTS = (
    "model", "api key", "api_key", "rate limit", "overloaded", "credit",
    "401", "403", "429", "500", "502", "503", "invalid_request",
    "authentication", "insufficient", "quota",
)


def looks_like_model_failure(message: str) -> bool:
    text = (message or "").lower()
    return any(h in text for h in _HINTS)


async def advance_model_chain(project_id: str) -> str | None:
    proj = await get_project(project_id)
    if not proj:
        return None
    cfg = dict(proj.get("config") or {})
    chain = [str(x).strip() for x in (cfg.get("model_chain") or []) if str(x or "").strip()]
    if len(chain) < 2:
        return None
    try:
        index = int(cfg.get("model_chain_index") or 0)
    except (TypeError, ValueError):
        index = 0
    nxt = index + 1
    if nxt >= len(chain):
        return None
    cfg["model_chain_index"] = nxt
    cfg["model"] = chain[nxt]
    await update_config(project_id, cfg)
    await db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
    return chain[nxt]
