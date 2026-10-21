import { useEffect, useState } from "react";
import { api } from "../../api";
import type { CapturedFlag } from "../../types";

type FlagState = {
  projectId?: string;
  flags: CapturedFlag[];
  loading: boolean;
  error: boolean;
  loaded: boolean;
};

/** Fetch persisted full values; event payloads may contain only truncated flags. */
export function useProjectFlags(projectId: string | undefined, revision: number, polling: boolean) {
  const [state, setState] = useState<FlagState>({ flags: [], loading: false, error: false, loaded: false });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    let inFlight = false;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      setState(prev => ({ projectId, flags: prev.projectId === projectId ? prev.flags : [], loaded: prev.projectId === projectId && prev.loaded, loading: true, error: false }));
      try {
        const rows = await api.flags(projectId);
        // Resumed runs can persist the same flag again under another id/index.
        const unique = new Map<string, CapturedFlag>();
        for (const flag of rows) {
          const value = flag.value.trim();
          if (!value) continue;
          const previous = unique.get(value);
          if (!previous || (!previous.correct && flag.correct)) unique.set(value, flag);
        }
        if (active) setState({ projectId, flags: [...unique.values()], loading: false, error: false, loaded: true });
      } catch {
        if (active) setState(prev => ({ ...prev, loading: false, error: true }));
      } finally {
        inFlight = false;
      }
    };
    void load();
    const timer = polling ? setInterval(() => { void load(); }, 8000) : undefined;
    return () => { active = false; clearInterval(timer); };
  }, [projectId, revision, polling, attempt]);

  const current = projectId && state.projectId === projectId
    ? state
    : { flags: [], loading: !!projectId, error: false, loaded: false };
  return { ...current, retry: () => setAttempt(value => value + 1) };
}
