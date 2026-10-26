import { getLocale, t } from "./i18n";

/** 列表/集群筛选：配置了图空转/轮次/时长上限并触顶时进「失败」，不进「未完成」。 */
export const HUNT_FAILED_REASONS = new Set(["graph_idle", "runtime_cap", "turn_cap"]);

/** CTF / 夺旗项目：始终直连靶场，不走出口代理池。 */
export function isCtfProject(p: {
  config?: { track?: string; objective?: string } | null;
} | null | undefined): boolean {
  const t = String(p?.config?.track || "").toLowerCase();
  const o = String(p?.config?.objective || "").toLowerCase();
  return t === "ctf" || o === "flag" || o === "ctf";
}

export function huntFailedReason(p: { config?: { completion_reason?: string } | null } | null | undefined): string | undefined {
  const r = p?.config?.completion_reason;
  if (r && HUNT_FAILED_REASONS.has(r)) return r;
  return undefined;
}

function formatDur(sec: number): string {
  const n = Math.max(0, Math.floor(sec || 0));
  if (n <= 0) return "0";
  if (n % 3600 === 0) return t("dur.hour", { n: n / 3600 });
  if (n % 60 === 0) return t("dur.min", { n: n / 60 });
  if (n >= 3600) {
    const h = Math.floor(n / 3600);
    const m = Math.floor((n % 3600) / 60);
    return m ? t("dur.hourMin", { h, m }) : t("dur.hour", { n: h });
  }
  return t("dur.minShort", { n: Math.floor(n / 60) });
}

/** 项目页/集群页展示硬停条件；运行中附已跑时长。 */
export function hardStopLine(p: {
  hard_stop?: { label?: string; conditions?: string[]; runtime_sec?: number } | null;
  config?: { hunt?: { elapsed_sec?: number } | null } | null;
} | null | undefined): { text: string; title: string; conditions: string[] } | null {
  const hs = p?.hard_stop;
  const label = String(hs?.label || "").trim();
  if (!label) return null;
  const elapsed = Number(p?.config?.hunt?.elapsed_sec || 0);
  const cap = Number(hs?.runtime_sec || 0);
  const ran = cap > 0 && elapsed > 0
    ? t("dur.ran", { elapsed: formatDur(elapsed), cap: formatDur(cap) })
    : "";
  const conditions = (hs?.conditions || []).map((c) => String(c || "").trim()).filter(Boolean);
  return {
    text: ran ? `${label} ${ran}` : label,
    title: conditions.join(getLocale() === "en" ? "; " : "；"),
    conditions,
  };
}

/** 顶栏/列表筛选桶：running / completed / idle / stopped / error */
export function listStatusOf(p: {
  running?: boolean;
  queued?: boolean;
  status?: string;
  config?: { completion_reason?: string } | null;
}): string {
  if (p.queued) return "queued";
  if (p.running) return "running";
  if (huntFailedReason(p)) return "error";
  if (p.status === "goal_reached" || p.status === "completed") return "completed";
  if (p.status === "error") return "error";
  if (p.status === "stopped") return "stopped";
  return "idle";
}

export function formatRunClock(sec: number): string {
  const n = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = n % 60;
  const pad = (x: number) => String(x).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** 进行中用落点时刻继续走秒；停了就停在已记下的时长。 */
export function liveHuntElapsed(
  p: { config?: { hunt?: { elapsed_sec?: number; elapsed_as_of?: number } | null } | null } | null | undefined,
  nowSec: number,
  running: boolean,
): number {
  const hunt = p?.config?.hunt;
  const base = Number(hunt?.elapsed_sec || 0);
  const asOf = Number(hunt?.elapsed_as_of || 0);
  if (running && asOf > 0) return Math.max(0, base + (nowSec - asOf));
  return Math.max(0, base);
}
