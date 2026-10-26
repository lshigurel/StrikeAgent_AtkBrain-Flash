import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatApiError } from "../../api";
import type { Project } from "../../types";
import { Badge } from "../../components/Badge";
import { BatchSelectionBar } from "../../components/BatchSelectionBar";
import { ImportProgressBar, isImportPaused, isImportRunning, type ImportProgress } from "../../components/ImportProgressBar";
import { PaginationBar, pageItems, readPageSize } from "../../components/PaginationBar";
import { colors } from "../../theme";
import { huntFailedReason, listStatusOf } from "../../projectStatus";
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
    goal_reached: t("status.completed"),
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

/** 展示态：排队（等并发槽）优先于笼统的 running */
function displayStatus(p: Project): string {
  if (p.queued) return "queued";
  if (p.running) return "running";
  if (huntFailedReason(p)) return "error";
  return p.status || "idle";
}

/** 筛选桶：与项目列表同一套 */
function filterStatusOf(p: Project): string {
  return listStatusOf(p);
}

function vhostsOf(p: Project): string[] {
  const fromCfg = Array.isArray(p.config?.vhosts) ? p.config.vhosts : [];
  const fromScope = Array.isArray(p.scope?.targets) ? p.scope.targets : [];
  const raw = (fromCfg.length ? fromCfg : fromScope).map((x: unknown) => String(x || "").trim()).filter(Boolean);
  const primary = String(p.target || "").toLowerCase().replace(/\.$/, "");
  const seen = new Set<string>();
  const out: string[] = [];
  for (const h of raw) {
    const k = h.toLowerCase().replace(/\.$/, "");
    if (!k || k === primary || seen.has(k)) continue;
    seen.add(k);
    out.push(h);
  }
  return out;
}

export function ClusterDashboard({
  project,
  onProjectUpdate,
}: {
  project: Project;
  onProjectUpdate?: (p: Project) => void;
}) {
  const { t: tr } = useT();
  const [subs, setSubs] = useState<Project[]>([]);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importProgress, setImportProgress] = useState<ImportProgress | null>(
    () => (project.config?.import_progress as ImportProgress) || null,
  );
  const [summary, setSummary] = useState<any>(null);
  const [err, setErr] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newAssets, setNewAssets] = useState("");
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(project.name);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(readPageSize);
  const importPoll = useRef<ReturnType<typeof setTimeout> | null>(null);

  const assets: string[] = project.config?.assets || project.scope?.targets || [];
  const rawTrack = String(project.config?.track || project.config?.objective || "").toLowerCase();
  const clusterTrack = rawTrack === "ctf" || rawTrack === "flag" ? "ctf" : "agent";

  const load = () => api.subprojects(project.id).then(setSubs).catch(() => {});
  useEffect(() => {
    load();
    const tmr = setInterval(load, importing ? 1500 : 8000);
    return () => clearInterval(tmr);
  }, [project.id, importing]);
  useEffect(() => {
    if (!editingName) setNameDraft(project.name);
  }, [project.name, editingName]);

  const pollImport = async () => {
    try {
      const p = await api.importProgress(project.id) as ImportProgress;
      setImportProgress(p);
      const running = isImportRunning(p);
      setImporting(running);
      if (running) {
        importPoll.current = setTimeout(pollImport, 400);
      } else if ((p.phase === "done" || p.phase === "error") && p.total) {
        await load();
        if (p.phase === "done") {
          setSummary((prev: any) => ({
            assets: assets.length,
            hosts: p.total,
            subprojects_created: p.created ?? prev?.subprojects_created,
            started: p.started ?? prev?.started,
          }));
          window.setTimeout(() => setImportProgress((cur) => (cur?.phase === "done" ? null : cur)), 2500);
        }
        if (p.phase === "error") setErr(p.message || tr("projects.importFailed"));
      } else if (isImportPaused(p)) {
        await load();
      }
    } catch {
      setImporting((was) => {
        if (was) importPoll.current = setTimeout(pollImport, 1200);
        return was;
      });
    }
  };

  useEffect(() => {
    pollImport();
    return () => { if (importPoll.current) clearTimeout(importPoll.current); };
  }, [project.id]);

  const saveName = async () => {
    const next = nameDraft.trim();
    if (!next) {
      setErr(tr("projects.nameRequired"));
      return;
    }
    if (next === project.name) {
      setEditingName(false);
      return;
    }
    setBusy(true); setErr("");
    try {
      const p = await api.renameProject(project.id, next);
      onProjectUpdate?.(p);
      setEditingName(false);
      await load();
    } catch (e: any) {
      setErr(e.message || tr("projects.renameFailed"));
    } finally {
      setBusy(false);
    }
  };

  /** 可选：重新探测存活（非主路径；创建时已按 host 直建并启动） */
  const triage = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.triage(project.id);
      setSummary(r);
      await load();
    } catch (e: any) {
      setErr(e.message || tr("cluster.probeFailed"));
    } finally { setBusy(false); }
  };

  const refold = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.refoldMachines(project.id);
      setSummary({
        ...r,
        message: tr("cluster.foldOk", { g: r.merged_groups || 0, d: r.deleted || 0 })
          + (r.skipped_running ? tr("cluster.foldSkip", { n: r.skipped_running }) : ""),
      });
      await load();
    } catch (e: any) {
      setErr(e.message || tr("cluster.foldFailed"));
    } finally { setBusy(false); }
  };

  const startAll = async () => {
    setBusy(true); setErr("");
    try { await api.startAll(project.id); await load(); }
    catch (e: any) { setErr(formatApiError(e, tr("cluster.batchStartFailed"))); }
    finally { setBusy(false); }
  };

  const stopAll = async () => {
    setBusy(true); setErr("");
    try { await api.stopAll(project.id); await load(); }
    catch (e: any) { setErr(formatApiError(e, tr("cluster.batchStopFailed"))); }
    finally { setBusy(false); }
  };

  const pauseImport = async () => {
    setBusy(true); setErr("");
    try {
      const p = await api.pauseImport(project.id) as ImportProgress;
      setImportProgress(p);
      if (isImportRunning(p)) {
        if (importPoll.current) clearTimeout(importPoll.current);
        importPoll.current = setTimeout(pollImport, 200);
      } else {
        setImporting(false);
        await load();
      }
    } catch (e: any) {
      setErr(e.message || tr("projects.pauseImportFailed"));
    } finally {
      setBusy(false);
    }
  };

  const resumeImport = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.resumeImport(project.id);
      const p = (r.import_progress || r) as ImportProgress;
      setImportProgress(p);
      setImporting(true);
      if (importPoll.current) clearTimeout(importPoll.current);
      importPoll.current = setTimeout(pollImport, 200);
    } catch (e: any) {
      setErr(e.message || tr("projects.resumeImportFailed"));
    } finally {
      setBusy(false);
    }
  };

  const addAssets = async () => {
    const blob = newAssets.trim();
    if (!blob) {
      setErr(tr("cluster.needAssets"));
      return;
    }
    const lineHint = blob.split(/\r?\n/).filter((s) => s.trim()).length;
    setBusy(true); setErr("");
    setImporting(true);
    setImportProgress({
      phase: "merge", done: 0, total: lineHint,
      message: clusterTrack === "agent" ? tr("projects.mergingZone") : tr("projects.mergingHost"),
    });
    try {
      const r = await api.addClusterAssets(project.id, [blob], true);
      if (r.project && onProjectUpdate) onProjectUpdate(r.project);
      const skipN = r.skipped_dup_count ?? (r.skipped_dup || []).length;
      setSummary({
        assets: r.assets_total,
        hosts: r.pending_hosts ?? (r.added || []).length,
        subprojects_created: r.pending_hosts ?? r.subprojects_created,
        started: 0,
        added: (r.added || []).length,
        skipped: skipN,
        skippedUrls: r.skipped_dup_urls,
        rejected: (r.rejected || []).length,
        message: r.message,
      });
      setNewAssets("");
      if (r.rejected?.length) {
        setErr(tr("cluster.rejected", { list: r.rejected.map((x: any) => x.asset).join(", ") }));
      }
      if (!r.importing) {
        setImporting(false);
        setImportProgress(null);
        await load();
      } else {
        setImportProgress(r.import_progress || r);
        if (importPoll.current) clearTimeout(importPoll.current);
        importPoll.current = setTimeout(pollImport, 200);
      }
    } catch (e: any) {
      setErr(e.message || tr("cluster.addFailed"));
      setImporting(false);
      setImportProgress(null);
    } finally {
      setBusy(false);
    }
  };

  const onPickAssetFile = async (file?: File | null) => {
    if (!file) return;
    const text = await file.text();
    setNewAssets((prev) => (prev ? `${prev.trim()}\n${text}` : text));
  };

  const runningCount = subs.filter((s) => s.running && !s.queued).length;
  const queuedCount = subs.filter((s) => s.queued).length;
  const visible = statusFilter === "all" ? subs : subs.filter((p) => filterStatusOf(p) === statusFilter);
  useEffect(() => { setPage(1); }, [statusFilter, project.id]);
  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize) || 1);
  const curPage = Math.min(page, pageCount);
  const paged = pageItems(visible, curPage, pageSize);
  const selectedCount = selectedIds.length;
  const allSelected = paged.length > 0 && paged.every((s) => selectedIds.includes(s.id));
  const toggleSelected = (id: string) => {
    setSelectedIds((ids) => ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);
  };
  const toggleAll = () => setSelectedIds(allSelected ? selectedIds.filter((id) => !paged.some((s) => s.id === id)) : Array.from(new Set([...selectedIds, ...paged.map((s) => s.id)])));
  const runSelected = async () => {
    if (!selectedCount || !window.confirm(tr("cluster.confirmRun", { n: selectedCount }))) return;
    setBusy(true); setErr("");
    try { await api.batchStartProjects(selectedIds); setSelectedIds([]); await load(); }
    catch (e: any) { setErr(formatApiError(e, tr("cluster.runFailed"))); }
    finally { setBusy(false); }
  };
  const pauseSelected = async () => {
    if (!selectedCount || !window.confirm(tr("cluster.confirmPause", { n: selectedCount }))) return;
    setBusy(true); setErr("");
    try { await api.batchStopProjects(selectedIds); setSelectedIds([]); await load(); }
    catch (e: any) { setErr(formatApiError(e, tr("cluster.batchStopFailed"))); }
    finally { setBusy(false); }
  };
  const deleteSelected = async () => {
    if (!selectedCount || !window.confirm(tr("cluster.confirmDelete", { n: selectedCount }))) return;
    setBusy(true); setErr("");
    try { await api.batchDeleteProjects(selectedIds); setSelectedIds([]); await load(); }
    catch (e: any) { setErr(e.message || tr("cluster.deleteFailed")); }
    finally { setBusy(false); }
  };

  return (
    <div className="container" style={{ paddingTop: 24, paddingBottom: 40 }}>
      <Link to="/" className="muted" style={{ fontSize: 13 }}>&larr; {tr("project.backList")}</Link>
      <div className="spread" style={{ margin: "10px 0 18px", alignItems: "flex-start" }}>
        <div>
          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {editingName ? (
              <>
                <input
                  className="input"
                  value={nameDraft}
                  autoFocus
                  disabled={busy}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveName();
                    if (e.key === "Escape") { setEditingName(false); setNameDraft(project.name); }
                  }}
                  style={{ fontSize: 22, fontWeight: 600, maxWidth: 360 }}
                />
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={saveName}>{tr("common.save")}</button>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={busy}
                  onClick={() => { setEditingName(false); setNameDraft(project.name); }}
                >
                  {tr("common.cancel")}
                </button>
              </>
            ) : (
              <>
                <h1 style={{ fontSize: 34 }}>{project.name}</h1>
                <Badge>{tr("projects.cluster")}</Badge>
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => { setNameDraft(project.name); setEditingName(true); setErr(""); }}
                  title={tr("cluster.renameTitle")}
                >
                  {tr("common.rename")}
                </button>
              </>
            )}
          </div>
          <div className="row" style={{ gap: 12, marginTop: 6 }}>
            <span className="muted" style={{ fontSize: 13 }}>
              {tr("cluster.assets", { a: assets.length, s: subs.length, r: runningCount })}
              {queuedCount > 0 ? tr("cluster.queued", { n: queuedCount }) : ""}
            </span>
          </div>
        </div>
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <ReportExportControls projectId={project.id} disabled={busy} />
          <button className="btn btn-primary" disabled={busy} onClick={() => { setShowAdd((v) => !v); setErr(""); }}>
            {showAdd ? tr("common.cancel") : tr("cluster.add")}
          </button>
          <button className="btn btn-primary" disabled={busy || subs.length === 0} onClick={startAll}>
            {busy ? tr("common.processing") : tr("cluster.startAll")}
          </button>
          <button className="btn btn-secondary" disabled={busy || runningCount === 0} onClick={stopAll}>
            {tr("cluster.stopAll")}
          </button>
          <button className="btn btn-secondary" disabled={busy} onClick={triage} title={tr("cluster.retriageTitle")}>
            {tr("cluster.retriage")}
          </button>
          <button
            className="btn btn-secondary"
            disabled={busy || subs.length === 0}
            onClick={refold}
            title={tr("cluster.foldTitle")}
          >
            {tr("cluster.fold")}
          </button>
        </div>
      </div>

      <ImportProgressBar
        progress={importProgress}
        title={isImportPaused(importProgress) ? tr("cluster.importPaused") : (isImportRunning(importProgress) ? tr("cluster.importing") : undefined)}
        onPause={pauseImport}
        onResume={resumeImport}
        busy={busy}
      />

      {showAdd && (
        <div className="card-cream" style={{ marginBottom: 20, padding: 18 }}>
          <h3 style={{ marginBottom: 8, fontSize: 16 }}>{tr("cluster.addTitle")}</h3>
          <p className="muted" style={{ fontSize: 13, marginBottom: 10 }}>
            {clusterTrack === "agent" ? tr("cluster.addSrc") : tr("cluster.addRed")}
          </p>
          <div className="row" style={{ gap: 10, marginBottom: 10, flexWrap: "wrap", alignItems: "center" }}>
            <label className="btn btn-secondary btn-sm" style={{ cursor: busy || importing ? "not-allowed" : "pointer" }}>
              {tr("cluster.pickFile")}
              <input
                type="file"
                accept=".txt,.csv,.list,text/plain"
                hidden
                disabled={busy || importing}
                onChange={(e) => { onPickAssetFile(e.target.files?.[0]); e.target.value = ""; }}
              />
            </label>
            <span className="muted" style={{ fontSize: 12 }}>{tr("cluster.fileHint")}</span>
          </div>
          <textarea
            className="input"
            rows={4}
            value={newAssets}
            onChange={(e) => setNewAssets(e.target.value)}
            placeholder={"https://example.com\nother.target.com\n10.0.0.8:8080"}
            disabled={busy || importing}
            style={{ width: "100%", marginBottom: 12 }}
          />
          <div className="row" style={{ gap: 10 }}>
            <button className="btn btn-primary" disabled={busy || importing} onClick={addAssets}>
              {busy || importing ? tr("projects.importingBtn") : tr("cluster.confirmAdd")}
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={() => { setShowAdd(false); setNewAssets(""); }}>
              {tr("common.cancel")}
            </button>
          </div>
        </div>
      )}

      {err && <div style={{ color: "var(--error)", marginBottom: 12, fontSize: 14 }}>{err}</div>}

      {summary && (
        <div className="card-cream" style={{ marginBottom: 20, padding: 18 }}>
          <div className="row" style={{ gap: 22, fontSize: 14, flexWrap: "wrap" }}>
            {summary.added != null && <span>{tr("cluster.added")} <b style={{ color: colors.success }}>{summary.added}</b></span>}
            {summary.skipped != null && (
              <span>
                {tr("cluster.skipped")} <b>{summary.skipped}</b>
                {summary.skippedUrls != null ? tr("cluster.skippedUrls", { n: summary.skippedUrls }) : ""}
              </span>
            )}
            {summary.rejected != null && summary.rejected > 0 && <span>{tr("cluster.rejectedN")} <b style={{ color: colors.error }}>{summary.rejected}</b></span>}
            <span>{tr("cluster.statAssets")} <b>{summary.assets}</b></span>
            <span>{tr("cluster.willCreate")} <b style={{ color: colors.primary }}>{summary.hosts}</b></span>
            {summary.live_hosts != null && <span>{tr("cluster.liveHosts")} <b style={{ color: colors.success }}>{summary.live_hosts}</b></span>}
            {summary.live_endpoints != null && <span>{tr("cluster.liveEps")} <b>{summary.live_endpoints}</b></span>}
            {summary.subprojects_created > 0 && <span>{tr("cluster.createdN")} <b style={{ color: colors.primary }}>{summary.subprojects_created}</b></span>}
            {summary.started != null && <span>{tr("cluster.startedN")} <b>{summary.started}</b></span>}
          </div>
          {summary.message && <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>{summary.message}</p>}
        </div>
      )}

      <h3 style={{ marginBottom: 12 }}>{tr("cluster.children")}</h3>
      <div className="status-filters">
        {STATUS_FILTER_KEYS.map((key) => (
          <button key={key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>
            {statusFilterText(key)} <b>{key === "all" ? subs.length : subs.filter((p) => filterStatusOf(p) === key).length}</b>
          </button>
        ))}
      </div>
      <BatchSelectionBar
        count={selectedCount}
        busy={busy}
        onRun={runSelected}
        onPause={pauseSelected}
        onDelete={deleteSelected}
        onClear={() => setSelectedIds([])}
      />
      {subs.length === 0 ? (
        <div className="card-cream" style={{ textAlign: "center", padding: 48 }}>
          <p className="muted">{tr("cluster.noChildren")}</p>
          <div className="mono muted" style={{ fontSize: 12, marginTop: 12, whiteSpace: "pre-wrap" }}>{assets.join("  ") || tr("cluster.noAssets")}</div>
        </div>
      ) : visible.length === 0 ? (
        <div className="empty-list">{tr("cluster.emptyFilter")}</div>
      ) : (
        <SubprojectsTable
          projects={paged}
          selectedIds={selectedIds}
          allSelected={allSelected}
          onToggle={toggleSelected}
          onToggleAll={toggleAll}
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

function SubprojectsTable({
  projects, selectedIds, allSelected, onToggle, onToggleAll,
}: {
  projects: Project[];
  selectedIds: string[];
  allSelected: boolean;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
}) {
  const { t: tr } = useT();
  const nav = useNavigate();
  return (
    <div className="project-table-wrap">
      <table className="project-table">
        <thead><tr><th><input type="checkbox" checked={allSelected} onChange={onToggleAll} aria-label={tr("cluster.selectAll")} /></th><th>{tr("cluster.colStatus")}</th><th>{tr("cluster.colTarget")}</th><th>{tr("cluster.colHost")}</th><th>{tr("cluster.colPorts")}</th><th>{tr("projects.colNodes")}</th><th>{tr("projects.colServices")}</th><th>{tr("projects.colHigh")}</th><th>{tr("projects.colCritical")}</th><th>{tr("cluster.colAttack")}</th></tr></thead>
        <tbody>
          {projects.map((p) => {
            const s = p.stats;
            const aliases = vhostsOf(p);
            return (
              <tr key={p.id} className={selectedIds.includes(p.id) ? "selected" : ""} onClick={() => nav(`/project/${p.id}`)}>
                <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(p.id)} onChange={() => onToggle(p.id)} aria-label={tr("cluster.selectOne", { name: p.target || p.name })} /></td>
                <td>
                  <span className="row" style={{ gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="pulse-dot" style={{ background: statusColor[displayStatus(p)] || colors.muted }} />
                    {statusText(displayStatus(p)) || p.status}
                    {p.queued ? <span className="badge" style={{ background: "rgba(217,190,132,0.16)", color: "#d9be84", borderColor: "rgba(217,190,132,0.35)" }} title={tr("status.waitingSlotTitle")}>{tr("status.waitingSlot")}</span> : null}
                    {!p.running && p.config?.completion_reason === "entry_dead" ? <span className="badge" style={{ background: "rgba(217,190,132,0.16)", color: "#d9be84", borderColor: "rgba(217,190,132,0.35)" }} title={tr("status.entryDeadTitle")}>{tr("status.entryDead")}</span> : null}
                    {!p.running && (p.config?.completion_reason === "env_closed" || p.config?.completion_reason === "env_unreachable" || p.config?.env_closed) ? <span className="badge" style={{ background: "rgba(198,69,69,.12)", color: "#c64545", borderColor: "rgba(198,69,69,.35)" }} title={tr("cluster.envClosedShort")}>{tr("status.envClosed")}</span> : null}
                  </span>
                </td>
                <td>
                  <b>{p.target || p.name}</b>
                  {aliases.length > 0 ? (
                    <div className="muted" style={{ fontSize: 12, marginTop: 2 }} title={aliases.join(", ")}>
                      {tr("cluster.aliases", { n: aliases.length + 1 })}
                    </div>
                  ) : null}
                </td>
                <td className="mono" title={aliases.join(", ") || undefined}>{aliases.length ? aliases.length : "—"}</td>
                <td className="mono">{(p.ports || []).join(", ") || tr("cluster.allPorts")}</td>
                <td>{s?.nodes ?? 0}</td><td>{s?.services ?? 0}</td>
                <td className={(s?.high ?? 0) > 0 ? "danger-number" : ""}>{s?.high ?? 0}</td>
                <td className={(s?.critical ?? 0) > 0 ? "danger-number" : ""}>{s?.critical ?? 0}</td>
                <td>{s?.has_shell ? <Badge coral>GETSHELL</Badge> : s?.lateral_active ? <span className="badge">{tr("cluster.lateral")}</span> : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
