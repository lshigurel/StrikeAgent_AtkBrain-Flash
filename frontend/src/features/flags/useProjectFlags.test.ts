import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useProjectFlags } from "./useProjectFlags";

const flag = { id: "fl_1", project_id: "p1", unique_code: null, flag_index: 1, value: "flag{stored}", submitted: 1, correct: 1, awarded: 0, created_at: 1792500000 };
function respond(rows: unknown[]) { return new Response(JSON.stringify(rows), { status: 200 }); }
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("loads stored flags and reloads full values after a flag event revision", async () => {
  let rows = [flag];
  vi.stubGlobal("fetch", async (url: string) => {
    expect(url).toBe("/api/projects/p1/flags");
    return respond(rows);
  });
  const { result, rerender } = renderHook(({ revision }) => useProjectFlags("p1", revision, false), { initialProps: { revision: 0 } });
  await waitFor(() => expect(result.current.flags[0]?.value).toBe("flag{stored}"));
  rows = [{ ...flag, id: "fl_2", value: "flag{new_full_value}" }, flag];
  rerender({ revision: 1 });
  await waitFor(() => expect(result.current.flags.map(f => f.value)).toEqual(["flag{new_full_value}", "flag{stored}"]));
});

it("never exposes flags from a previous project when its request resolves late", async () => {
  let resolveOld!: (response: Response) => void;
  vi.stubGlobal("fetch", (url: string) => url.includes("p1")
    ? new Promise<Response>(resolve => { resolveOld = resolve; })
    : Promise.resolve(respond([{ ...flag, project_id: "p2", value: "flag{p2}" }])));
  const { result, rerender } = renderHook(({ id }) => useProjectFlags(id, 0, false), { initialProps: { id: "p1" as string | undefined } });
  rerender({ id: "p2" });
  await waitFor(() => expect(result.current.flags[0]?.value).toBe("flag{p2}"));
  await act(async () => { resolveOld(respond([flag])); });
  expect(result.current.flags[0]?.value).toBe("flag{p2}");
  rerender({ id: undefined });
  expect(result.current.flags).toEqual([]);
});

it("reports request failure and recovers through retry", async () => {
  let fail = true;
  vi.stubGlobal("fetch", async () => fail ? new Response("unavailable", { status: 503 }) : respond([flag]));
  const { result } = renderHook(() => useProjectFlags("p1", 0, false));
  await waitFor(() => expect(result.current.error).toBe(true));
  fail = false;
  act(() => { result.current.retry(); });
  await waitFor(() => expect(result.current.flags[0]?.value).toBe("flag{stored}"));
  expect(result.current.error).toBe(false);
});

it("counts a repeated capture once while preserving different values with the same index", async () => {
  vi.stubGlobal("fetch", async () => respond([
    { ...flag, id: "fl_6", value: "flag{third}", flag_index: 2 },
    { ...flag, id: "fl_5", value: "flag{second}", flag_index: null },
    { ...flag, id: "fl_4", value: "flag{stored}", flag_index: 2 },
    { ...flag, id: "fl_3", value: "flag{third}", flag_index: null },
    { ...flag, id: "fl_2", value: "flag{second}", flag_index: 2 },
    flag,
  ]));
  const { result } = renderHook(() => useProjectFlags("p1", 0, false));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.flags.map(f => f.value)).toEqual(["flag{third}", "flag{second}", "flag{stored}"]);
});

it("polls while running so a missed event does not hide a flag", async () => {
  vi.useFakeTimers();
  let rows: typeof flag[] = [];
  vi.stubGlobal("fetch", async () => respond(rows));
  const { result } = renderHook(() => useProjectFlags("p1", 0, true));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  rows = [flag];
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
  expect(result.current.flags[0]?.value).toBe("flag{stored}");
});

it("merges whitespace variants and keeps a correct capture over an incorrect retry", async () => {
  vi.stubGlobal("fetch", async () => respond([
    { ...flag, id: "fl_retry", value: " flag{stored} \n", correct: 0 },
    flag,
    { ...flag, id: "fl_old_error", correct: 0 },
  ]));
  const { result } = renderHook(() => useProjectFlags("p1", 0, false));
  await waitFor(() => expect(result.current.loaded).toBe(true));
  expect(result.current.flags).toHaveLength(1);
  expect(result.current.flags[0].value).toBe("flag{stored}");
  expect(result.current.flags[0].correct).toBe(1);
});
