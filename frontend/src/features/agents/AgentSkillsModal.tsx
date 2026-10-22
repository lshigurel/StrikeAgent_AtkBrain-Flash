import { useEffect, useState } from "react";
import { api, formatApiError, type AgentSkillCatalog, type AgentsSnapshot, type AgentTrack } from "../../api";
import { Modal } from "../../components/Modal";
import { useT } from "../../i18n";

export function AgentSkillsModal({ agent, track, onClose, onSaved }: {
  agent: { id: string; skills?: string[] | null };
  track: AgentTrack;
  onClose: () => void;
  onSaved: (snapshot: AgentsSnapshot) => void;
}) {
  const { t } = useT();
  const [catalog, setCatalog] = useState<AgentSkillCatalog | null>(null);
  const [selection, setSelection] = useState<string[] | null>(agent.skills ?? null);
  const [preview, setPreview] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<{ mode: "create" | "edit"; name: string; content: string; revision: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api.listAgentSkills().then((next) => { if (active) setCatalog(next); })
      .catch((e) => { if (active) setError(formatApiError(e, t("skills.loadFailed"))); });
    return () => { active = false; };
  }, [attempt]);
  const defaults = catalog?.defaults[track] || [];
  const effective = selection ?? defaults;
  const entries: AgentSkillCatalog["skills"] = catalog ? [...catalog.skills, ...(selection || [])
    .filter((name) => !catalog.skills.some((s) => s.name === name))
    .map((name) => ({ name, content: "" }))] : [];
  const closeEditor = () => { setEditor(null); setError(""); };
  const saveContent = async () => {
    if (!editor || busy) return;
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(editor.name) || !editor.content.trim()) {
      setError(t("skills.required"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = editor.mode === "create"
        ? await api.createAgentSkill({ name: editor.name, content: editor.content })
        : await api.updateAgentSkill(editor.name, { content: editor.content, revision: editor.revision });
      setCatalog(next);
      setPreview(editor.name);
      setNotice(t(editor.mode === "create" ? "skills.created" : "skills.contentSaved"));
      setEditor(null);
    } catch (e) {
      setError(formatApiError(e, t("agents.saveFailed")));
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (!catalog || busy) return;
    setBusy(true);
    setError("");
    try {
      onSaved(await api.patchAgent(agent.id, { skills: selection }));
    } catch (e) {
      setError(formatApiError(e, t("agents.saveFailed")));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal wide title={editor ? `${t(editor.mode === "create" ? "skills.add" : "skills.edit")} · ${editor.name || agent.id}` : `${t("skills.manage")} · ${agent.id}`}
      onClose={() => { if (!busy) { if (editor) closeEditor(); else onClose(); } }}>
      <p className="muted">{t(editor ? "skills.sharedEdit" : "skills.hint")}</p>
      {error ? <p className="error-text" role="alert">{error}</p> : null}
      {notice && !editor ? <p className="muted" role="status">{notice}</p> : null}
      {editor ? (
        <div style={{ display: "grid", gap: 12 }}>
          <label className="login-field">
            <span>{t("skills.name")}</span>
            <input className="input mono" value={editor.name} disabled={busy || editor.mode === "edit"}
              placeholder="api-guide" maxLength={64} spellCheck={false}
              onChange={(e) => setEditor({ ...editor, name: e.target.value })} />
          </label>
          <label className="login-field">
            <span>{t("skills.content")}</span>
            <textarea className="input mono" rows={10} value={editor.content} disabled={busy}
              style={{ width: "100%", maxHeight: "36vh", resize: "vertical" }} spellCheck={false}
              onChange={(e) => setEditor({ ...editor, content: e.target.value })} />
          </label>
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>{t("skills.formatHint")}</p>
        </div>
      ) : !catalog ? (
        error ? <button className="btn btn-secondary btn-sm" onClick={() => setAttempt((n) => n + 1)}>{t("skills.retry")}</button>
          : <p className="muted">{t("common.loading")}</p>
      ) : (
        <>
          <button className="btn btn-secondary btn-sm" style={{ marginBottom: 16 }} disabled={busy}
            onClick={() => { setError(""); setEditor({ mode: "create", name: "", content: t("skills.template"), revision: "" }); }}>{t("skills.add")}</button>
          <label className="row" style={{ gap: 8, marginBottom: 16 }}>
            <input type="checkbox" checked={selection === null} disabled={busy}
              onChange={(e) => setSelection(e.target.checked ? null : [...defaults])} />
            <span>{t("skills.inherit")}</span>
          </label>
          <div className="spread" style={{ gap: 8, marginBottom: 12 }}>
            <span className="muted">{t("skills.count", { count: effective.length })}</span>
            <button className="btn btn-secondary btn-sm" disabled={busy || selection === null} onClick={() => setSelection([])}>{t("skills.clear")}</button>
          </div>
          {entries.length === 0 ? <p className="muted">{t("skills.empty")}</p> : null}
          <div style={{ display: "grid", gap: 8, maxHeight: "35vh", overflowY: "auto" }}>
            {entries.map((skill) => (
              <div className="spread card-cream" key={skill.name} style={{ padding: 12, gap: 8, flexWrap: "wrap" }}>
                <label className="row" style={{ gap: 8, minWidth: 0 }}>
                  <input type="checkbox" checked={effective.includes(skill.name)} disabled={busy || selection === null}
                    onChange={(e) => setSelection(e.target.checked ? [...effective, skill.name] : effective.filter((n) => n !== skill.name))} />
                  <span className="mono" style={{ overflowWrap: "anywhere" }}>{skill.name}{!skill.content ? ` (${t("skills.missing")})` : ""}</span>
                </label>
                <button className="btn btn-ghost btn-sm" aria-label={`${t("skills.preview")} · ${skill.name}`}
                  disabled={!skill.content || busy} onClick={() => setPreview(preview === skill.name ? "" : skill.name)}>{t("skills.preview")}</button>
                <button className="btn btn-ghost btn-sm" aria-label={`${t("skills.edit")} · ${skill.name}`}
                  disabled={!skill.content || busy} onClick={() => {
                    setError("");
                    setEditor({ mode: "edit", name: skill.name, content: skill.content, revision: skill.revision || "" });
                  }}>{t("skills.edit")}</button>
              </div>
            ))}
          </div>
          {preview ? <section style={{ marginTop: 16 }}>
            <h3 className="mono">{preview}</h3>
            <pre className="mono" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: "30vh", overflowY: "auto", fontSize: 12 }}>{catalog.skills.find((s) => s.name === preview)?.content}</pre>
          </section> : null}
          {selection !== null && selection.length === 0 ? <p className="muted">{t("skills.none")}</p> : null}
        </>
      )}
      <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
        <button className="btn btn-secondary" disabled={busy} onClick={editor ? closeEditor : onClose}>{t(editor ? "skills.cancelEdit" : "common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy || !catalog} onClick={() => { if (editor) void saveContent(); else void save(); }}>{busy ? t("common.saving") : t(editor ? "skills.saveContent" : "skills.save")}</button>
      </div>
    </Modal>
  );
}
