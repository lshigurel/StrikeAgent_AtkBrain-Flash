"""设置页可调的猎面撞墙钟。持久化在 proxy-settings.json，启动与保存时写入 settings。"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..proxy.pool import _merge_settings, _settings_path

MAX_WALL_SEC = 72 * 60 * 60
MAX_TURNS = 9999
MIN_IDLE_PLANS = 1
MAX_IDLE_PLANS = 100

# json 键 → settings 属性
CLOCK_KEYS: tuple[str, ...] = (
    "loop_max_turns",
    "loop_max_turns_agent",
    "loop_max_turns_src",
    "loop_max_turns_redteam",
    "agent_runtime_hard_stop_sec",
    "src_runtime_hard_stop_sec",
    "redteam_runtime_hard_stop_sec",
    "runtime_hard_stop_sec",
    "runtime_hard_stop_pass2_sec",
    "runtime_hard_stop_pass3_sec",
    "runtime_hard_stop_pass_step_sec",
    "graph_idle_empty_plans",
    "loop_stall_limit_agent",
    "loop_stall_limit_redteam",
    "loop_stall_limit_src",
)


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp_wall(sec: int) -> int:
    if sec < 0:
        return 0
    return min(int(sec), MAX_WALL_SEC)


def _clamp_turns(n: int) -> int:
    if n < 0:
        return 0
    return min(int(n), MAX_TURNS)


def _clamp_plans(n: int) -> int:
    if n <= 0:
        return MIN_IDLE_PLANS
    return max(MIN_IDLE_PLANS, min(int(n), MAX_IDLE_PLANS))


def _clamp_stall(n: int) -> int:
    if n < 0:
        return 0
    return min(int(n), MAX_TURNS)


def defaults() -> dict[str, int]:
    return {
        "loop_max_turns": 0,
        "loop_max_turns_agent": 0,
        "loop_max_turns_src": 0,
        "loop_max_turns_redteam": 0,
        "agent_runtime_hard_stop_sec": 6 * 60 * 60,
        "src_runtime_hard_stop_sec": 6 * 60 * 60,
        "redteam_runtime_hard_stop_sec": 6 * 60 * 60,
        "runtime_hard_stop_sec": 40 * 60,
        "runtime_hard_stop_pass2_sec": 120 * 60,
        "runtime_hard_stop_pass3_sec": 180 * 60,
        "runtime_hard_stop_pass_step_sec": 60 * 60,
        "graph_idle_empty_plans": 6,
        "loop_stall_limit_agent": 10,
        "loop_stall_limit_redteam": 10,
        "loop_stall_limit_src": 10,
    }


def _read_file() -> dict[str, Any]:
    p = _settings_path()
    if not p.is_file():
        return {}
    try:
        import json
        loaded = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _normalize(raw: dict[str, Any] | None = None) -> dict[str, int]:
    base = defaults()
    src = dict(raw or {})
    out: dict[str, int] = {}
    for key in CLOCK_KEYS:
        live = _as_int(getattr(settings, key, base[key]), base[key])
        val = _as_int(src.get(key, live), live)
        if key.endswith("_sec"):
            out[key] = _clamp_wall(val)
        elif key == "graph_idle_empty_plans":
            out[key] = _clamp_plans(val)
        elif key.startswith("loop_stall"):
            out[key] = _clamp_stall(val)
        else:
            out[key] = _clamp_turns(val)
    _unify_agent_clocks(out, src)
    return out


def _unify_agent_clocks(out: dict[str, int], raw: dict[str, Any] | None) -> None:
    """agent 测试只有一口钟。旧的 src / redteam 键读入后写成同一个数，避免再分开。"""
    raw = raw or {}

    def pick(agent_key: str, src_key: str, red_key: str) -> int:
        if agent_key in raw and raw.get(agent_key) is not None:
            return out[agent_key]
        if src_key in raw and raw.get(src_key) is not None:
            return out[src_key]
        if red_key in raw and raw.get(red_key) is not None:
            return out[red_key]
        return out[agent_key]

    wall = pick("agent_runtime_hard_stop_sec", "src_runtime_hard_stop_sec", "redteam_runtime_hard_stop_sec")
    turns = pick("loop_max_turns_agent", "loop_max_turns_src", "loop_max_turns_redteam")
    stall = pick("loop_stall_limit_agent", "loop_stall_limit_src", "loop_stall_limit_redteam")
    out["agent_runtime_hard_stop_sec"] = wall
    out["src_runtime_hard_stop_sec"] = wall
    out["redteam_runtime_hard_stop_sec"] = wall
    out["loop_max_turns_agent"] = turns
    out["loop_max_turns_src"] = turns
    out["loop_max_turns_redteam"] = turns
    out["loop_stall_limit_agent"] = stall
    out["loop_stall_limit_src"] = stall
    out["loop_stall_limit_redteam"] = stall


def get_hunt_clocks() -> dict[str, int]:
    data = _read_file()
    return _normalize(data)


def apply_hunt_clocks_to_settings(clocks: dict[str, int] | None = None) -> dict[str, int]:
    got = clocks or get_hunt_clocks()
    for key, val in got.items():
        setattr(settings, key, int(val))
    # 旧字段：红队空转暂停仍有代码读 loop_stall_limit
    settings.loop_stall_limit = int(got.get("loop_stall_limit_agent") or 10)
    return got


def set_hunt_clocks(updates: dict[str, Any] | None) -> dict[str, int]:
    cur = get_hunt_clocks()
    if updates:
        merged = dict(cur)
        for key in CLOCK_KEYS:
            if key in updates and updates[key] is not None:
                merged[key] = updates[key]
        # 只改了旧键时，不要让先前合成的 agent 键盖住这次写入。
        if "agent_runtime_hard_stop_sec" not in updates and (
            "src_runtime_hard_stop_sec" in updates or "redteam_runtime_hard_stop_sec" in updates
        ):
            merged.pop("agent_runtime_hard_stop_sec", None)
        if "loop_max_turns_agent" not in updates and (
            "loop_max_turns_src" in updates or "loop_max_turns_redteam" in updates
        ):
            merged.pop("loop_max_turns_agent", None)
        if "loop_stall_limit_agent" not in updates and (
            "loop_stall_limit_src" in updates or "loop_stall_limit_redteam" in updates
        ):
            merged.pop("loop_stall_limit_agent", None)
        cur = _normalize(merged)
        _merge_settings({k: int(cur[k]) for k in CLOCK_KEYS})
    return apply_hunt_clocks_to_settings(cur)
