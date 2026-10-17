import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { readFileSync } from "node:fs";
const root=process.env.PI_PACKAGE_ROOT;
assert(root,"PI_PACKAGE_ROOT required");
const require=createRequire(resolve(root,"package.json"));
const {createJiti}=require("jiti");
function esmEntry(name) {
  const pkg=JSON.parse(readFileSync(resolve(root,name,"package.json"),"utf8"));
  return resolve(root,name,pkg.exports["."].import);
}
const jiti=createJiti(import.meta.url,{alias:{
  "@earendil-works/pi-coding-agent":esmEntry("@earendil-works/pi-coding-agent"),
  "typebox":esmEntry("typebox")
}});
const extension=await jiti.import(resolve("pi/extensions/atkbrain-tools.ts"),{default:true});
const registered=new Map();
await extension({on(){},registerTool(tool){registered.set(tool.name,tool);}});
assert(registered.has("mcp_list_tools"));
assert(registered.has("mcp_call_tool"));
async function execute(name,args) {
  const result=await registered.get(name).execute("smoke",args,new AbortController().signal);
  assert.equal(result.details.is_error,false,JSON.stringify(result));
  return result.content[0].text;
}
const catalog=JSON.parse(await execute("mcp_list_tools",{}));
assert(catalog.tools.some(t=>t.server_id==="stdio"&&t.name==="nested_echo"&&t.inputSchema.$defs));
for(const server_id of ["stdio","http"]) {
  assert.match(await execute("mcp_call_tool",{server_id,tool_name:"echo",arguments:{text:"local-echo-中文"}}),/local-echo-中文/);
  assert.match(await execute("mcp_call_tool",{server_id,tool_name:"nested_echo",arguments:{item:{value:42}}}),/42/);
}
const invalid=await registered.get("mcp_call_tool").execute("invalid",{
  server_id:"stdio",tool_name:"nested_echo",arguments:{item:{value:"bad"}}
},new AbortController().signal);
assert.equal(invalid.details.is_error,true);
console.log("extension smoke passed");

