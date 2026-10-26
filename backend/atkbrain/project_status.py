"""项目收口状态。

CTF（含评测子题）：不限轮次、不做御主运行时审查。
墙钟硬停按遍次：第 1 遍 40 分钟，第 2 遍 120 分钟，第 3 遍 180 分钟，之后每次 +60。
图空转：连续 6 个御主方案仍无新节点、无交旗、也无本地长计算 → 失败。
评测覆盖期按第 1 遍墙钟让槽，全部开过一轮后再回头啃未出/未齐 flag。
agent 测试：墙钟、连续 30 轮无新节点且无新漏洞、或手动停止。不以拿到 shell 收工。
入口不可达、会话故障、轮次上限都不停。
"""
from __future__ import annotations

HUNT_FAILED_REASONS = frozenset({
    "graph_idle", "runtime_cap", "turn_cap", "empty_rounds",
})
EMPTY_ROUND_STOP = 30


def uses_ctf_hunt_clocks(objective: str | None = None) -> bool:
    """图空转只给 CTF（含评测子题）。墙钟红队与 CTF 各自有上限。CTF 不限轮次、不审查。"""
    from .objective import FLAG, normalize_objective
    return normalize_objective(objective) == FLAG


def ctf_pass_hard_stop_sec(pass_n: int | None = None) -> int:
    """CTF 第 N 遍墙钟硬上限（秒）。1=40min，2=120，3=180，之后每次 +60。"""
    from .config import settings
    try:
        n = max(1, int(pass_n or 1))
    except (TypeError, ValueError):
        n = 1
    try:
        p1 = max(0, int(getattr(settings, "runtime_hard_stop_sec", 40 * 60) or 0))
    except (TypeError, ValueError):
        p1 = 40 * 60
    try:
        p2 = max(0, int(getattr(settings, "runtime_hard_stop_pass2_sec", 120 * 60) or 0))
    except (TypeError, ValueError):
        p2 = 120 * 60
    try:
        p3 = max(0, int(getattr(settings, "runtime_hard_stop_pass3_sec", 180 * 60) or 0))
    except (TypeError, ValueError):
        p3 = 180 * 60
    try:
        step = max(0, int(getattr(settings, "runtime_hard_stop_pass_step_sec", 60 * 60) or 0))
    except (TypeError, ValueError):
        step = 60 * 60
    if n <= 1:
        return p1
    if n == 2:
        return p2
    if n == 3:
        return p3
    return p3 + (n - 3) * step


def ctf_pass_index(*, ended_real_attempts: int = 0) -> int:
    """已结束的真正 attempt 数 + 1 = 本猎遍次。"""
    try:
        n = max(0, int(ended_real_attempts or 0))
    except (TypeError, ValueError):
        n = 0
    return n + 1


def hunt_runtime_hard_stop_sec(objective: str | None = None, *, pass_n: int | None = None) -> int:
    """本猎墙钟硬上限（秒）。CTF 按遍次；agent 测试用同一口钟；0 表示不限。"""
    from .config import settings
    if uses_ctf_hunt_clocks(objective):
        return ctf_pass_hard_stop_sec(pass_n)
    try:
        return max(0, int(getattr(settings, "agent_runtime_hard_stop_sec", 6 * 60 * 60) or 0))
    except (TypeError, ValueError):
        return 6 * 60 * 60


def format_duration(sec: int | float | None, lang: str | None = None) -> str:
    from .i18n.locale import get_locale, normalize_locale
    from .i18n.strings import msg

    loc = normalize_locale(lang or get_locale())
    try:
        n = max(0, int(sec or 0))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return msg("hs.unlimited", loc)
    if loc == "en":
        if n % 3600 == 0:
            h = n // 3600
            return f"{h} hour" if h == 1 else f"{h} hours"
        if n % 60 == 0:
            m = n // 60
            return f"{m} minute" if m == 1 else f"{m} minutes"
        return f"{n} second" if n == 1 else f"{n} seconds"
    if n % 3600 == 0:
        return f"{n // 3600} 小时"
    if n % 60 == 0:
        return f"{n // 60} 分钟"
    return f"{n} 秒"


def format_duration_zh(sec: int | float | None) -> str:
    return format_duration(sec, "zh")


def _setting_int(name: str, default: int) -> int:
    from .config import settings
    try:
        return max(0, int(getattr(settings, name, default) or 0))
    except (TypeError, ValueError):
        return max(0, int(default or 0))


def hunt_hard_stop_info(objective: str | None = None, *, pass_n: int | None = None, lang: str | None = None) -> dict:
    """给 UI / 开猎日志的停猎条件：硬停记失败、暂停可再开、本 run 故障自动重试。"""
    from .i18n.locale import get_locale, normalize_locale
    from .i18n.strings import msg
    from .objective import FLAG, normalize_objective

    loc = normalize_locale(lang or get_locale())
    runtime = hunt_runtime_hard_stop_sec(objective, pass_n=pass_n)
    turns = hunt_max_turns(objective)
    cap = format_duration(runtime, loc)
    hang = format_duration(_setting_int("turn_hang_sec", 8 * 60), loc)
    ctf_entry_sec = _setting_int("benchmark_entry_down_yield_sec", 8 * 60)
    o = normalize_objective(objective)
    retry = msg("hs.retry", loc, hang=hang)
    if o == FLAG:
        idle_n = max(1, _setting_int("graph_idle_empty_plans", 6) or 6)
        conditions = [
            msg("hs.ctf_wall", loc, cap=cap),
            msg("hs.ctf_idle", loc, n=idle_n),
            retry,
        ]
        if ctf_entry_sec > 0:
            conditions.insert(2, msg("hs.ctf_entry", loc, dur=format_duration(ctf_entry_sec, loc)))
        conditions.insert(-1, msg("hs.ctf_env", loc))
        label = msg("hs.ctf_label", loc, cap=cap, n=idle_n)
    else:
        conditions = [
            msg("hs.wall_fail", loc, cap=cap),
            msg("hs.empty_rounds", loc, n=EMPTY_ROUND_STOP),
            msg("hs.manual", loc),
        ]
        label = msg("hs.src_label", loc, cap=cap, n=EMPTY_ROUND_STOP)
    return {
        "track": o,
        "runtime_sec": runtime,
        "max_turns": turns,
        "conditions": conditions,
        "label": label,
    }


def hunt_max_turns(objective: str | None = None, *, is_benchmark: bool = False) -> int:
    """本猎最大编排轮次。0=不限。agent 测试共用一口轮次钟。"""
    del is_benchmark
    if uses_ctf_hunt_clocks(objective):
        return _setting_int("loop_max_turns", 0)
    return _setting_int("loop_max_turns_agent", 0)


def anchor_hunt_elapsed(
    hunt: dict | None,
    *,
    running: bool,
    run_started_at: float | None = None,
    now_ts: float | None = None,
) -> dict:
    """给页面的运行时间。进行中从上次落点继续走，不把硬停上限写进这行。"""
    import time as _time

    out = dict(hunt or {})
    now = float(now_ts if now_ts is not None else _time.time())
    try:
        elapsed = max(0.0, float(out.get("elapsed_sec") or 0))
    except (TypeError, ValueError):
        elapsed = 0.0
    if not running:
        out["elapsed_sec"] = elapsed
        out.pop("elapsed_as_of", None)
        return out
    try:
        as_of = float(out.get("elapsed_as_of") or 0)
    except (TypeError, ValueError):
        as_of = 0.0
    if as_of > 0:
        elapsed += max(0.0, now - as_of)
    else:
        try:
            started = float(run_started_at or 0)
        except (TypeError, ValueError):
            started = 0.0
        if started > 0:
            elapsed = max(elapsed, now - started)
    out["elapsed_sec"] = elapsed
    out["elapsed_as_of"] = now
    return out


def displayed_status(
    db_status: str | None, *, running: bool = False, queued: bool = False,
) -> str:
    """给 UI 的状态：以活句柄为准。DB 里残留的 running 在没进程时算空闲。"""
    if queued:
        return "queued"
    if running:
        return "running"
    st = (db_status or "idle").strip().lower()
    if st == "running":
        return "idle"
    if st == "goal_reached":
        return "completed"
    return st or "idle"


def final_project_status(
    *, goal: bool, exhausted: bool = False, pause_reason: str | None = None,
) -> str:
    if goal:
        return "completed"
    if exhausted or (pause_reason in HUNT_FAILED_REASONS):
        return "error"
    return "idle"
