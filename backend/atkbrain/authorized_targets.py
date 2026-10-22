"""显式授权白名单。

只用于公开 SRC 项目中明确列入“可测资产范围”的主机。白名单文件位于
backend/data/authorized-domains.json，默认不存在即保持全部拦截。
支持精确主机和 ``*.example.com`` 子域通配；deny 优先于 allow。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

_ALLOWLIST_PATH = Path(__file__).resolve().parents[1] / "data" / "authorized-domains.json"
_AUDIT_PATH = Path(__file__).resolve().parents[1] / "data" / "logs" / "authorized-targets.jsonl"


def _norm_host(host: str) -> str:
    h = (host or "").strip().lower().rstrip(".")
    if h.count(":") == 1:
        name, port = h.split(":")
        if port.isdigit():
            h = name
    return h


def _match(pattern: str, host: str) -> bool:
    p = _norm_host(pattern)
    if not p:
        return False
    if p.startswith("*."):
        suffix = p[2:]
        return bool(suffix) and host.endswith("." + suffix)
    return host == p


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_allowlist() -> dict:
    try:
        st = _ALLOWLIST_PATH.stat()
    except FileNotFoundError:
        return {}
    try:
        return _load_cached(str(_ALLOWLIST_PATH), st.st_mtime_ns)
    except (OSError, ValueError):
        return {}


def authorized_match(host: str) -> dict | None:
    h = _norm_host(host)
    if not h:
        return None
    data = load_allowlist()
    deny = data.get("deny") or []
    if any(_match(pattern, h) for pattern in deny):
        return None
    for pattern in data.get("allow") or []:
        if _match(str(pattern), h):
            return {
                "host": h,
                "matched": str(pattern),
                "program": str(data.get("program") or ""),
                "url": str(data.get("url") or ""),
            }
    return None


def audit_authorized(entry: dict) -> None:
    """记录白名单放行，便于事后核对授权范围。"""
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
        with _AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        _AUDIT_PATH.chmod(0o600)
    except OSError:
        pass
