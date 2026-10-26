import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Finding } from "../types";
import { SeverityBadge, SecondaryVerifyBadge, RedteamRatingBadge } from "../components/Badge";
import { PaginationBar, readPageSize } from "../components/PaginationBar";
import { FindingReportModal } from "../features/findings/FindingReportModal";
import { colors, displayFindingSeverity, scrubCandidateRceLabel } from "../theme";
import { countUp } from "../anim";
import { useT } from "../i18n";

type ReviewLive = {
  status?: string;
  started_at?: number;
  updated_at?: number;
  detail?: string;
};

type LibFinding = Finding & {
  project_id: string;
  project_name?: string;
  project_target?: string;
  project_kind?: string;
  project_track?: string;
  parent_id?: string;
  parent_name?: string;
  parent_kind?: string;
  reviewing_secondary?: boolean;
  reviewing_rating?: boolean;
  review_secondary?: ReviewLive | null;
  review_rating?: ReviewLive | null;
  disposition?: string | null;
  retest_conclusion?: string | null;
};

function dur(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}秒`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}分${r}秒` : `${m}分`;
}

function reviewLine(row: ReviewLive | null | undefined, t: (key: string, vars?: Record<string, string | number>) => string): string {
  if (!row?.status) return "";
  if (row.status === "queued") return t("vulns.queuedDetail");
  if (row.status === "dead") return row.detail || t("vulns.deadDetail");
  const now = Date.now() / 1000;
  const started = Number(row.started_at || now);
  const clock = dur(now - started);
  return t("vulns.liveDetail", { clock, detail: (row.detail || "").trim() || t("vulns.waitingModel") });
}

type Counts = { total: number; critical: number; high: number; medium: number; low: number; info: number };
type TrackCounts = { all: number; agent: number; redteam: number; ctf: number; src: number };

const EMPTY_COUNTS: Counts = { total: 0, critical: 0, high: 0, medium: 0, low: 0, info: 0 };
const EMPTY_TRACKS: TrackCounts = { all: 0, agent: 0, redteam: 0, ctf: 0, src: 0 };
const TRACK_KEYS = ["all", "agent", "ctf"] as const;

const BAR: { key: keyof Counts; color: string }[] = [
  { key: "critical", color: "var(--sev-critical)" },
  { key: "high", color: "var(--sev-high)" },
  { key: "medium", color: "var(--sev-medium)" },
  { key: "low", color: "var(--sev-low)" },
];

export function VulnsPage() {
  const { t } = useT();
  const [q, setQ] = useState("");
  const [project, setProject] = useState("");
  const [category, setCategory] = useState("");
  const [track, setTrack] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(readPageSize);
  const [items, setItems] = useState<LibFinding[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Counts>(EMPTY_COUNTS);
  const [trackCounts, setTrackCounts] = useState<TrackCounts>(EMPTY_TRACKS);
  const [categories, setCategories] = useState<string[]>([]);
  const [open, setOpen] = useState<LibFinding | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = () => {
    api.listFindings({ q, project, category, track: track === "all" ? "" : track, page, page_size: pageSize })
      .then((r) => {
        setItems(Array.isArray(r?.items) ? r.items : []);
        setTotal(Number(r?.total || 0));
        setCounts({ ...EMPTY_COUNTS, ...(r?.counts || {}) });
        setTrackCounts({ ...EMPTY_TRACKS, ...(r?.track_counts || {}) });
        setCategories(Array.isArray(r?.categories) ? r.categories : []);
      })
      .catch(() => {});
  };

  useEffect(() => { setPage(1); }, [q, project, category, track, pageSize]);
  useEffect(() => {
    load();
    const tmr = setInterval(load, 4000);
    return () => clearInterval(tmr);
  }, [q, project, category, track, page, pageSize]);

  const [retestNote, setRetestNote] = useState("");
  const retest = async (f: LibFinding) => {
    setErr("");
    setRetestNote("");
    try {
      const r = await api.retestFinding(f.project_id, f.id);
      setRetestNote(r.label || r.conclusion);
      load();
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  };

  const startReview = async (f: LibFinding, mode: "secondary" | "rating") => {
    const key = `${f.project_id}:${f.id}:${mode}`;
    setErr("");
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      await api.reviewFinding(f.project_id, f.id, mode);
      load();
    } catch (e: any) {
      setErr(e?.status === 409 ? t("vulns.busy") : String(e?.message || e));
    } finally {
      setBusy((b) => {
        const n = { ...b };
        delete n[key];
        return n;
      });
    }
  };

  const barTotal = Math.max(1, counts.critical + counts.high + counts.medium + counts.low);

  return (
    <div className="page-container vulns-page">
      <header className="page-heading">
        <p className="eyebrow">VULNS</p>
        <h1>{t("vulns.title")}</h1>
        <p>{t("vulns.subtitle")}</p>
      </header>
      {err ? <p className="error-text">{err}</p> : null}
      {retestNote ? <p className="muted">{retestNote}</p> : null}

      <div className="project-head-stats" style={{ marginBottom: 18, justifyContent: "flex-start" }}>
        <Stat value={counts.total} label={t("vulns.kpiTotal")} />
        <Stat value={counts.critical} label={t("vulns.kpiCritical")} color={counts.critical ? "var(--sev-critical)" : undefined} />
        <Stat value={counts.high} label={t("vulns.kpiHigh")} color={counts.high ? "var(--sev-high)" : undefined} />
        <Stat value={counts.medium} label={t("vulns.kpiMedium")} color={counts.medium ? "var(--sev-medium)" : undefined} />
        <Stat value={counts.low} label={t("vulns.kpiLow")} color={counts.low ? "var(--sev-low)" : undefined} />
      </div>

      <section className="card-cream" style={{ marginBottom: 16 }}>
        <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>{t("vulns.dist")}</p>
        <div className="vuln-stack" role="img" aria-label={t("vulns.dist")}>
          {BAR.map(({ key, color }) => {
            const n = counts[key] || 0;
            if (!n) return null;
            return (
              <span
                key={key}
                className="vuln-stack-seg"
                style={{ width: `${(n / barTotal) * 100}%`, background: color }}
                title={`${key}: ${n}`}
              />
            );
          })}
        </div>
        <div className="vuln-legend">
          {BAR.map(({ key, color }) => (
            <span key={key} className="vuln-legend-item">
              <i style={{ background: color }} />
              {t(
                key === "critical" ? "vulns.kpiCritical"
                  : key === "high" ? "vulns.kpiHigh"
                    : key === "medium" ? "vulns.kpiMedium"
                      : "vulns.kpiLow",
              )} {counts[key] || 0}
            </span>
          ))}
        </div>
      </section>

      <section className="project-list-toolbar">
        <input className="input project-search" value={project} onChange={(e) => setProject(e.target.value)} placeholder={t("vulns.searchProject")} />
        <input className="input project-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("vulns.searchTitle")} />
        <select className="select compact-filter" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">{t("vulns.catAll")}</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </section>
      <div className="status-filters">
        {TRACK_KEYS.map((key) => (
          <button key={key} type="button" className={track === key ? "active" : ""} onClick={() => setTrack(key)}>
            {key === "all" ? t("vulns.trackAll") : key === "ctf" ? "CTF" : t("projects.trackAgent")}
            <b>{(key === "agent" ? (trackCounts.agent || (trackCounts.redteam || 0) + (trackCounts.src || 0)) : trackCounts[key]) || 0}</b>
          </button>
        ))}
      </div>

      <div className="project-table-wrap">
        <table className="project-table vulns-table">
          <thead>
            <tr>
              <th>{t("vulns.colProject")}</th>
              <th>{t("vulns.colTrack")}</th>
              <th>{t("vulns.colTitle")}</th>
              <th>{t("vulns.colType")}</th>
              <th>{t("vulns.colSev")}</th>
              <th>{t("vulns.colReview")}</th>
              <th>{t("vulns.colAct")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => {
              const secKey = `${f.project_id}:${f.id}:secondary`;
              const rateKey = `${f.project_id}:${f.id}:rating`;
              const sec = f.review_secondary;
              const rate = f.review_rating;
              const secHeld = !!busy[secKey] || !!sec;
              const rateHeld = !!busy[rateKey] || !!rate;
              return (
                <tr key={`${f.project_id}:${f.id}`}>
                  <td>
                    <Link to={`/project/${f.project_id}`} className="vuln-project-link" onClick={(e) => e.stopPropagation()}>
                      <strong>{f.project_name || f.project_id}</strong>
                    </Link>
                    {f.parent_id ? (
                      <span className="table-sub">
                        <Link to={`/project/${f.parent_id}`} className="vuln-project-link" onClick={(e) => e.stopPropagation()}>
                          {t("vulns.cluster")} · {f.parent_name || f.parent_id}
                        </Link>
                        {f.project_target ? ` · ${f.project_target}` : ""}
                      </span>
                    ) : (
                      <span className="table-sub mono">{f.project_target || ""}</span>
                    )}
                  </td>
                  <td>{f.project_track === "ctf" ? "CTF" : t("projects.trackAgent")}</td>
                  <td>
                    <button type="button" className="vuln-title-btn" onClick={() => setOpen(f)}>
                      {scrubCandidateRceLabel(f.title) || f.title}
                    </button>
                    <span className="table-sub mono">{f.id}</span>
                  </td>
                  <td className="mono">{f.category}</td>
                  <td><SeverityBadge severity={displayFindingSeverity(f)} /></td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                      {(f.verification_status || "").toLowerCase() === "excluded" ? (
                        <SecondaryVerifyBadge excluded />
                      ) : (
                        <SecondaryVerifyBadge done={!!f.secondary_verified} reviewing={sec?.status === "running" && !f.secondary_verified} />
                      )}
                      <RedteamRatingBadge rating={f.redteam_rating} score={f.cvss} reviewing={rate?.status === "running" && !f.redteam_rating} />
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                      <div className="stack" style={{ gap: 2, alignItems: "flex-start" }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={secHeld}
                          onClick={() => { void startReview(f, "secondary"); }}
                        >
                          {sec?.status === "running" ? t("vulns.running") : sec?.status === "queued" ? t("vulns.queued") : sec?.status === "dead" ? t("vulns.deadDetail") : t("vulns.secondary")}
                        </button>
                        {sec ? <span className="table-sub">{reviewLine(sec, t)}</span> : null}
                      </div>
                      <div className="stack" style={{ gap: 2, alignItems: "flex-start" }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={rateHeld}
                          onClick={() => { void startReview(f, "rating"); }}
                        >
                          {rate?.status === "running" ? t("vulns.running") : rate?.status === "queued" ? t("vulns.queued") : rate?.status === "dead" ? t("vulns.deadDetail") : t("vulns.rating")}
                        </button>
                        {rate ? <span className="table-sub">{reviewLine(rate, t)}</span> : null}
                      </div>
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => { void retest(f); }}>
                        {t("vulns.retest")}
                      </button>
                      {f.disposition === "fixed" ? <span className="table-sub">已修复</span> : f.retest_conclusion === "still_reproducible" ? <span className="table-sub">仍可复现</span> : f.retest_conclusion === "inconclusive" ? <span className="table-sub">无法确认</span> : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!items.length && <div className="empty-list">{t("vulns.empty")}</div>}
      </div>
      {total > 0 && (
        <PaginationBar total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
      )}
      {open ? (
        <FindingReportModal projectId={open.project_id} finding={open} onClose={() => setOpen(null)} />
      ) : null}
    </div>
  );
}

function Stat({ value, label, color }: { value: number; label: string; color?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(0);
  useEffect(() => {
    if (ref.current && value !== prev.current) {
      countUp(ref.current, value, 600);
      prev.current = value;
    }
  }, [value]);
  return (
    <div className="stack" style={{ alignItems: "center" }}>
      <span ref={ref} className="serif" style={{ fontSize: 30, color: color || colors.ink }}>{value}</span>
      <span className="muted" style={{ fontSize: 12 }}>{label}</span>
    </div>
  );
}
