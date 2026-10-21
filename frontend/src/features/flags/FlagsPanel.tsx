import { useState } from "react";
import type { CapturedFlag } from "../../types";
import { useT } from "../../i18n";

export function FlagsPanel({ flags, loading, error, onRetry }: {
  flags: CapturedFlag[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const { t, locale } = useT();
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);

  const copy = async (flag: CapturedFlag) => {
    setCopied(null);
    setCopyError(null);
    try {
      await navigator.clipboard.writeText(flag.value);
      setCopied(flag.id);
    } catch {
      setCopyError(flag.id);
    }
  };

  return (
    <div className="flags-panel">
      {error && <div role="alert" className="flags-error">
        <span>{t("flags.loadFailed")}</span>
        <button type="button" className="btn btn-sm btn-secondary" onClick={onRetry}>{t("flags.retry")}</button>
      </div>}
      {loading && !flags.length && <p className="muted">{t("common.loading")}</p>}
      {!loading && !error && !flags.length && <p className="muted">{t("flags.empty")}</p>}
      {flags.map((flag, index) => (
        <article key={flag.id} className="card-cream flag-card">
          <div className="spread flag-card-header">
            <div className="row flag-card-labels">
              <b>Flag #{flag.flag_index ?? flags.length - index}</b>
              <span className={`badge ${flag.correct ? "badge-coral" : ""}`}>{t(flag.correct ? "flags.correct" : "flags.incorrect")}</span>
              <span className="muted">{t("flags.score", { n: flag.awarded })}</span>
            </div>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => { void copy(flag); }}>
              {t(copied === flag.id ? "flags.copied" : "flags.copy")}
            </button>
          </div>
          <code className="mono flag-value">{flag.value}</code>
          <div className="muted flag-time">{t("flags.discoveredAt")} <time dateTime={new Date(flag.created_at * 1000).toISOString()}>
            {new Date(flag.created_at * 1000).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")}
          </time></div>
          {copyError === flag.id && <p role="status" className="flags-copy-error">{t("flags.copyFailed")}</p>}
        </article>
      ))}
    </div>
  );
}
