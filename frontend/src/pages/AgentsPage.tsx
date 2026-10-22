import { useEffect, useMemo, useState } from "react";
import {
  api,
  formatApiError,
  type AgentDraft,
  type AgentTrack,
  type AgentsSnapshot,
  type BuiltinAgent,
  type CustomAgent,
} from "../api";
import { AgentSkillsModal } from "../features/agents/AgentSkillsModal";
import { Modal } from "../components/Modal";
import { useT } from "../i18n";

const TRACKS: AgentTrack[] = ["redteam", "flag", "src"];
const TRACK_LABEL: Record<AgentTrack, string> = {
  redteam: "agents.trackRed",
  flag: "agents.trackCtf",
  src: "agents.trackSrc",
};

function emptyDraft(track: AgentTrack): AgentDraft {
  return {
    id: "",
    description: "",
    prompt: "",
    tracks: [track],
    enabled: true,
    default: false,
    model: "",
  };
}

function Switch({
  on,
  disabled,
  onClick,
}: {
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`proxy-switch${on ? " is-on" : ""}`}
      aria-pressed={on}
      disabled={disabled}
      onClick={onClick}
    >
      <span className="proxy-switch-knob" />
    </button>
  );
}

function TrackBadges({
  tracks,
  active,
  t,
}: {
  tracks: AgentTrack[];
  active: AgentTrack;
  t: (key: string) => string;
}) {
  return (
    <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
      {tracks.map((track) => (
        <span
          key={track}
          className={`badge ${track === active ? "badge-coral" : "badge-pill"}`}
        >
          {t(TRACK_LABEL[track])}
        </span>
      ))}
    </div>
  );
}

function BuiltinCard({
  agent,
  track,
  busy,
  t,
  onPatch,
  onSkills,
}: {
  agent: BuiltinAgent;
  track: AgentTrack;
  busy: boolean;
  t: (key: string) => string;
  onPatch: (id: string, body: Partial<AgentDraft>) => void;
  onSkills: () => void;
}) {
  const [model, setModel] = useState(agent.model);
  useEffect(() => setModel(agent.model), [agent.model]);
  const core = agent.core.includes(track);
  return (
    <section className="card-cream">
      <div className="spread" style={{ alignItems: "flex-start", gap: 12 }}>
        <div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <h3 className="mono" style={{ margin: 0 }}>{agent.id}</h3>
            <span className="badge badge-pill">{t("agents.builtin")}</span>
            {core ? <span className="badge badge-coral">{t("agents.core")}</span> : null}
          </div>
          <p className="muted" style={{ margin: "8px 0 0", lineHeight: 1.55 }}>
            {agent.descriptions[track] || t("agents.noDescription")}
          </p>
        </div>
        <TrackBadges tracks={agent.tracks} active={track} t={t} />
      </div>
      <dl className="settings-list">
        <dt>{t("agents.enabled")}</dt>
        <dd>
          <Switch
            on={agent.enabled}
            disabled={busy || core}
            onClick={() => onPatch(agent.id, { enabled: !agent.enabled })}
          />
        </dd>
        <dt>{t("agents.default")}</dt>
        <dd>
          <Switch
            on={agent.default}
            disabled={busy || core}
            onClick={() => onPatch(agent.id, { default: !agent.default })}
          />
        </dd>
        <dt>{t("agents.model")}</dt>
        <dd>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <input
              className="input mono"
              style={{ maxWidth: 220 }}
              value={model}
              placeholder={t("agents.modelPlaceholder")}
              onChange={(e) => setModel(e.target.value)}
              spellCheck={false}
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={busy || model === agent.model}
              onClick={() => onPatch(agent.id, { model })}
            >
              {t("common.save")}
            </button>
          </div>
        </dd>
      </dl>
      <button type="button" className="btn btn-secondary btn-sm" onClick={onSkills} disabled={busy}>
        {t("skills.manage")}
      </button>
      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
        {core ? t("agents.coreHint") : t("agents.builtinHint")}
      </p>
    </section>
  );
}

function CustomCard({
  agent,
  track,
  busy,
  t,
  onPatch,
  onEdit,
  onDelete,
  onSkills,
}: {
  agent: CustomAgent;
  track: AgentTrack;
  busy: boolean;
  t: (key: string) => string;
  onPatch: (id: string, body: Partial<AgentDraft>) => void;
  onSkills: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [model, setModel] = useState(agent.model);
  useEffect(() => setModel(agent.model), [agent.model]);
  return (
    <section className="card-cream">
      <div className="spread" style={{ alignItems: "flex-start", gap: 12 }}>
        <div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <h3 className="mono" style={{ margin: 0 }}>{agent.id}</h3>
            <span className="badge badge-pill">{t("agents.custom")}</span>
          </div>
          <p className="muted" style={{ margin: "8px 0 0", lineHeight: 1.55 }}>
            {agent.description || t("agents.noDescription")}
          </p>
        </div>
        <TrackBadges tracks={agent.tracks} active={track} t={t} />
      </div>
      <dl className="settings-list">
        <dt>{t("agents.enabled")}</dt>
        <dd>
          <Switch
            on={agent.enabled}
            disabled={busy}
            onClick={() => onPatch(agent.id, { enabled: !agent.enabled })}
          />
        </dd>
        <dt>{t("agents.default")}</dt>
        <dd>
          <Switch
            on={agent.default}
            disabled={busy || !agent.enabled}
            onClick={() => onPatch(agent.id, { default: !agent.default })}
          />
        </dd>
        <dt>{t("agents.model")}</dt>
        <dd>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <input
              className="input mono"
              style={{ maxWidth: 220 }}
              value={model}
              placeholder={t("agents.modelPlaceholder")}
              onChange={(e) => setModel(e.target.value)}
              spellCheck={false}
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={busy || model === agent.model}
              onClick={() => onPatch(agent.id, { model })}
            >
              {t("common.save")}
            </button>
          </div>
        </dd>
      </dl>
      <button type="button" className="btn btn-secondary btn-sm" onClick={onSkills} disabled={busy}>
        {t("skills.manage")}
      </button>
      <div className="row" style={{ gap: 8, marginTop: 12 }}>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onEdit} disabled={busy}>
          {t("common.edit")}
        </button>
        <button type="button" className="btn btn-ghost btn-sm error-text" onClick={onDelete} disabled={busy}>
          {t("common.delete")}
        </button>
      </div>
      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
        {t("agents.customHint")}
      </p>
    </section>
  );
}

export function AgentsPage() {
  const { t } = useT();
  const [snap, setSnap] = useState<AgentsSnapshot | null>(null);
  const [track, setTrack] = useState<AgentTrack>("redteam");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [skillsAgent, setSkillsAgent] = useState<BuiltinAgent | CustomAgent | null>(null);
  const [editor, setEditor] = useState<{ mode: "create" | "edit"; draft: AgentDraft } | null>(null);

  const load = async () => {
    try {
      setSnap(await api.listAgents());
    } catch (e) {
      const status = (e as { status?: number } | null)?.status;
      setError(status === 404 ? t("agents.backendRestart") : formatApiError(e, t("agents.loadFailed")));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const builtins = useMemo(
    () => (snap?.builtin || []).filter((a) => a.tracks.includes(track)),
    [snap, track],
  );
  const customs = useMemo(
    () => (snap?.custom || []).filter((a) => a.tracks.includes(track)),
    [snap, track],
  );

  const patch = async (id: string, body: Partial<AgentDraft>) => {
    setBusy(true);
    setError("");
    try {
      setSnap(await api.patchAgent(id, body));
      setMessage(t("agents.saved"));
    } catch (e) {
      setError(formatApiError(e, t("agents.saveFailed")));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(t("agents.deleteConfirm", { id }))) return;
    setBusy(true);
    setError("");
    try {
      setSnap(await api.deleteAgent(id));
      setMessage(t("agents.deleted"));
    } catch (e) {
      setError(formatApiError(e, t("agents.deleteFailed")));
    } finally {
      setBusy(false);
    }
  };

  const saveEditor = async () => {
    if (!editor) return;
    const draft = editor.draft;
    const id = String(draft.id || "").trim().toLowerCase();
    if (editor.mode === "create" && !/^[a-z][a-z0-9-]{1,31}$/.test(id)) {
      setError(t("agents.invalidId"));
      return;
    }
    if (!draft.description.trim() || !draft.prompt.trim() || draft.tracks.length === 0) {
      setError(t("agents.required"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (editor.mode === "create") {
        setSnap(await api.createAgent({ ...draft, id }));
        setMessage(t("agents.created"));
      } else {
        const { id: _id, ...body } = draft;
        setSnap(await api.patchAgent(id, body));
        setMessage(t("agents.saved"));
      }
      if (draft.tracks[0]) setTrack(draft.tracks[0]);
      setEditor(null);
    } catch (e) {
      setError(formatApiError(e, t("agents.saveFailed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page-container">
      <header className="page-heading">
        <p className="eyebrow">AGENTS</p>
        <h1>{t("agents.title")}</h1>
        <p>{t("agents.subtitle")}</p>
      </header>
      {message ? <p className="muted">{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      <div className="spread" style={{ gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }} role="tablist" aria-label={t("agents.tracks")}>
          {TRACKS.map((item) => (
            <button
              key={item}
              type="button"
              className={`btn btn-sm ${track === item ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setTrack(item)}
            >
              {t(TRACK_LABEL[item])}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!snap || busy}
          onClick={() => setEditor({ mode: "create", draft: emptyDraft(track) })}
        >
          {t("agents.new")}
        </button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {t("agents.runtimeHint")}
      </p>
      {!snap ? (
        <p className="muted">{t("common.loading")}</p>
      ) : (
        <div className="settings-grid" style={{ maxWidth: "none" }}>
          {builtins.map((agent) => (
            <BuiltinCard
              key={agent.id}
              agent={agent}
              track={track}
              busy={busy}
              t={t}
              onPatch={(id, body) => { void patch(id, body); }}
              onSkills={() => setSkillsAgent(agent)}
            />
          ))}
          {customs.map((agent) => (
            <CustomCard
              key={agent.id}
              agent={agent}
              track={track}
              busy={busy}
              t={t}
              onPatch={(id, body) => { void patch(id, body); }}
              onSkills={() => setSkillsAgent(agent)}
              onEdit={() => setEditor({ mode: "edit", draft: { ...agent } })}
              onDelete={() => { void remove(agent.id); }}
            />
          ))}
        </div>
      )}
      {snap ? (
        <p className="muted" style={{ fontSize: 12 }}>
          {t("agents.limitHint", {
            per: snap.limits.per_project,
            live: snap.limits.max_live,
          })}
        </p>
      ) : null}

      {skillsAgent ? (
        <AgentSkillsModal
          agent={skillsAgent}
          track={track}
          onClose={() => setSkillsAgent(null)}
          onSaved={(next) => {
            setSnap(next);
            setMessage(t("agents.saved"));
            setError("");
            setSkillsAgent(null);
          }}
        />
      ) : null}
      {editor ? (
        <Modal
          wide
          title={editor.mode === "create" ? t("agents.newTitle") : t("agents.editTitle")}
          onClose={() => setEditor(null)}
        >
          <div style={{ display: "grid", gap: 12 }}>
            <label className="login-field">
              <span>{t("agents.id")}</span>
              <input
                className="input mono"
                value={editor.draft.id || ""}
                disabled={editor.mode === "edit"}
                placeholder="api-hunter"
                onChange={(e) => setEditor((cur) => cur ? { ...cur, draft: { ...cur.draft, id: e.target.value } } : cur)}
                spellCheck={false}
              />
            </label>
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>{t("agents.idHint")}</p>
            <label className="login-field">
              <span>{t("agents.description")}</span>
              <input
                className="input"
                value={editor.draft.description}
                onChange={(e) => setEditor((cur) => cur ? { ...cur, draft: { ...cur.draft, description: e.target.value } } : cur)}
                placeholder={t("agents.descriptionPlaceholder")}
              />
            </label>
            <div>
              <div className="muted" style={{ marginBottom: 6 }}>{t("agents.tracks")}</div>
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                {TRACKS.map((item) => (
                  <label key={item} className="row" style={{ gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={editor.draft.tracks.includes(item)}
                      onChange={(e) => setEditor((cur) => {
                        if (!cur) return cur;
                        const next = e.target.checked
                          ? [...cur.draft.tracks, item]
                          : cur.draft.tracks.filter((x) => x !== item);
                        return { ...cur, draft: { ...cur.draft, tracks: next } };
                      })}
                    />
                    <span>{t(TRACK_LABEL[item])}</span>
                  </label>
                ))}
              </div>
            </div>
            <label className="login-field">
              <span>{t("agents.prompt")}</span>
              <textarea
                className="input mono"
                rows={12}
                style={{ width: "100%", resize: "vertical" }}
                value={editor.draft.prompt}
                onChange={(e) => setEditor((cur) => cur ? { ...cur, draft: { ...cur.draft, prompt: e.target.value } } : cur)}
                placeholder={t("agents.promptPlaceholder")}
              />
            </label>
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>{t("agents.promptHint")}</p>
            <label className="login-field">
              <span>{t("agents.model")}</span>
              <input
                className="input mono"
                value={editor.draft.model}
                placeholder={t("agents.modelPlaceholder")}
                onChange={(e) => setEditor((cur) => cur ? { ...cur, draft: { ...cur.draft, model: e.target.value } } : cur)}
                spellCheck={false}
              />
            </label>
            <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
              <label className="row" style={{ gap: 6 }}>
                <input
                  type="checkbox"
                  checked={editor.draft.enabled}
                  onChange={(e) => setEditor((cur) => cur ? { ...cur, draft: { ...cur.draft, enabled: e.target.checked } } : cur)}
                />
                <span>{t("agents.enabled")}</span>
              </label>
              <label className="row" style={{ gap: 6 }}>
                <input
                  type="checkbox"
                  checked={editor.draft.default}
                  onChange={(e) => setEditor((cur) => cur ? { ...cur, draft: { ...cur.draft, default: e.target.checked } } : cur)}
                />
                <span>{t("agents.default")}</span>
              </label>
            </div>
            <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
              <button type="button" className="btn btn-secondary" onClick={() => setEditor(null)}>
                {t("common.cancel")}
              </button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => { void saveEditor(); }}>
                {busy ? t("common.saving") : t("common.save")}
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
