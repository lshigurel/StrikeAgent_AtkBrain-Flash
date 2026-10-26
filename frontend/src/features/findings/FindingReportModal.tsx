import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Finding, FindingDetail } from "../../types";
import { Modal } from "../../components/Modal";
import { SeverityBadge, VerifyBadge, SecondaryVerifyBadge } from "../../components/Badge";
import { displayFindingSeverity, scrubCandidateRceLabel } from "../../theme";
import { useT } from "../../i18n";

function SectionBody({ text, placeholder }: { text?: string; placeholder: string }) {
  const body = (text || "").trim();
  if (!body) {
    return (
      <p className="muted" style={{ fontSize: 13, margin: 0 }}>
        {placeholder}
      </p>
    );
  }
  return (
    <p style={{ fontSize: 13, margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.65 }}>
      {body}
    </p>
  );
}

export function FindingReportModal({
  projectId, finding, onClose,
}: { projectId: string; finding: Finding; onClose: () => void }) {
  const { t, locale } = useT();
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [err, setErr] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setErr("");
    setDetail(null);
    api.getFinding(projectId, finding.id, true)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e) => { if (!cancelled) setErr(String(e?.message || e)); });
    return () => { cancelled = true; };
  }, [projectId, finding.id, attempt]);

  useEffect(() => {
    if (detail?.report_state !== "writing") return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      api.getFinding(projectId, finding.id, false)
        .then((d) => {
          if (cancelled) return;
          setDetail(d);
          if (d?.report_state !== "writing") window.clearInterval(timer);
        })
        .catch(() => {});
    }, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [detail?.report_state, projectId, finding.id]);

  const downloadMd = () => {
    window.open(api.findingReportUrl(projectId, finding.id, locale), "_blank");
  };

  const d = detail;
  const poc = d?.poc;
  const shownSev = displayFindingSeverity(d || finding);
  const title = `[${shownSev.toUpperCase()}] ${scrubCandidateRceLabel(finding.title) || finding.title}`;
  const state = d?.report_state || (d?.report_pending ? "pending" : d ? "ready" : "pending");
  const failed = (
    finding.verification_status || detail?.verification_status || ""
  ).toLowerCase() === "excluded";
  const showPage = state === "ready";
  const curl = showPage ? (poc?.curl || d?.poc_curl || "").trim() : "";
  const summary = showPage ? (d?.report_summary || "") : "";
  const impact = showPage ? (d?.report_impact || "") : "";
  const rating = showPage ? (d?.report_rating || "") : "";
  const repro = showPage ? (d?.report_repro || "") : "";
  const fix = showPage ? (d?.report_fix || "") : "";
  const placeholder = state === "ready"
    ? t("findings.notCollected")
    : state === "writing"
      ? t("findings.writing")
      : state === "failed"
        ? t("findings.writeFailed")
        : t("findings.pendingCopy");

  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="finding-report">
        <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <SeverityBadge severity={shownSev} />
          <VerifyBadge status={finding.verification_status || detail?.verification_status} />
          {(finding.verification_status || detail?.verification_status || "").toLowerCase() !== "excluded" && (
            <SecondaryVerifyBadge done={!!(finding.secondary_verified || detail?.secondary_verified)} />
          )}
          <span className="muted" style={{ fontSize: 12 }}>{finding.category}</span>
          <div style={{ flex: 1 }} />
          <button className="btn btn-primary btn-sm" onClick={downloadMd}>{t("findings.downloadMd")}</button>
        </div>

        {err && <p style={{ color: "var(--error)", fontSize: 13 }}>{err}</p>}
        {!d && !err && (
          <p className="muted" style={{ fontSize: 13 }}>{t("findings.loading")}</p>
        )}

        {d && (
          <>
            {failed && (
              <>
                <h3>{t("findings.excludeReason")}</h3>
                <SectionBody
                  text={(d.exclusion_reason || d.redteam_rating_rationale || d.proof_detail || "").trim()}
                  placeholder={t("findings.excludeReasonMissing")}
                />
              </>
            )}
            {state === "pending" && (
              <p className="muted" style={{ fontSize: 12, margin: "0 0 12px" }}>
                {t("findings.pageNote")}
              </p>
            )}
            {state === "writing" && (
              <p className="muted" style={{ fontSize: 12, margin: "0 0 12px" }}>
                {t("findings.writing")}
              </p>
            )}
            {state === "failed" && (
              <p className="muted" style={{ fontSize: 12, margin: "0 0 12px" }}>
                {t("findings.writeFailed")}{" "}
                <button className="btn btn-secondary btn-sm" onClick={() => setAttempt((n) => n + 1)}>
                  {t("findings.retryWrite")}
                </button>
              </p>
            )}

            <h3>{t("findings.summary")}</h3>
            <SectionBody text={summary} placeholder={placeholder} />

            <h3>{t("findings.impact")}</h3>
            <SectionBody text={impact} placeholder={placeholder} />

            <h3>{t("findings.rating")}</h3>
            <SectionBody text={rating} placeholder={placeholder} />

            <h3>{t("findings.repro")}</h3>
            <SectionBody text={repro} placeholder={placeholder} />
            {curl ? <pre style={{ maxHeight: 280 }}>{curl}</pre> : null}

            <h3>{t("findings.fix")}</h3>
            <SectionBody text={fix} placeholder={placeholder} />

            <div className="row" style={{ gap: 8, marginTop: 20, borderTop: "1px solid var(--hair)", paddingTop: 14 }}>
              <button className="btn btn-primary" onClick={downloadMd}>{t("findings.downloadThis")}</button>
              <button className="btn btn-secondary" onClick={onClose}>{t("common.close")}</button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
