import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProjectPage } from "./ProjectPage";

const graph = { nodes: [], edges: [], findings: [], intents: [], frontier: {}, rce_path: { path: [], likelihood: 0 }, stats: { nodes: 0, edges: 0, findings: 0, critical: 0, has_shell: false } };
const flag = { id: "fl_1", project_id: "p1", unique_code: null, flag_index: 1, value: "flag{persisted_full_value}", submitted: 1, correct: 1, awarded: 15, created_at: 1792500000 };
let flagRows: typeof flag[];
let track: string;
let socket: FakeSocket;

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  readyState = 1;
  onmessage?: (message: { data: string }) => void;
  onclose?: () => void;
  constructor() { socket = this; }
  close() {}
  send() {}
}

beforeEach(() => {
  track = "ctf";
  flagRows = [flag];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 900, height: 560, x: 0, y: 0, top: 0, left: 0, right: 900, bottom: 560, toJSON: () => ({}) });
  vi.stubGlobal("fetch", async (input: string) => {
    const url = new URL(input, "http://localhost").pathname;
    let data: unknown;
    if (url === "/api/projects/p1") data = { id: "p1", name: "CTF fixture", target: "ctf.local", kind: "single", status: "idle", running: false, queued: false, config: { track, objective: track === "ctf" ? "flag" : "shell", flag_count: 3 }, graph, created_at: 1792500000, updated_at: 1792500000 };
    else if (url === "/api/projects/p1/flags") data = flagRows;
    else if (url === "/api/projects/p1/events") data = [];
    else if (url === "/api/health") data = {};
    else throw new Error(`Unexpected request: ${url}`);
    return new Response(JSON.stringify(data), { status: 200 });
  });
});

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function openProject() {
  return render(<MemoryRouter initialEntries={["/project/p1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Routes><Route path="/project/:id" element={<ProjectPage />} /></Routes>
  </MemoryRouter>);
}

it("adds the CTF flag tab and refreshes full persisted values on a flag event", async () => {
  openProject();
  fireEvent.click(await screen.findByText("已发现 Flag 1"));
  expect(screen.getByText("1/3")).toBeInTheDocument();
  expect(screen.getByText("flag{persisted_full_value}")).toBeInTheDocument();
  flagRows = [{ ...flag, id: "fl_2", flag_index: 2, value: "flag{new_complete_value}" }, flag];
  await act(async () => {
    socket.onmessage?.({ data: JSON.stringify({ id: 1, type: "flag", ts: 1792500010, payload: { value: "flag{new_", correct: true } }) });
  });
  expect(await screen.findByText("已发现 Flag 2")).toBeInTheDocument();
  expect(screen.getByText("2/3")).toBeInTheDocument();
  expect(screen.getByText("flag{new_complete_value}")).toBeInTheDocument();
  expect(screen.queryByText("flag{new_")).not.toBeInTheDocument();
});

it("uses unique persisted flags for both progress and the list despite stale graph goals", async () => {
  flagRows = [{ ...flag, id: "fl_duplicate", flag_index: 2 }, flag];
  openProject();
  fireEvent.click(await screen.findByText("已发现 Flag 1"));
  expect(screen.getAllByText("flag{persisted_full_value}")).toHaveLength(1);
  expect(screen.getByText("1/3")).toBeInTheDocument();
  expect(screen.queryByText("已发现 Flag 2")).not.toBeInTheDocument();
});

it("keeps flag navigation out of non-CTF projects", async () => {
  track = "redteam";
  openProject();
  await screen.findByText("CTF fixture");
  await waitFor(() => expect(screen.getByText("时间线")).toBeInTheDocument());
  expect(screen.queryByText(/已发现 Flag/)).not.toBeInTheDocument();
});
