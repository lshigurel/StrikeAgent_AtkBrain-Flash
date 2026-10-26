"""单条意图的暂停、纠偏，以及单条命令确认。拒绝只回到这个工人。"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar

from ..db import db, new_id, now

# 本次工具调用来自哪个 Pi。二次验证要能重放，不能被猎洞写回后的意图闸挡住。
tool_caller_role: ContextVar[str] = ContextVar("tool_caller_role", default="")

_waiters: dict[str, asyncio.Event] = {}
_decisions: dict[str, tuple[bool, str]] = {}


def _intent_id(ctx) -> str:
    hop = str(getattr(ctx, "hop_auth_intent_id", "") or "").strip()
    if hop:
        return hop
    bound = getattr(ctx, "bound_must_intents", None) or ()
    ids = [str(x) for x in bound if str(x or "").strip()]
    return sorted(ids)[0] if ids else ""


def _review_may_recheck(role: str) -> bool:
    r = (role or "").strip().lower()
    return r == "finding-review" or r.startswith("finding-review:")


async def gate_intent(ctx) -> str | None:
    """工具执行前。返回文本则本步不执行，项目里的其它意图继续。"""
    if getattr(ctx, "intent_closed", False) and not _review_may_recheck(tool_caller_role.get()):
        return "本条意图已经写回，这次会话不再改打别的类型。"
    iid = _intent_id(ctx)
    if not iid:
        return None
    row = await db.fetchone(
        "SELECT paused, pending_steer FROM intents WHERE id=? AND project_id=?",
        (iid, getattr(ctx, "project_id", "")),
    )
    if not row:
        return None
    if int(row.get("paused") or 0):
        return "这条意图已暂停。其它意图继续。"
    steer = str(row.get("pending_steer") or "").strip()
    if steer:
        await db.execute(
            "UPDATE intents SET pending_steer=NULL, updated_at=? WHERE id=?",
            (now(), iid),
        )
        return "纠偏（先按这句调整，本步工具未执行）：" + steer
    return None


async def maybe_confirm_command(ctx, command: str, needs: bool) -> str | None:
    if not needs:
        return None
    cid = new_id("cmd_")
    iid = _intent_id(ctx)
    await db.execute(
        """INSERT INTO command_confirms(id, project_id, intent_id, command, status, created_at)
           VALUES(?,?,?,?,?,?)""",
        (cid, getattr(ctx, "project_id", ""), iid or None, command or "", "pending", now()),
    )
    ev = _waiters.get(cid)
    if ev is None:
        ev = asyncio.Event()
        _waiters[cid] = ev
    if cid in _decisions:
        ev.set()
    try:
        await asyncio.wait_for(ev.wait(), timeout=600)
    except asyncio.TimeoutError:
        await db.execute(
            "UPDATE command_confirms SET status=?, reason=?, decided_at=? WHERE id=?",
            ("timeout", "无人确认", now(), cid),
        )
        _waiters.pop(cid, None)
        return "无人确认，这条命令没有执行。"
    allow, reason = _decisions.pop(cid, (False, ""))
    _waiters.pop(cid, None)
    if allow:
        return None
    return reason or "这条命令被拒绝。"


def decide_command(confirm_id: str, *, allow: bool, reason: str = "") -> None:
    _decisions[confirm_id] = (bool(allow), (reason or "").strip())
    ev = _waiters.get(confirm_id)
    if ev is None:
        ev = asyncio.Event()
        _waiters[confirm_id] = ev
    ev.set()
