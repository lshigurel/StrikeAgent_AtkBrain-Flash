import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { FlagsPanel } from "./FlagsPanel";

const value = `flag{${"full_value_".repeat(20)}}`;
const flag = { id: "fl_1", project_id: "p1", unique_code: null, flag_index: 2, value, submitted: 1, correct: 1, awarded: 25, created_at: 1792500000 };

afterEach(() => { vi.unstubAllGlobals(); });

it("shows the full persisted flag and copies it without truncation", async () => {
  let clipboard = "";
  vi.stubGlobal("navigator", { clipboard: { writeText: async (text: string) => { clipboard = text; } } });
  render(<FlagsPanel flags={[flag]} loading={false} error={false} onRetry={() => {}} />);
  expect(screen.getByText(value)).toBeInTheDocument();
  expect(screen.getByText("正确")).toBeInTheDocument();
  expect(screen.getByText("得分 25")).toBeInTheDocument();
  expect(screen.getByText("Flag #2")).toBeInTheDocument();
  expect(screen.getByText(/发现时间/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制 Flag" }));
  await screen.findByRole("button", { name: "已复制" });
  expect(clipboard).toBe(value);
});

it("keeps the full flag selectable when clipboard access is denied", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText: async () => { throw new Error("denied"); } } });
  render(<FlagsPanel flags={[flag]} loading={false} error={false} onRetry={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "复制 Flag" }));
  expect(await screen.findByRole("status")).toHaveTextContent("复制失败，请手动选择 Flag");
  expect(screen.getByText(value)).toBeInTheDocument();
  expect(screen.queryByText("已复制")).not.toBeInTheDocument();
});

it("distinguishes loading and failures from an empty result and allows retry", () => {
  let retried = false;
  const props = { flags: [], loading: true, error: false, onRetry: () => { retried = true; } };
  const { rerender } = render(<FlagsPanel {...props} />);
  expect(screen.queryByText("尚未发现 Flag")).not.toBeInTheDocument();
  rerender(<FlagsPanel {...props} loading={false} error />);
  expect(screen.getByRole("alert")).toHaveTextContent("Flag 加载失败");
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(retried).toBe(true);
  rerender(<FlagsPanel {...props} loading={false} />);
  expect(screen.getByText("尚未发现 Flag")).toBeInTheDocument();
});
