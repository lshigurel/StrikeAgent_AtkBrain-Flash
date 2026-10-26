import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatApiError } from "../../api";
import type { Project } from "../../types";
import { Badge } from "../../components/Badge";
import { BatchSelectionBar } from "../../components/BatchSelectionBar";
import { PaginationBar, pageItems, readPageSize } from "../../components/PaginationBar";
import { colors } from "../../theme";
import { ReportExportControls } from "../report/ExportReport";
import { t, useT } from "../../i18n";

const statusColor: Record<string, string> = {
  running: colors.success, queued: colors.warning, completed: colors.primary, idle: colors.mutedSoft, error: colors.error, stopped: colors.muted,
};

function statusText(key: string): string {
  const map: Record<string, string> = {
    running: t("status.running"),
    queued: t("status.queued"),
    completed: t("status.completed"),
    idle: t("status.idle"),
    error: t("status.error"),
    stopped: t("status.stopped"),
  };
  return map[key] || key;
}

const STATUS_FILTER_KEYS = ["all", "running", "completed", "idle", "stopped", "error"] as const;

function statusFilterText(key: string): string {
  const map: Record<string, string> = {
    all: t("projects.statusAll"),
    running: t("projects.statusRunning"),
    completed: t("projects.statusCompleted"),
    idle: t("projects.statusIdle"),
    stopped: t("projects.statusStopped"),
    error: t("projects.statusError"),
  };
  return map[key] || key;
}

function filterStatusOf(c: Board["challenges"][number]): string {
  if (c.is_completed || c.status === "completed") return "completed";
  if (c.status === "queued" || c.queued || c.status === "running") return "running";
  if (c.status === "error") return "error";
  if (c.status === "stopped") return "stopped";
  return "idle";
}

interface Board {
  cumulative_score: number;
  total_flags: number;
  correct_flags: number;
  slot_limit?: number;
  slot_running?: number;
  slot_queued?: number;
  challenges: {
    subproject_id: string; unique_code?: string; name: string; status: string;
    flag_count: number; correct_flag_count: number; score: number;
    difficulty?: string; total_score?: number; is_completed: boolean;
    has_shell?: boolean; lateral_active?: boolean; queued?: boolean;
  }[];
}

export function BenchmarkDashboard({ project }: { project: Project }) {
  const { t: tr } = useT();
  const [board, setBoard] = useState<Board | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(readPageSize);

  const bm = project.config?.benchmark || {};
  const rawTrack = String((project.config as any)?.track || (project.config as any)?.objective || "").toLowerCase();
  const labSrc = rawTrack === "agent" || rawTrack === "src" || rawTrack === "redteam";
  const envClosed = Boolean((project.config as any)?.env_closed);

  const load = () => api.scoreboard(project.id).then(setBoard).catch(() => {});
  useEffect(() => {
    load();
    const tmr = setInterval(load, 12000);
    return () => clearInterval(tmr);
  }, [project.id]);

  const chs = board?.challenges || [];
  const slotLimit = board?.slot_limit || 3;
  const runningCount = chs.filter((c) => c.status === "running").length;
  const queuedCount = chs.filter((c) => c.status === "queued" || c.queued).length;
  const liveCount = chs.filter((c) => c.status === "running" || c.status === "queued" || c.queued).length;
  const completed = chs.filter((c) => c.is_completed).length;
  const unfinishedIdle = chs.filter((c) => !c.is_completed && c.status !== "running" && c.status !== "queued").length;
  const visible = statusFilter === "all" ? chs : chs.filter((c) => filterStatusOf(c) === statusFilter);
  useEffect(() => { setPage(1); }, [statusFilter, project.id]);
  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize) || 1);
  const curPage = Math.min(page, pageCount);
  const paged = pageItems(visible, curPage, pageSize);
  const selectedCount = selectedIds.length;
  const allSelected = paged.length > 0 && paged.every((c) => selectedIds.includes(c.subproject_id));
  const toggleSelected = (id: string) => {
    setSelectedIds((ids) => ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);
  };
  const toggleAll = () => setSelectedIds(
    allSelected
      ? selectedIds.filter((id) => !paged.some((c) => c.subproject_id === id))
      : Array.from(new Set([...selectedIds, ...paged.map((c) => c.subproject_id)])),
  );

  const doImport = async () => {
    setBusy("import"); setErr("");
    try { await api.bmImport(project.id); await load(); }
    catch (e: any) { setErr(e.message || tr("bench.importFailed")); }
    finally { setBusy(""); }
  };
  const startAll = async () => {
    setBusy("start"); setErr("");
    try {
      await api.startAll(project.id, false);
      await load();
    } catch (e: any) { setErr(e.message || tr("cluster.batchStartFailed")); }
    finally { setBusy(""); }
  };

  const startUnfinished = async () => {
    const idle = chs.filter((c) => !c.is_completed && c.status !== "running");
    if (!idle.length) {
      setErr(chs.length > 0 && completed === chs.length
        ? (labSrc ? tr("bench.noUnfinishedAssets") : tr("bench.allCleared"))
        : (labSrc ? tr("bench.noUnfinishedAssetsBusy") : tr("bench.noUnfinishedChallenges")));
      return;
    }
    const tip = labSrc
      ? tr("bench.confirmUnfinishedSrc")
      : tr("bench.confirmUnfinishedCtf", { n: completed });
    if (!window.confirm(tip)) return;
    setBusy("unfinished");
    setErr("");
    try {
      const res = await api.startAll(project.id, false, true);
      if (!res?.unfinished_only && !res?.scheduled) {
        for (let i = 0; i < idle.length; i++) {
          await api.start(idle[i].subproject_id, false);
          if (i < idle.length - 1) await new Promise((r) => setTimeout(r, 800));
        }
      }
      await load();
    } catch (e: any) { setErr(e.message || tr("bench.startUnfinishedFailed")); }
    finally { setBusy(""); }
  };

  const stopAll = async () => {
    if (!liveCount) return;
    if (!window.confirm(tr("bench.confirmStopAll", { n: liveCount, noun: labSrc ? tr("bench.nounAsset") : tr("bench.nounChallenge") }))) return;
    setBusy("stop"); setErr("");
    try { await api.stopAll(project.id); await load(); }
    catch (e: any) { setErr(formatApiError(e, tr("cluster.batchStopFailed"))); }
    finally { setBusy(""); }
  };

  const runSelected = async () => {
    if (!selectedCount || !window.confirm(tr("bench.confirmRunSel", { n: selectedCount }))) return;
    setBusy("sel-start"); setErr("");
    try { await api.batchStartProjects(selectedIds); setSelectedIds([]); await load(); }
    catch (e: any) { setErr(e.message || tr("cluster.runFailed")); }
    finally { setBusy(""); }
  };
  const pauseSelected = async () => {
    if (!selectedCount || !window.confirm(tr("bench.confirmPauseSel", { n: selectedCount }))) return;
    setBusy("sel-stop"); setErr("");
    try { await api.batchStopProjects(selectedIds); setSelectedIds([]); await load(); }
    catch (e: any) { setErr(formatApiError(e, tr("cluster.batchStopFailed"))); }
    finally { setBusy(""); }
  };
  const deleteSelected = async () => {
    if (!selectedCount || !window.confirm(tr("bench.confirmDeleteSel", { n: selectedCount }))) return;
    setBusy("sel-del"); setErr("");
    try { await api.batchDeleteProjects(selectedIds); setSelectedIds([]); await load(); }
    catch (e: any) { setErr(e.message || tr("cluster.deleteFailed")); }
    finally { setBusy(""); }
  };

  return (
    <div className="container" style={{ paddingTop: 24, paddingBottom: 40 }}>
      <Link to="/" className="muted" style={{ fontSize: 13 }}>&larr; {tr("project.backList")}</Link>
      <div className="spread" style={{ margin: "10px 0 18px", alignItems: "flex-start" }}>
        <div>
          <div className="row" style={{ gap: 10 }}>
            <h1 style={{ fontSize: 34 }}>{project.name}</h1>
            <Badge>{labSrc ? tr("projects.srcCluster") : tr("projects.ctfBench")}</Badge>
            <Badge coral>{labSrc ? tr("bench.srcMenu") : tr("bench.flagTrack")}</Badge>
          </div>
          <div className="row" style={{ gap: 12, marginTop: 6 }}>
            <span className="mono muted" style={{ fontSize: 13 }}>{bm.base_url || tr("bench.noBaseUrl")}</span>
            <span className="muted" style={{ fontSize: 13 }}>{tr("bench.meta", { kind: labSrc ? tr("bench.colAsset") : tr("bench.colChallenge"), n: chs.length, done: completed, run: runningCount, cap: slotLimit })}{queuedCount ? tr("cluster.queued", { n: queuedCount }) : ""}</span>
          </div>
        </div>
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <ReportExportControls projectId={project.id} disabled={!!busy} />
          <button className="btn btn-secondary" disabled={!!busy} onClick={doImport}>{busy === "import" ? tr("bench.importing") : tr("bench.import")}</button>
          {chs.length > 0 && (
            <button
              className="btn btn-primary"
              disabled={!!busy || envClosed || unfinishedIdle === 0}
              onClick={startUnfinished}
              title={envClosed ? tr("bench.envExpired") : undefined}
            >
              {busy === "unfinished" ? tr("bench.starting") : unfinishedIdle > 0 ? tr("bench.startUnfinishedN", { n: unfinishedIdle }) : tr("bench.startUnfinished")}
            </button>
          )}
          {chs.length > 0 && <button className="btn btn-ghost" disabled={!!busy || envClosed} onClick={startAll} title={envClosed ? tr("bench.envExpired") : undefined}>{busy === "start" ? tr("bench.starting") : tr("cluster.startAll")}</button>}
          {chs.length > 0 && (
            <button className="btn btn-secondary" disabled={!!busy || liveCount === 0} onClick={stopAll}>
              {busy === "stop" ? tr("bench.pausing") : tr("cluster.stopAll")}
            </button>
          )}
        </div>
      </div>

      {err && <div style={{ color: "var(--error)", marginBottom: 12, fontSize: 14 }}>{err}</div>}
      {envClosed && (
        <div className="import-progress is-error" style={{ marginBottom: 16 }}>
          <div className="import-progress-head">
            <strong>{tr("bench.envClosedTitle")}</strong>
            <span className="muted">{String((project.config as any)?.env_closed_reason || tr("bench.envClosedDefault"))}</span>
          </div>
          <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>{tr("bench.envClosedHint")}</p>
        </div>
      )}

      {labSrc ? (
        <div className="card-cream" style={{ marginBottom: 20, padding: 18 }}>
          <div className="row" style={{ gap: 28, alignItems: "baseline" }}>
            <div className="stack"><span className="serif" style={{ fontSize: 34, color: colors.primary }}>{chs.length}</span><span className="muted" style={{ fontSize: 12 }}>{tr("bench.srcAssets")}</span></div>
            <div className="stack"><span className="serif" style={{ fontSize: 28 }}>{completed}/{chs.length}</span><span className="muted" style={{ fontSize: 12 }}>{tr("projects.statusCompleted")}</span></div>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>{tr("bench.srcHint")}</p>
        </div>
      ) : (
        <div className="card-cream" style={{ marginBottom: 20, padding: 18 }}>
          <div className="row" style={{ gap: 28, alignItems: "baseline" }}>
            <div className="stack"><span className="serif" style={{ fontSize: 34, color: colors.primary }}>{board?.cumulative_score ?? 0}</span><span className="muted" style={{ fontSize: 12 }}>{tr("bench.score")}</span></div>
            <div className="stack"><span className="serif" style={{ fontSize: 28 }}>{board?.correct_flags ?? 0}/{board?.total_flags ?? 0}</span><span className="muted" style={{ fontSize: 12 }}>{tr("bench.flags")}</span></div>
            <div className="stack"><span className="serif" style={{ fontSize: 28 }}>{completed}/{chs.length}</span><span className="muted" style={{ fontSize: 12 }}>{tr("bench.cleared")}</span></div>
          </div>
        </div>
      )}

      <h3 style={{ marginBottom: 12 }}>{labSrc ? tr("bench.listSrc") : tr("bench.listCtf")}</h3>
      {chs.length > 0 && (
        <div className="status-filters">
          {STATUS_FILTER_KEYS.map((key) => (
            <button key={key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>
              {statusFilterText(key)} <b>{key === "all" ? chs.length : chs.filter((c) => filterStatusOf(c) === key).length}</b>
            </button>
          ))}
        </div>
      )}
      <BatchSelectionBar
        count={selectedCount}
        noun={tr("bench.nounChallenges")}
        busy={!!busy}
        onRun={runSelected}
        onPause={pauseSelected}
        onDelete={deleteSelected}
        onClear={() => setSelectedIds([])}
      />
      {chs.length === 0 ? (
        <div className="card-cream" style={{ textAlign: "center", padding: 48 }}>
          <p className="muted">{labSrc ? tr("bench.emptySrc") : tr("bench.emptyCtf")}</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="empty-list">{tr("bench.emptyFilter")}</div>
      ) : (
        <ChallengesTable
          challenges={paged}
          selectedIds={selectedIds}
          allSelected={allSelected}
          onToggle={toggleSelected}
          onToggleAll={toggleAll}
          labSrc={labSrc}
        />
      )}
      {visible.length > 0 && (
        <PaginationBar
          total={visible.length}
          page={curPage}
          pageSize={pageSize}
          onPage={setPage}
          onPageSize={setPageSize}
        />
      )}
    </div>
  );
}

function ChallengesTable({
  challenges, selectedIds, allSelected, onToggle, onToggleAll, labSrc = false,
}: {
  challenges: Board["challenges"];
  selectedIds: string[];
  allSelected: boolean;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  labSrc?: boolean;
}) {
  const { t: tr } = useT();
  const nav = useNavigate();
  return (
    <div className="project-table-wrap">
      <table className="project-table">
        <thead><tr><th><input type="checkbox" checked={allSelected} onChange={onToggleAll} aria-label={tr("bench.selectAll")} /></th><th>{tr("cluster.colStatus")}</th><th>{labSrc ? tr("bench.colAsset") : tr("bench.colChallenge")}</th><th>{tr("bench.colDiff")}</th>{labSrc ? null : <><th>{tr("bench.colFlag")}</th><th>{tr("bench.colScore")}</th><th>{tr("bench.colPct")}</th></>}<th>{tr("bench.colAttack")}</th></tr></thead>
        <tbody>
          {challenges.map((c) => {
            const pct = c.flag_count ? Math.round((c.correct_flag_count / c.flag_count) * 100) : 0;
            const flagCell = `${c.correct_flag_count}/${c.flag_count || 1}${c.total_score ? ` · ${c.score}/${c.total_score}` : c.score ? ` · ${c.score}` : ""}`;
            return (
              <tr key={c.subproject_id} className={selectedIds.includes(c.subproject_id) ? "selected" : ""} onClick={() => nav(`/project/${c.subproject_id}`)}>
                <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(c.subproject_id)} onChange={() => onToggle(c.subproject_id)} aria-label={tr("cluster.selectOne", { name: c.unique_code || c.name })} /></td>
                <td><span className="row" style={{ gap: 7 }}><span className="pulse-dot" style={{ background: statusColor[c.status] || colors.muted }} />{statusText(c.status) || c.status}</span></td>
                <td><b>{c.unique_code || c.name}</b></td>
                <td>{c.difficulty || "—"}</td>
                {labSrc ? null : <><td>{flagCell}</td><td>{c.score}{c.total_score ? ` / ${c.total_score}` : ""}</td><td>{pct}%</td></>}
                <td>{c.is_completed ? <Badge coral>{tr("status.completed")}</Badge> : c.lateral_active ? <span className="badge">{tr("cluster.lateral")}</span> : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
