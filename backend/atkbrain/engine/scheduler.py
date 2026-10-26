"""运行调度：全局并发信号量（可运行时调整）+ 项目运行生命周期 + steering 队列。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..config import benchmark_slot_limit, settings


def _task_is_cancelling() -> bool:
    """当前协程是否正在被取消（HTTP 断开 / shutdown），区别于子猎任务的 CancelledError。"""
    task = asyncio.current_task()
    if task is None:
        return False
    fn = getattr(task, "cancelling", None)
    if not callable(fn):
        return False
    try:
        return int(fn()) > 0
    except Exception:
        return False


class DynamicSemaphore:
    """并发上限可在运行时调整的信号量。"""

    def __init__(self, value: int) -> None:
        self._limit = value
        self._active = 0
        self._cond = asyncio.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    async def set_limit(self, value: int) -> None:
        async with self._cond:
            self._limit = max(1, value)
            self._cond.notify_all()

    async def acquire(self) -> None:
        async with self._cond:
            while self._active >= self._limit:
                await self._cond.wait()
            self._active += 1

    async def release(self) -> None:
        async with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify_all()

    def force_active(self, n: int) -> None:
        """纠偏泄漏：把占槽数掰回真实持有数，并唤醒排队者。"""
        self._active = max(0, int(n))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _wake() -> None:
            async with self._cond:
                self._cond.notify_all()

        loop.create_task(_wake())


@dataclass
class RunHandle:
    project_id: str
    task: asyncio.Task | None = None
    agent: object | None = None                       # ProjectAgent
    steering: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    status: str = "starting"
    run_id: str | None = None
    hard_restart: bool = False  # True=清图+新容器+烧 attempt；False=续跑
    user_stop: bool = False     # True=人工暂停，重启后不要自动拉起
    human_interrupt: bool = False  # 人工强制指令：打断本轮从者，下一轮立刻改向
    slot_held: bool = False     # 已拿到本赛道项目并发槽
    slot_kind: str = "redteam"  # redteam | ctf
    bench_held: bool = False    # 兼容旧句柄；现与 ctf 槽合一，不再单独占


def hunt_slot_kind(project: dict | None, objective: str | None = None) -> str:
    """CTF / 评测 CTF 子题走 ctf 槽；红队与 SRC（含胶水 SRC 子猎）走红队槽。"""
    from ..objective import objective_allows_flag, objective_is_src
    from .. import benchmark as bmk
    obj = objective
    if not obj and project:
        cfg = project.get("config") or {}
        obj = (cfg.get("objective") or cfg.get("track") or "") if isinstance(cfg, dict) else ""
    if objective_is_src(obj):
        return "redteam"
    if project and bmk.is_benchmark_sub(project):
        return "ctf"
    return "ctf" if objective_allows_flag(obj) else "redteam"


async def _write_intent_steer(intent_id: str, message: str) -> None:
    from ..db import db, now
    await db.execute(
        "UPDATE intents SET pending_steer=?, updated_at=? WHERE id=?",
        ((message or "").strip()[:2000], now(), intent_id),
    )


async def acquire_slot_fifo(project_id: str, sem) -> None:
    """按项目 queued_at 的提交顺序拿并发槽。暂停、删除、超时走句柄释放。"""
    from ..db import db

    while True:
        async with _QUEUE_LINE:
            row = await db.fetchone(
                """SELECT id FROM projects
                   WHERE status='queued' AND IFNULL(archived,0)=0
                   ORDER BY COALESCE(queued_at, updated_at) ASC
                   LIMIT 1"""
            )
            head = str((row or {}).get("id") or "")
            if head in ("", project_id):
                await sem.acquire()
                return
        await asyncio.sleep(0.25)


_QUEUE_LINE = asyncio.Lock()


class RunManager:
    """两道互不占槽的项目闸：
    - 红队 `redteam_sem`：红队与 SRC 同时跑的数量（默认 5）。
    - CTF `ctf_sem`：CTF / 评测子题（默认 3，上限 20）。
    项目内 Pi：从者+工人默认 4，整机默认 32；顶栏 health 报真实数字。
    """

    def __init__(self) -> None:
        rt_limit = min(settings.max_redteam_concurrency, settings.max_redteam_concurrency_cap)
        ctf_limit = benchmark_slot_limit()
        from ..agents.pi_runtime import pi_max_live_limit, pi_per_project_limit
        self.redteam_sem = DynamicSemaphore(max(1, rt_limit))
        self.ctf_sem = DynamicSemaphore(max(1, ctf_limit))
        # 旧名：只代表红队槽。CTF 不再走这道闸。
        self.project_sem = self.redteam_sem
        self.sem = self.redteam_sem
        self.bench_sem = self.ctf_sem
        self.claude_per_project = pi_per_project_limit()
        self.max_claude = pi_max_live_limit()
        self.handles: dict[str, RunHandle] = {}
        self.shutting_down = False

    def slot_sem(self, kind: str) -> DynamicSemaphore:
        return self.ctf_sem if kind == "ctf" else self.redteam_sem

    @property
    def claude_active(self) -> int:
        """本机正在跑的 Pi 进程数（含从者/工人/复核/一次性）。"""
        from ..agents.pi_runtime import live_pi_count
        return live_pi_count()

    def is_running(self, project_id: str) -> bool:
        h = self.handles.get(project_id)
        # zombie/stopping：句柄残留但不再占用调度语义，允许重新 start
        if not h or not h.task or h.task.done():
            return False
        if h.status in ("done", "stopping", "zombie"):
            return False
        return True

    def is_queued(self, project_id: str) -> bool:
        """已 start 但还在等项目并发槽（sem.acquire 之前），未真正开跑。

        UI 应显示「排队中」，不要算进「运行中」——否则会出现「并发已满、列表却多一条运行中」。
        """
        h = self.handles.get(project_id)
        if not h or not h.task or h.task.done():
            return False
        return h.status == "starting"

    def get(self, project_id: str) -> RunHandle | None:
        return self.handles.get(project_id)

    def _relink_claude_cap(self) -> None:
        from ..agents.pi_runtime import pi_max_live_limit, pi_per_project_limit
        self.claude_per_project = pi_per_project_limit()
        self.max_claude = pi_max_live_limit()

    async def set_concurrency(self, value: int, *, track: str = "redteam") -> int:
        """按赛道设置项目并发。track=ctf 只动 CTF 槽，红队反之。"""
        kind = "ctf" if str(track or "").strip().lower() in ("ctf", "flag", "benchmark") else "redteam"
        if kind == "ctf":
            return await self.set_ctf_concurrency(value)
        return await self.set_redteam_concurrency(value)

    async def set_redteam_concurrency(self, value: int) -> int:
        value = max(1, min(int(value), settings.max_redteam_concurrency_cap))
        await self.redteam_sem.set_limit(value)
        self._relink_claude_cap()
        return value

    async def set_ctf_concurrency(self, value: int) -> int:
        cap = int(getattr(settings, "max_ctf_concurrency_cap", 20) or 20)
        if cap <= 0:
            cap = 20
        value = max(1, min(int(value), cap))
        await self.ctf_sem.set_limit(value)
        settings.benchmark_max_concurrency = value
        self._relink_claude_cap()
        return value

    # 语义更清晰的别名
    async def set_project_concurrency(self, value: int) -> int:
        return await self.set_redteam_concurrency(value)

    def set_claude_per_project(self, value: int) -> int:
        from ..agents.pi_runtime import pi_per_project_limit
        try:
            cap = int(getattr(settings, "pi_per_project_cap", None)
                      or getattr(settings, "claude_per_project_cap", None)
                      or 8)
        except (TypeError, ValueError):
            cap = 8
        if cap <= 0:
            cap = 8
        n = max(1, min(int(value or 0) or 4, cap))
        settings.pi_per_project = n
        settings.claude_per_project = n
        self._relink_claude_cap()
        return pi_per_project_limit()

    def _drop_handle(self, project_id: str, handle: RunHandle | None = None) -> None:
        cur = self.handles.get(project_id)
        if cur is None:
            return
        if handle is None or cur is handle:
            self.handles.pop(project_id, None)

    async def release_handle_slots(self, handle: RunHandle | None) -> None:
        """幂等释放句柄占的项目槽。僵尸收口与 loop finally 都走这里，避免双 release。"""
        if handle is None:
            return
        if handle.slot_held:
            handle.slot_held = False
            await self.slot_sem(handle.slot_kind).release()
        if handle.bench_held:
            handle.bench_held = False

    def _slot_holders(self, kind: str | None = None) -> list[str]:
        out: list[str] = []
        for pid, h in self.handles.items():
            if not h.slot_held:
                continue
            if h.status != "running":
                continue
            if not h.task or h.task.done():
                continue
            if kind and h.slot_kind != kind:
                continue
            out.append(pid)
        return out

    def start(self, project_id: str, *, hard_restart: bool = False) -> RunHandle:
        from .loop import run_project_loop  # 延迟导入避免环依赖

        if self.is_running(project_id):
            return self.handles[project_id]

        # 清掉已结束或僵尸句柄，避免 UI 显示 running 却无法再次启动
        old = self.handles.pop(project_id, None)
        if old and old.task and not old.task.done():
            old.status = "zombie"
            old.task.cancel()
            if old.slot_held:
                asyncio.create_task(self.release_handle_slots(old))

        handle = RunHandle(project_id=project_id, hard_restart=hard_restart)
        self.handles[project_id] = handle

        def _cleanup(t: asyncio.Task, pid: str = project_id, owned: RunHandle = handle) -> None:
            cur = self.handles.get(pid)
            if cur is owned:
                self.handles.pop(pid, None)

        handle.task = asyncio.create_task(run_project_loop(self, project_id))
        handle.task.add_done_callback(_cleanup)
        return handle

    async def stop(self, project_id: str) -> bool:
        h = self.handles.get(project_id)
        if not h:
            return False
        h.user_stop = True
        h.status = "stopping"
        try:
            from .hunt_resume import forget_resume
            forget_resume(project_id)
        except Exception:
            pass
        if h.agent is not None:
            try:
                await h.agent.interrupt()  # type: ignore[attr-defined]
            except asyncio.CancelledError:
                if _task_is_cancelling():
                    raise
            except Exception:
                pass
        try:
            from ..agents.pi_runtime import kill_live_for_project
            await asyncio.to_thread(kill_live_for_project, project_id)
        except asyncio.CancelledError:
            if _task_is_cancelling():
                raise
        except Exception:
            pass
        if h.task and not h.task.done():
            h.task.cancel()
            try:
                await asyncio.wait_for(h.task, timeout=12)
            except asyncio.CancelledError:
                if _task_is_cancelling() and (h.task is None or not h.task.done()):
                    raise
            except (asyncio.TimeoutError, Exception):
                # 取消后仍卡住（例如 SDK 忽略 cancel）→ 降级为 zombie，解除 is_running 占位
                if not h.task.done():
                    h.status = "zombie"
                    try:
                        from ..agents.pi_runtime import kill_live_for_project
                        await asyncio.to_thread(kill_live_for_project, project_id)
                    except Exception:
                        pass
                    await self.release_handle_slots(h)
                    try:
                        from ..projects import update_status
                        await update_status(project_id, "idle")
                    except Exception:
                        pass
                    return True
        await self.release_handle_slots(h)
        self._drop_handle(project_id, h)
        return True

    async def halt(self, project_id: str, *, reason: str = "user_stop") -> bool:
        """真正停猎：杀 Pi/命令、清续跑清单、项目改 idle。没有句柄也照做，不留幽灵。"""
        from ..events import emit
        from ..projects import update_status
        from .hunt_resume import forget_resume

        try:
            forget_resume(project_id)
        except Exception:
            pass
        try:
            from ..agents.pi_runtime import kill_live_for_project
            await asyncio.to_thread(kill_live_for_project, project_id)
        except Exception:
            pass
        had = bool(self.handles.get(project_id))
        if had:
            try:
                await self.stop(project_id)
            except asyncio.CancelledError:
                # 猎循环 cancel 会冒到这里；再抛出会让 Starlette BaseHTTPMiddleware 变成 HTTP 500
                if _task_is_cancelling():
                    raise
            except Exception:
                pass
            try:
                from ..agents.pi_runtime import kill_live_for_project
                await asyncio.to_thread(kill_live_for_project, project_id)
            except Exception:
                pass
        try:
            await update_status(project_id, "idle")
        except Exception:
            pass
        try:
            await emit(
                project_id, "status",
                {"status": "stopped", "reason": reason},
            )
        except Exception:
            pass
        return True

    def steer(self, project_id: str, message: str, intent_id: str | None = None) -> bool:
        """纠偏只写到那一条意图，下一工具调用前交给该工人。不打断项目里的其它意图。"""
        h = self.handles.get(project_id)
        if not h or not self.is_running(project_id):
            return False
        iid = str(intent_id or "").strip()
        if not iid and h.agent is not None:
            bound = getattr(getattr(h.agent, "ctx", None), "bound_must_intents", None) or ()
            ids = [str(x) for x in bound if str(x or "").strip()]
            if len(ids) == 1:
                iid = ids[0]
        if iid:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(_write_intent_steer(iid, message))
            return True
        try:
            h.steering.put_nowait(message)
        except asyncio.QueueFull:
            return False
        h.human_interrupt = True
        agent = h.agent
        if agent is not None and hasattr(agent, "interrupt"):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                async def _nudge() -> None:
                    try:
                        await agent.interrupt(halt=False)  # type: ignore[misc]
                    except Exception:
                        pass
                loop.create_task(_nudge())
        return True

    def has_pending_human(self, project_id: str) -> bool:
        h = self.handles.get(project_id)
        if not h:
            return False
        if getattr(h, "human_interrupt", False):
            return True
        return h.steering.qsize() > 0

    def take_human_interrupt(self, project_id: str) -> bool:
        """本轮因人工指令被打断：取出并清旗，供循环立刻进入下一轮。"""
        h = self.handles.get(project_id)
        if not h or not getattr(h, "human_interrupt", False):
            return False
        h.human_interrupt = False
        return True

    def drain_steering(self, project_id: str) -> list[str]:
        h = self.handles.get(project_id)
        if not h:
            return []
        out: list[str] = []
        while True:
            try:
                out.append(h.steering.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    def snapshot(self) -> dict:
        # 顺手清掉已 done 的残留句柄
        for pid, h in list(self.handles.items()):
            if h.task is None or h.task.done():
                if h.status != "zombie":
                    self.handles.pop(pid, None)
        live_rt = self._slot_holders("redteam")
        live_ctf = self._slot_holders("ctf")
        live = live_rt + live_ctf
        queued = [pid for pid in self.handles if self.is_queued(pid)]
        if self.redteam_sem.active != len(live_rt):
            self.redteam_sem.force_active(len(live_rt))
        if self.ctf_sem.active != len(live_ctf):
            self.ctf_sem.force_active(len(live_ctf))
        rt_cap = settings.max_redteam_concurrency_cap
        ctf_cap = max(1, int(getattr(settings, "max_ctf_concurrency_cap", 20) or 20))
        return {
            "concurrency_limit": self.redteam_sem.limit + self.ctf_sem.limit,
            "active": len(live),
            "cap": rt_cap + ctf_cap,
            "running": live,
            "queued": queued,
            "redteam": {
                "active": len(live_rt),
                "limit": self.redteam_sem.limit,
                "cap": rt_cap,
            },
            "ctf": {
                "active": len(live_ctf),
                "limit": self.ctf_sem.limit,
                "cap": ctf_cap,
            },
            "projects": {
                "active": len(live),
                "limit": self.redteam_sem.limit + self.ctf_sem.limit,
                "cap": rt_cap + ctf_cap,
            },
            "claude": {
                "active": self.claude_active,
                "limit": self.max_claude,
                "cap": int(getattr(settings, "pi_max_live_cap", 96) or 96),
                "per_project": self.claude_per_project,
            },
        }

    async def checkpoint_for_shutdown(self, timeout: float = 8.0) -> None:
        """关机前取消猎循环并等猎钟落盘。必须在关闭数据库之前调用。"""
        self.shutting_down = True
        tasks = [
            h.task for h in list(self.handles.values())
            if h.task is not None and not h.task.done()
        ]
        for t in tasks:
            t.cancel()
        if not tasks:
            return
        try:
            await asyncio.wait(tasks, timeout=max(0.5, float(timeout or 0)))
        except Exception:
            pass


manager = RunManager()
