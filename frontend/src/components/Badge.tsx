import { useT } from "../i18n";

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge badge-${severity}`}>{severity.toUpperCase()}</span>;
}

export function VerifyBadge({ status }: { status?: string }) {
  const { t } = useT();
  const s = (status || "verified").toLowerCase();
  if (s === "excluded") {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--warning, #d4a017)" }}>{t("badge.excluded")}</span>
    );
  }
  if (s === "rejected") {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--error)" }}>{t("badge.rejected")}</span>
    );
  }
  if (s === "pending") {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--muted)" }}>{t("badge.pending")}</span>
    );
  }
  if (s === "flaky") {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--warning, #d4a017)" }}>{t("badge.flaky")}</span>
    );
  }
  return (
    <span className="kbd" style={{ fontSize: 11, color: "var(--ok, #2a7)" }}>{t("badge.verified")}</span>
  );
}

const RT_RATING_KEY: Record<string, string> = {
  critical: "badge.rtCritical",
  high: "badge.rtHigh",
  medium: "badge.rtMedium",
  low: "badge.rtLow",
  info: "badge.rtInfo",
};

export function SecondaryVerifyBadge({ done, reviewing, excluded }: { done?: boolean; reviewing?: boolean; excluded?: boolean }) {
  const { t } = useT();
  if (excluded) {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--warning, #d4a017)" }}>{t("badge.excluded")}</span>
    );
  }
  if (done) {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--ok, #2a7)" }}>{t("badge.secondDone")}</span>
    );
  }
  if (reviewing) {
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--warning, #d4a017)" }}>{t("badge.seconding")}</span>
    );
  }
  return (
    <span className="kbd" style={{ fontSize: 11, color: "var(--muted)" }}>{t("badge.secondNo")}</span>
  );
}

const CVSS_BAND_KEY: Record<string, string> = {
  critical: "badge.cvssCritical",
  high: "badge.cvssHigh",
  medium: "badge.cvssMedium",
  low: "badge.cvssLow",
  info: "badge.cvssNone",
};

export function RedteamRatingBadge({ rating, score, reviewing }: { rating?: string; score?: number | null; reviewing?: boolean }) {
  const { t } = useT();
  const s = (rating || "").toLowerCase();
  const key = RT_RATING_KEY[s];
  if (!key) {
    if (reviewing) {
      return (
        <span className="kbd" style={{ fontSize: 11, color: "var(--warning, #d4a017)" }}>{t("badge.ratingNow")}</span>
      );
    }
    return (
      <span className="kbd" style={{ fontSize: 11, color: "var(--muted)" }}>{t("badge.unrated")}</span>
    );
  }
  const color = s === "critical" || s === "high" ? "var(--error, #c44)" : s === "medium" ? "var(--warning, #d4a017)" : "var(--muted)";
  const bandKey = CVSS_BAND_KEY[s];
  const text = typeof score === "number" && Number.isFinite(score) && bandKey
    ? t("badge.cvssLine", { score: score.toFixed(1), band: t(bandKey) })
    : t(key);
  return (
    <span className="kbd" style={{ fontSize: 11, color }}>{text}</span>
  );
}

export function Badge({ children, coral }: { children: any; coral?: boolean }) {
  return <span className={`badge ${coral ? "badge-coral" : "badge-pill"}`}>{children}</span>;
}
