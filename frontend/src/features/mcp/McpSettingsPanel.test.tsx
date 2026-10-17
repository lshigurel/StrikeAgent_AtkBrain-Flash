import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { McpSettingsPanel } from "./McpSettingsPanel";
import * as api from "./api";
vi.mock("./api", () => ({ getMcpConfig: vi.fn(), saveMcpConfig: vi.fn(), testMcpServer: vi.fn() }));
const base = { id:"local",enabled:false,transport:"stdio",command:"/bin/echo",args:[],cwd:"/tmp",url:"",allowed_tools:[],env_keys:["TOKEN"],header_keys:[] };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getMcpConfig).mockResolvedValue({version:1,revision:4,servers:[base]} as any);
  vi.mocked(api.saveMcpConfig).mockResolvedValue({version:1,revision:5,servers:[base]} as any);
});
async function ready() { render(<McpSettingsPanel/>); await screen.findByDisplayValue("local"); }
it("preserves omitted secrets and explicitly clears them",async()=>{
  await ready();
  expect(screen.getByLabelText("启用")).not.toBeChecked();
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  expect(vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers[0]).not.toHaveProperty("env");
  await userEvent.click(screen.getByLabelText("清空环境变量"));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.saveMcpConfig).mock.calls[1][0].servers[0].env).toEqual({});
});
it("adds both transports and saves disabled services",async()=>{
  vi.mocked(api.getMcpConfig).mockResolvedValue({version:1,revision:0,servers:[]});
  render(<McpSettingsPanel/>);
  await screen.findByText("尚未配置 MCP 服务");
  await userEvent.click(screen.getByRole("button",{name:"添加 stdio"}));
  await userEvent.click(screen.getByRole("button",{name:"添加 HTTP"}));
  const rows=screen.getAllByTestId("mcp-server");
  fireEvent.change(within(rows[0]).getByLabelText("命令（绝对路径）"),{target:{value:"/usr/bin/python3"}});
  fireEvent.change(within(rows[0]).getByLabelText("工作目录（绝对路径）"),{target:{value:"/tmp"}});
  fireEvent.change(within(rows[1]).getByLabelText("服务 URL"),{target:{value:"http://127.0.0.1:8765/mcp"}});
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await waitFor(()=>expect(api.saveMcpConfig).toHaveBeenCalledOnce());
  expect(vi.mocked(api.saveMcpConfig).mock.calls[0][0].servers.map(s=>s.transport)).toEqual(["stdio","streamable_http"]);
});
it("keeps draft after conflict and blocks invalid JSON",async()=>{
  await ready();
  fireEvent.change(screen.getByLabelText("参数 JSON"),{target:{value:"bad"}});
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  expect(api.saveMcpConfig).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("参数 JSON"),{target:{value:'["draft"]'}});
  vi.mocked(api.saveMcpConfig).mockRejectedValue(new Error("mcp_config_changed"));
  await userEvent.click(screen.getByRole("button",{name:"保存 MCP 配置"}));
  await screen.findByText(/配置已被其他页面修改/);
  expect(screen.getByLabelText("参数 JSON")).toHaveValue('["draft"]');
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

