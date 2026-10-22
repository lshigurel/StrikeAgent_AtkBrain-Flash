import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { AgentsPage } from "./AgentsPage";
vi.mock("animejs", () => ({ animate: vi.fn() }));
vi.mock("../api", () => ({ api: { listAgents: vi.fn(), listAgentSkills: vi.fn(), patchAgent: vi.fn(), createAgentSkill: vi.fn(), updateAgentSkill: vi.fn() }, formatApiError: (e: Error) => e.message }));
const snapshot = () => ({ builtin: [{ id: "recon", tracks: ["redteam"], core: ["redteam"], enabled: true, default: true, model: "", descriptions: {}, skills: null }], custom: [{ id: "api-hunter", description: "API", prompt: "Inspect", tracks: ["redteam"], enabled: true, default: false, model: "", skills: ["kali-kit"] }], limits: { per_project: 4, max_live: 32 } });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listAgents).mockResolvedValue(snapshot() as any);
  (api as any).listAgentSkills.mockResolvedValue({ skills: [{ name: "kali-kit", content: "# Tool reference" }, { name: "recon-spiral", content: "# Recon steps" }], defaults: { redteam: ["kali-kit", "recon-spiral"], flag: ["kali-kit"], src: ["kali-kit"] } });
  vi.mocked(api.patchAgent).mockResolvedValue(snapshot() as any);
});
async function open(index = 0) {
  render(<AgentsPage />);
  const buttons = await screen.findAllByRole("button", { name: "Skill 管理" });
  fireEvent.click(buttons[index]);
  await screen.findByLabelText("沿用赛道默认");
  await screen.findByLabelText("kali-kit");
}
it("shows track defaults and previews skill content", async () => {
  await open();
  expect(screen.getByLabelText("沿用赛道默认")).toBeChecked();
  expect(screen.getByLabelText("kali-kit")).toBeChecked();
  expect(screen.getByLabelText("kali-kit")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "查看内容 · kali-kit" }));
  await screen.findByText("# Tool reference");
});
it("saves an explicitly empty selection for the selected agent", async () => {
  await open();
  fireEvent.click(screen.getByLabelText("沿用赛道默认"));
  fireEvent.click(screen.getByRole("button", { name: "清空选择" }));
  fireEvent.click(screen.getByRole("button", { name: "保存 Skill 配置" }));
  await waitFor(() => expect(api.patchAgent).toHaveBeenCalledWith("recon", { skills: [] }));
});
it("restores defaults for a custom agent using null", async () => {
  await open(1);
  expect(screen.getByLabelText("沿用赛道默认")).not.toBeChecked();
  fireEvent.click(screen.getByLabelText("沿用赛道默认"));
  fireEvent.click(screen.getByRole("button", { name: "保存 Skill 配置" }));
  await waitFor(() => expect(api.patchAgent).toHaveBeenCalledWith("api-hunter", { skills: null }));
});
it("keeps selection and modal open when saving fails", async () => {
  vi.mocked(api.patchAgent).mockRejectedValue(new Error("save failed"));
  await open(1);
  fireEvent.click(screen.getByLabelText("recon-spiral"));
  fireEvent.click(screen.getByRole("button", { name: "保存 Skill 配置" }));
  await screen.findByText("save failed");
  expect(screen.getByLabelText("recon-spiral")).toBeChecked();
  expect(screen.getByRole("button", { name: "保存 Skill 配置" })).toBeEnabled();
});
it("prevents saving when the catalog cannot be loaded", async () => {
  (api as any).listAgentSkills.mockRejectedValue(new Error("catalog failed"));
  render(<AgentsPage />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Skill 管理" }))[0]);
  await screen.findByText("catalog failed");
  expect(screen.getByRole("button", { name: "保存 Skill 配置" })).toBeDisabled();
});

it("creates a shared skill without silently changing agent bindings", async () => {
  (api as any).createAgentSkill.mockResolvedValue({ skills: [{ name: "api-guide", content: "# New guide", revision: "new-rev" }], defaults: { redteam: [] } });
  await open();
  fireEvent.click(screen.getByRole("button", { name: "新增 Skill" }));
  fireEvent.change(screen.getByLabelText("Skill 名称"), { target: { value: "api-guide" } });
  fireEvent.change(screen.getByLabelText("Skill 内容（Markdown）"), { target: { value: "# New guide" } });
  fireEvent.click(screen.getByRole("button", { name: "保存 Skill 内容" }));
  await waitFor(() => expect((api as any).createAgentSkill).toHaveBeenCalledWith({ name: "api-guide", content: "# New guide" }));
  await screen.findByLabelText("api-guide");
  expect(api.patchAgent).not.toHaveBeenCalled();
});
it("edits a shared skill with its revision and preserves draft on conflict", async () => {
  (api as any).listAgentSkills.mockResolvedValue({ skills: [{ name: "kali-kit", content: "# Tool reference", revision: "rev-1" }], defaults: { redteam: ["kali-kit"] } });
  (api as any).updateAgentSkill.mockRejectedValue(new Error("conflict"));
  await open(1);
  fireEvent.click(screen.getByRole("button", { name: "编辑内容 · kali-kit" }));
  expect(screen.getByLabelText("Skill 名称")).toBeDisabled();
  expect(screen.getByText(/影响所有绑定此 skill 的 agent/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Skill 内容（Markdown）"), { target: { value: "# Shared change" } });
  fireEvent.click(screen.getByRole("button", { name: "保存 Skill 内容" }));
  await screen.findByText("conflict");
  expect(screen.getByLabelText("Skill 内容（Markdown）")).toHaveValue("# Shared change");
  expect((api as any).updateAgentSkill).toHaveBeenCalledWith("kali-kit", { content: "# Shared change", revision: "rev-1" });
});
it("cancels skill editing without losing the unsaved binding selection", async () => {
  await open(1);
  fireEvent.click(screen.getByLabelText("recon-spiral"));
  fireEvent.click(screen.getByRole("button", { name: "新增 Skill" }));
  fireEvent.click(screen.getByRole("button", { name: "取消编辑" }));
  expect(screen.getByLabelText("recon-spiral")).toBeChecked();
});
