import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { McpSettingsPanel } from "./McpSettingsPanel";
import * as api from "./api";
import { api as appApi } from "../../api";
vi.mock("./api", () => ({ getMcpConfig: vi.fn(), saveMcpConfig: vi.fn(), testMcpServer: vi.fn() }));
vi.mock("../../api", () => ({ api: { listAgents: vi.fn() } }));
const base = { id:"local",enabled:false,transport:"stdio",command:"/bin/echo",args:[],cwd:"/tmp",url:"",allowed_agents:[],env_keys:["TOKEN"],header_keys:[] };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(appApi.listAgents).mockResolvedValue({builtin:[{id:"recon",enabled:true},{id:"reverse",enabled:true}],custom:[{id:"custom-parser",description:"Parser",enabled:true}]} as any);
  vi.mocked(api.getMcpConfig).mockResolvedValue({version:1,revision:4,servers:[base]} as any);
  vi.mocked(api.saveMcpConfig).mockResolvedValue({version:1,revision:5,servers:[base]} as any);
});

it("saves agent selections across form and JSON editing and restores them on reopen",async()=>{
  const server={...base,allowed_agents:["recon"]};
  vi.mocked(api.getMcpConfig).mockResolvedValue({version:1,revision:4,servers:[server]} as any);
  vi.mocked(api.saveMcpConfig).mockImplementation(async input=>({version:1,revision:5,servers:input.servers.map(s=>({...s,env_keys:["TOKEN"],header_keys:[]}))}) as any);
  await ready();await edit();
  expect(screen.getByRole("checkbox",{name:"recon"})).toBeChecked();
  await userEvent.click(screen.getByRole("checkbox",{name:"recon"}));
  await userEvent.click(screen.getByRole("checkbox",{name:"reverse"}));
  await userEvent.click(screen.getByRole("checkbox",{name:"custom-parser"}));
  await userEvent.click(screen.getByRole("tab",{name:"JSON"}));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  const saved=vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers[0] as any;
  expect(saved.allowed_agents).toEqual(["reverse","custom-parser"]);
  expect(saved).not.toHaveProperty("allowed_tools");
  await screen.findByText("MCP 配置已保存");
  await edit();
  expect(screen.getByRole("checkbox",{name:"recon"})).not.toBeChecked();
  expect(screen.getByRole("checkbox",{name:"reverse"})).toBeChecked();
  expect(screen.getByRole("checkbox",{name:"custom-parser"})).toBeChecked();
});

it("allows explicitly granting no agents",async()=>{
  vi.mocked(api.getMcpConfig).mockResolvedValue({version:1,revision:4,servers:[{...base,allowed_agents:["recon"]}]} as any);
  await ready();await edit();
  await userEvent.click(screen.getByRole("checkbox",{name:"recon"}));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  expect((vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers[0] as any).allowed_agents).toEqual([]);
});
async function ready() { render(<McpSettingsPanel/>); await screen.findByText("local"); }
async function edit() { await userEvent.click(screen.getByRole("button",{name:"编辑连接"})); }
it("offers lead separately from managed worker agents and persists its grant",async()=>{
  vi.mocked(api.saveMcpConfig).mockImplementation(async input=>({version:1,revision:5,servers:input.servers.map(s=>({...s,env_keys:["TOKEN"],header_keys:[]}))}) as any);
  await ready();await edit();
  expect(screen.getByRole("checkbox",{name:"lead"})).not.toBeChecked();
  await userEvent.click(screen.getByRole("checkbox",{name:"lead"}));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  expect(vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers[0].allowed_agents).toEqual(["lead"]);
  await screen.findByText("MCP 配置已保存");
  await edit();
  expect(screen.getByRole("checkbox",{name:"lead"})).toBeChecked();
});
it("preserves unread secrets and supports removing individual keys",async()=>{
  await ready();await edit();
  expect(screen.getByLabelText("环境变量值 1")).toHaveValue("");
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  expect(vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers[0]).not.toHaveProperty("env");
  expect(vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers[0]).not.toHaveProperty("env_patch");
  await edit();
  await userEvent.click(screen.getByRole("button",{name:"删除环境变量 1"}));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.saveMcpConfig).mock.calls[1][0].servers[0].env_patch).toEqual({TOKEN:null});
});
it("adds an HTTP connection using the screenshot fields",async()=>{
  vi.mocked(api.getMcpConfig).mockResolvedValue({version:1,revision:0,servers:[]});
  render(<McpSettingsPanel/>);
  await screen.findByText("尚未配置 MCP 服务");
  await userEvent.click(screen.getByRole("button",{name:"添加 MCP 服务"}));
  fireEvent.change(screen.getByLabelText("名称"),{target:{value:"Context 7"}});
  await userEvent.click(screen.getByRole("tab",{name:"HTTP"}));
  fireEvent.change(screen.getByLabelText("URL"),{target:{value:"http://127.0.0.1:8765/mcp"}});
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  expect(vi.mocked(api.saveMcpConfig).mock.calls[0][0]).toEqual({
    revision:0,servers:[{id:"server-1",name:"Context 7",enabled:false,transport:"streamable_http",
      command:"",cwd:"",url:"http://127.0.0.1:8765/mcp",args:[],allowed_agents:[]}]
  });
});
it("retains the editor draft on revision conflict and malformed JSON",async()=>{
  await ready();await edit();
  await userEvent.click(screen.getByRole("tab",{name:"JSON"}));
  fireEvent.change(screen.getByLabelText("连接配置 JSON"),{target:{value:"bad"}});
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  expect(api.saveMcpConfig).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("连接配置 JSON"),{target:{value:'{"transport":"stdio","command":"/bin/echo","args":["draft"],"env":{"TOKEN":""}}'}});
  vi.mocked(api.saveMcpConfig).mockRejectedValue(new Error("mcp_config_changed"));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await screen.findByText(/配置已被其他页面修改/);
  expect((screen.getByLabelText("连接配置 JSON") as HTMLTextAreaElement).value).toContain("draft");
});
it("tests saved config only and displays schemas and failures",async()=>{
  await ready();
  vi.mocked(api.testMcpServer).mockResolvedValue({ok:true,latency_ms:3,tools:[{name:"echo",description:"safe",inputSchema:{type:"object",properties:{text:{type:"string"}}}}]});
  await userEvent.click(screen.getByRole("button",{name:"测试已保存配置"}));
  await screen.findByText(/inputSchema/);
  expect(api.testMcpServer).toHaveBeenCalledWith("local");
  expect(api.saveMcpConfig).not.toHaveBeenCalled();
  vi.mocked(api.testMcpServer).mockResolvedValue({ok:false,latency_ms:3,tools:[],error_code:"timeout"});
  await userEvent.click(screen.getByRole("button",{name:"测试已保存配置"}));
  await screen.findByText(/timeout/);
});

it("shows configuration validation errors without incorrectly blaming login",async()=>{
  await ready();await edit();
  vi.mocked(api.saveMcpConfig).mockRejectedValue(new Error("invalid_mcp_config"));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接配置格式无效");
  expect(screen.getByLabelText("命令")).toHaveValue("/bin/echo");
});
