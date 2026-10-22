"""Web 控制台可管理的 Agent 注册表。

内置角色的提示词仍由 prompts.py 生成；本模块只保存可管理的覆盖项和自定义角色。
配置落在 backend/data/agents.json，属于运行时数据，不进 git。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..config import settings
from ..objective import normalize_objective
from .project_skills import validate_skill_selection

VERSION = 1
MAX_PROMPT = 60_000
MAX_DESCRIPTION = 800
MAX_MODEL = 200

TRACKS = ("redteam", "flag", "src")
TRACK_LABELS = {"redteam": "红队", "flag": "CTF", "src": "SRC"}

# 内置角色出现在哪些赛道。和 prompts.build_subagents 的生成逻辑保持一致。
BUILTIN_TRACKS: dict[str, tuple[str, ...]] = {
    "recon": TRACKS,
    "web-exploit": TRACKS,
    "protocol-model": TRACKS,
    "reverse": TRACKS,
    "rce-hunt": TRACKS,
    "privesc": ("redteam", "flag"),
    "lateral": ("redteam", "flag"),
    "src-hunt": ("src",),
    "flag-hunt": ("flag",),
}

# 这些角色被主提示词和御主规则当作必需角色，不允许从控制台停用。
CORE_BY_TRACK: dict[str, tuple[str, ...]] = {
    "redteam": ("recon", "web-exploit"),
    "flag": ("recon", "web-exploit"),
    "src": ("recon", "src-hunt"),
}
CORE_ROLES = frozenset({"recon", "web-exploit", "src-hunt"})

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_RESERVED = frozenset({
    "lead", "supervisor", "advisor", "commander", "finding-review",
    "review", "system", "worker",
})


def track_of(objective: str | None) -> str:
    return normalize_objective(objective)


def is_core(role: str, track: str | None = None) -> bool:
    if track:
        return role in CORE_BY_TRACK.get(track, ())
    return any(role in names for names in CORE_BY_TRACK.values())


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[:limit]
    return text


def _clean_tracks(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for raw in value or []:
        t = str(raw or "").strip().lower()
        if t == "ctf":
            t = "flag"
        if t in TRACKS and t not in out:
            out.append(t)
    return out


def _validate_id(agent_id: str) -> str:
    raw = str(agent_id or "").strip()
    if raw != raw.lower():
        raise ValueError("Agent ID 只能用小写字母、数字和短横线")
    if not _ID_RE.match(raw):
        raise ValueError("Agent ID 只能用小写字母、数字和短横线，2-32 位，且以字母开头")
    if raw in _RESERVED or raw in BUILTIN_TRACKS:
        raise ValueError("Agent ID 与内置/保留角色冲突")
    return raw


class AgentStore:
    """agents.json 的读写、缓存和运行时投影。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cached: dict[str, Any] | None = None
        self._stamp: tuple[int, int] | None = None

    # ---------- file io ----------

    def _empty(self) -> dict[str, Any]:
        return {"version": VERSION, "builtin": {}, "custom": []}

    def _load(self) -> dict[str, Any]:
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            return self._empty()
        with self._lock:
            if self._cached is not None and self._stamp == stamp:
                return self._cached
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            data = self._empty()
            if isinstance(raw, dict):
                if isinstance(raw.get("builtin"), dict):
                    data["builtin"] = {
                        str(k): v for k, v in raw["builtin"].items()
                        if isinstance(v, dict)
                    }
                if isinstance(raw.get("custom"), list):
                    data["custom"] = [v for v in raw["custom"] if isinstance(v, dict)]
            self._cached = data
            self._stamp = stamp
            return data

    def _save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + f".tmp-{os.getpid()}")
            payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.write_text(payload + "\n", encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
            self._cached = data
            try:
                st = self.path.stat()
                self._stamp = (st.st_mtime_ns, st.st_size)
            except OSError:
                self._stamp = None

    # ---------- builtin ----------

    def builtin_cfg(self, role: str) -> dict[str, Any]:
        data = self._load()
        raw = data["builtin"].get(role) or {}
        core = is_core(role)
        enabled = True if core else bool(raw.get("enabled", True))
        default = True if core else bool(raw.get("default", False))
        return {
            "enabled": enabled,
            "default": default,
            "model": _clean_text(raw.get("model"), MAX_MODEL),
            "skills": raw.get("skills"),
        }

    def update_builtin(self, role: str, **fields: Any) -> None:
        if role not in BUILTIN_TRACKS:
            raise ValueError("不是内置 Agent")
        core = is_core(role)
        with self._lock:
            data = self._load()
            cur = dict(data["builtin"].get(role) or {})
            if "enabled" in fields and fields["enabled"] is not None:
                if core and not bool(fields["enabled"]):
                    raise ValueError("核心 Agent 不能停用")
                cur["enabled"] = bool(fields["enabled"])
            if "default" in fields and fields["default"] is not None:
                if core and not bool(fields["default"]):
                    raise ValueError("核心 Agent 必须在默认并发中")
                cur["default"] = bool(fields["default"])
            if "model" in fields and fields["model"] is not None:
                cur["model"] = _clean_text(fields["model"], MAX_MODEL)
            if "skills" in fields:
                cur["skills"] = validate_skill_selection(fields["skills"])
            data["builtin"][role] = cur
            self._save(data)

    # ---------- custom ----------

    def custom(self, agent_id: str) -> dict[str, Any] | None:
        want = str(agent_id or "").strip().lower()
        for row in self._load()["custom"]:
            if str(row.get("id") or "").strip().lower() == want:
                return row
        return None

    def create_custom(
        self,
        *,
        agent_id: str,
        description: str,
        prompt: str,
        tracks: Any,
        enabled: bool = True,
        default: bool = False,
        model: str = "",
        skills: list[str] | None = None,
    ) -> dict[str, Any]:
        skills = validate_skill_selection(skills)
        aid = _validate_id(agent_id)
        desc = _clean_text(description, MAX_DESCRIPTION)
        body = _clean_text(prompt, MAX_PROMPT)
        ts = _clean_tracks(tracks)
        if not desc:
            raise ValueError("请填写 Agent 描述")
        if not body:
            raise ValueError("请填写 Agent 提示词")
        if not ts:
            raise ValueError("至少选择一个赛道")
        with self._lock:
            data = self._load()
            if any(str(r.get("id") or "").strip().lower() == aid for r in data["custom"]):
                raise ValueError("Agent ID 已存在")
            row = {
                "id": aid,
                "description": desc,
                "prompt": body,
                "tracks": ts,
                "enabled": bool(enabled),
                "default": bool(default),
                "model": _clean_text(model, MAX_MODEL),
                "skills": skills,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            data["custom"].append(row)
            self._save(data)
            return row

    def update_custom(self, agent_id: str, **fields: Any) -> dict[str, Any]:
        if "skills" in fields:
            fields["skills"] = validate_skill_selection(fields["skills"])
        want = str(agent_id or "").strip().lower()
        with self._lock:
            data = self._load()
            for row in data["custom"]:
                if str(row.get("id") or "").strip().lower() != want:
                    continue
                if "description" in fields and fields["description"] is not None:
                    desc = _clean_text(fields["description"], MAX_DESCRIPTION)
                    if not desc:
                        raise ValueError("请填写 Agent 描述")
                    row["description"] = desc
                if "prompt" in fields and fields["prompt"] is not None:
                    body = _clean_text(fields["prompt"], MAX_PROMPT)
                    if not body:
                        raise ValueError("请填写 Agent 提示词")
                    row["prompt"] = body
                if "tracks" in fields and fields["tracks"] is not None:
                    ts = _clean_tracks(fields["tracks"])
                    if not ts:
                        raise ValueError("至少选择一个赛道")
                    row["tracks"] = ts
                if "enabled" in fields and fields["enabled"] is not None:
                    row["enabled"] = bool(fields["enabled"])
                if "default" in fields and fields["default"] is not None:
                    row["default"] = bool(fields["default"])
                if "model" in fields and fields["model"] is not None:
                    row["model"] = _clean_text(fields["model"], MAX_MODEL)
                if "skills" in fields:
                    row["skills"] = fields["skills"]
                row["updated_at"] = time.time()
                self._save(data)
                return row
        raise ValueError("自定义 Agent 不存在")

    def delete_custom(self, agent_id: str) -> None:
        want = str(agent_id or "").strip().lower()
        with self._lock:
            data = self._load()
            keep = [r for r in data["custom"] if str(r.get("id") or "").strip().lower() != want]
            if len(keep) == len(data["custom"]):
                raise ValueError("自定义 Agent 不存在")
            data["custom"] = keep
            self._save(data)

    # ---------- projection ----------

    def snapshot(self) -> dict[str, Any]:
        data = self._load()
        builtin: list[dict[str, Any]] = []
        for role, tracks in BUILTIN_TRACKS.items():
            cfg = self.builtin_cfg(role)
            builtin.append({
                "id": role,
                "tracks": list(tracks),
                "core": list(tracks) if role in CORE_ROLES else [],
                **cfg,
            })
        custom = []
        for row in data["custom"]:
            custom.append({
                "id": row.get("id"),
                "description": row.get("description", ""),
                "prompt": row.get("prompt", ""),
                "tracks": _clean_tracks(row.get("tracks")),
                "enabled": bool(row.get("enabled", True)),
                "default": bool(row.get("default", False)),
                "model": _clean_text(row.get("model"), MAX_MODEL),
                "skills": row.get("skills"),
            })
        return {
            "builtin": builtin,
            "custom": custom,
            "limits": {
                "per_project": int(getattr(settings, "pi_per_project", 4) or 4),
                "max_live": int(getattr(settings, "pi_max_live", 32) or 32),
            },
        }

    def apply_to_agents(self, agents: dict[str, dict], objective: str | None) -> dict[str, dict]:
        track = track_of(objective)
        out: dict[str, dict] = {}
        for role, spec in agents.items():
            cfg = self.builtin_cfg(role)
            if not cfg["enabled"] and not is_core(role, track):
                continue
            item = dict(spec)
            item["skills"] = cfg["skills"]
            if cfg["model"]:
                item["model"] = cfg["model"]
            out[role] = item
        for row in self._load()["custom"]:
            if not bool(row.get("enabled", True)):
                continue
            tracks = _clean_tracks(row.get("tracks"))
            if track not in tracks:
                continue
            aid = str(row.get("id") or "").strip().lower()
            if not aid or aid in out:
                continue
            item = {
                "description": _clean_text(row.get("description"), MAX_DESCRIPTION),
                "prompt": _clean_text(row.get("prompt"), MAX_PROMPT),
                "custom": True,
                "skills": row.get("skills"),
                "tracks": tracks,
            }
            model = _clean_text(row.get("model"), MAX_MODEL)
            if model:
                item["model"] = model
            out[aid] = item
        return out

    def default_extra_roles(self, objective: str | None) -> list[str]:
        track = track_of(objective)
        out: list[str] = []
        for role, tracks in BUILTIN_TRACKS.items():
            if track not in tracks or is_core(role, track):
                continue
            if self.builtin_cfg(role)["default"] and self.builtin_cfg(role)["enabled"]:
                out.append(role)
        for row in self._load()["custom"]:
            if not bool(row.get("enabled", True)) or not bool(row.get("default", False)):
                continue
            if track in _clean_tracks(row.get("tracks")):
                aid = str(row.get("id") or "").strip().lower()
                if aid and aid not in out:
                    out.append(aid)
        return out


STORE = AgentStore(Path(getattr(settings, "data_dir", settings.data_dir)) / "agents.json")


def apply_agent_config(
    agents: dict[str, dict], objective: str | None, *, store: AgentStore | None = None
) -> dict[str, dict]:
    return (store or STORE).apply_to_agents(agents, objective)


def default_extra_roles(objective: str | None, *, store: AgentStore | None = None) -> list[str]:
    return (store or STORE).default_extra_roles(objective)
