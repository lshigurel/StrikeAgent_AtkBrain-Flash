import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { useState } from "react";
import { McpConnectionEditor } from "./McpConnectionEditor";
import { connectionDraft, connectionPatch } from "./connection";
import type { ConnectionDraft } from "./connection";

function Editor() {
  const [draft,setDraft]=useState<ConnectionDraft>(()=>connectionDraft({
    id:"local",name:"本机工具",enabled:false,transport:"stdio",command:"python3",args:[],
    cwd:"/tmp",url:"",allowed_agents:[],env_keys:[],header_keys:[]
  }));
  return <McpConnectionEditor draft={draft} onChange={setDraft}/>;
}
it("switches connection types and preserves each transport draft",async()=>{
  render(<Editor/>);
  fireEvent.change(screen.getByLabelText("命令"),{target:{value:"uvx"}});
  await userEvent.click(screen.getByRole("tab",{name:"HTTP"}));
  fireEvent.change(screen.getByLabelText("URL"),{target:{value:"http://127.0.0.1:8765/mcp"}});
  expect(screen.queryByLabelText("命令")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"添加请求头"}));
  expect(screen.getByLabelText("请求头名称 1")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab",{name:"本地命令（stdio）"}));
  expect(screen.getByLabelText("命令")).toHaveValue("uvx");
  await userEvent.click(screen.getByRole("tab",{name:"SSE"}));
  expect(screen.getByLabelText("URL")).toHaveValue("http://127.0.0.1:8765/mcp");
});
it("edits argument rows and roundtrips connection JSON",async()=>{
  render(<Editor/>);
  await userEvent.click(screen.getByRole("button",{name:"添加参数"}));
  fireEvent.change(screen.getByLabelText("参数 1"),{target:{value:"--verbose"}});
  await userEvent.click(screen.getByRole("tab",{name:"JSON"}));
  const json=screen.getByLabelText("连接配置 JSON");
  expect(JSON.parse((json as HTMLTextAreaElement).value).args).toEqual(["--verbose"]);
  fireEvent.change(json,{target:{value:'{"transport":"stdio","command":"uvx","args":["echo"],"env":{"LANG":"zh_CN.UTF-8"}}'}});
  await userEvent.click(screen.getByRole("tab",{name:"表单"}));
  expect(screen.getByLabelText("命令")).toHaveValue("uvx");
  expect(screen.getByLabelText("参数 1")).toHaveValue("echo");
  expect(screen.getByLabelText("环境变量名称 1")).toHaveValue("LANG");
});
it("keeps malformed JSON visible rather than dropping the draft",async()=>{
  render(<Editor/>);
  await userEvent.click(screen.getByRole("tab",{name:"JSON"}));
  fireEvent.change(screen.getByLabelText("连接配置 JSON"),{target:{value:"{"}});
  await userEvent.click(screen.getByRole("tab",{name:"表单"}));
  expect(screen.getByLabelText("连接配置 JSON")).toHaveValue("{");
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
it("saves connection edits without resetting agent grants or unread secret values",()=>{
  const draft=connectionDraft({
    id:"local",name:"本机工具",enabled:true,transport:"stdio",command:"python3",args:[],
    cwd:"/tmp",url:"",allowed_agents:["reverse"],
    env_keys:["TOKEN","OLD"],header_keys:[]
  });
  draft.env=draft.env.filter(row=>row.key!=="OLD");
  draft.env.push({key:"NEW",value:"new-value"});
  const patch=connectionPatch(draft);
  expect(patch.allowed_agents).toEqual(["reverse"]);
  expect(patch).not.toHaveProperty("allowed_tools");
  expect(patch.env_patch).toEqual({OLD:null,NEW:"new-value"});
  expect(patch).not.toHaveProperty("env");
});

it("keeps saved credentials when connection JSON omits their map",()=>{
  const draft=connectionDraft({
    id:"local",name:"Local",enabled:false,transport:"stdio",command:"python3",args:[],
    cwd:"/tmp",url:"",allowed_agents:[],env_keys:["TOKEN"],header_keys:["Authorization"]
  });
  draft.mode="json";
  draft.json='{"transport":"stdio","command":"uvx","args":[]}';
  expect(connectionPatch(draft)).not.toHaveProperty("env_patch");
  draft.json='{"transport":"streamable_http","url":"http://127.0.0.1:8765/mcp"}';
  expect(connectionPatch(draft)).not.toHaveProperty("headers_patch");
});
it("clears saved credentials only when JSON explicitly supplies an empty map",()=>{
  const draft=connectionDraft({
    id:"local",name:"Local",enabled:false,transport:"stdio",command:"python3",args:[],
    cwd:"/tmp",url:"",allowed_agents:[],env_keys:["TOKEN"],header_keys:[]
  });
  draft.mode="json";
  draft.json='{"transport":"stdio","command":"uvx","args":[],"env":{}}';
  expect(connectionPatch(draft).env_patch).toEqual({TOKEN:null});
});
