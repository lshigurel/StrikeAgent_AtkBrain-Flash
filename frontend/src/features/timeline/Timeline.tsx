import { useEffect, useMemo, useRef } from "react";
import type { RTEvent } from "../../types";
import { displayFindingSeverity } from "../../theme";
import { coalesceStreamEvents } from "./coalesce";
import { t, useT } from "../../i18n";

const TIMELINE_TYPES = new Set([
  "text", "thought", "tool", "tool_result", "finding", "shell", "steer", "status", "log",
  "intent", "turn", "node", "edge", "rce_path", "lateral", "drift_alert", "finding_review", "report_export",
]);

function line(ev: RTEvent): string {
  const p = ev.payload || {};
  switch (ev.type) {
    case "text": return p.text?.slice(0, 300) || "";
    case "thought": return "💭 " + (p.message?.slice(0, 800) || "");
    case "tool": return `▶ ${p.tool}` + (p.command ? `: ${p.command}` : p.url ? `: ${p.method || ""} ${p.url}` : p.input ? `: ${p.input}` : "");
    case "tool_result": return p.tool === "run_cmd" ? `exit=${p.exit_code}${p.blocked ? t("timeline.blocked") : ""} ${(p.stdout_preview || p.reason || "").slice(0, 200)}` : `${p.status ?? ""} ${(p.preview || p.error || "").slice(0, 200)}`;
    case "finding": {
      const sev = displayFindingSeverity(p);
      return `${sev === "critical" ? "★ " : ""}[${sev}] ${p.title} (${p.category})`;
    }
    case "shell": return `🎯 GETSHELL! ${p.access || ""} ${(p.evidence || "").slice(0, 120)}`;
    case "lateral": return `🌐 ${t("timeline.lateralStart")}${p.hosts_footed ? t("timeline.hosts", { n: p.hosts_footed }) : ""}${p.pivot_edges ? t("timeline.pivots", { n: p.pivot_edges }) : ""}`;
    case "finding_review": {
      const n = Number(p.count || (p.titles || []).length || 0);
      if (p.status === "running") return `🔎 ${t("timeline.reviewRun", { n })}`;
      return n ? `🔎 ${t("timeline.reviewDoneN", { n })}` : `🔎 ${t("timeline.reviewDone")}`;
    }
    case "report_export": {
      if (p.status === "running") return `📄 ${t("timeline.exportRun")}`;
      if (p.status === "error") return `📄 ${t("timeline.exportErr", { msg: String(p.message || "").slice(0, 160) })}`;
      return `📄 ${t("timeline.exportDone")}`;
    }
    case "drift_alert": return `⚠️ ${t("timeline.drift", { cat: p.category || "", msg: (p.message || "").slice(0, 220) })}`;
    case "steer": return `⚡ ${p.content}`;
    case "status": return `${t("timeline.statusLine", { status: p.status })}${p.turn ? t("timeline.turnN", { n: p.turn }) : ""}`;
    case "log": return `${p.level === "error" ? "✖" : p.level === "warn" ? "⚠" : "ℹ"} ${p.message}`;
    case "intent": return t("timeline.intentLine", { desc: p.description });
    case "turn": return `${t("timeline.turnEnd", { steps: p.num_turns ?? "?" })}${p.total_cost_usd ? `, $${Number(p.total_cost_usd).toFixed(3)}` : ""})`;
    default: return JSON.stringify(p).slice(0, 160);
  }
}

function labelOf(ev: RTEvent): string {
  if (ev.type === "steer" && ev.payload?.source === "supervisor") return t("timeline.supervisor");
  if (ev.type === "steer") return t("timeline.human");
  const key = `timeline.${ev.type}`;
  return TIMELINE_TYPES.has(ev.type) ? t(key) : ev.type;
}

const CLS: Record<string, string> = { finding: "t-finding", shell: "t-shell", lateral: "t-shell", tool: "t-tool", steer: "t-steer", log: "t-error", drift_alert: "t-error", finding_review: "t-steer", report_export: "t-steer" };
const SKIP = new Set(["node", "edge", "rce_path", "supervisor"]);
/** 时间线只渲染最近 N 条，避免长跑项目 DOM 上千节点卡死 */
const MAX_SHOWN = 150;

export function Timeline({ events }: { events: RTEvent[] }) {
  const { t: tr } = useT();
  const ref = useRef<HTMLDivElement>(null);
  const shown = useMemo(() => {
    const filtered = coalesceStreamEvents(events).filter((e) => !SKIP.has(e.type) && TIMELINE_TYPES.has(e.type));
    return filtered.length > MAX_SHOWN ? filtered.slice(-MAX_SHOWN) : filtered;
  }, [events]);

  // 长跑时 shown 被截到 MAX_SHOWN，length 不再变；用末条 id/ts 触发滚到底，避免时间线看起来“卡住”
  const tailKey = shown.length ? (shown[shown.length - 1].id ?? shown[shown.length - 1].ts) : 0;
  useEffect(() => {
    const pane = ref.current?.closest(".project-side-body");
    const el = pane instanceof HTMLElement ? pane : ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [tailKey]);

  return (
    <div className="scroll-y" ref={ref} style={{ maxHeight: 520 }}>
      {shown.length === 0 && <p className="muted" style={{ fontSize: 14 }}>{tr("timeline.empty")}</p>}
      {shown.map((ev) => (
        <div key={ev.id ?? `${ev.ts}-${ev.type}`} className={`timeline-item ${ev.type === "log" && ev.payload?.level !== "error" ? "" : CLS[ev.type] || ""}`}>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>{labelOf(ev)}</div>
          <div style={{ fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{line(ev)}</div>
        </div>
      ))}
    </div>
  );
}
