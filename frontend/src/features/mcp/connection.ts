import type { PublicServerConfig, ServerPatch, Transport } from "./types";

export type KeyValue = { key:string; value:string };
export type ConnectionDraft = {
  server:PublicServerConfig; name:string; transport:Transport; command:string; args:string[];
  url:string; env:KeyValue[]; headers:KeyValue[]; mode:"form"|"json"; json:string;
  allowedAgents:string[];
};
export function connectionDraft(server:PublicServerConfig):ConnectionDraft {
  return {server,name:server.name||server.id,transport:server.transport,command:server.command,
    args:[...server.args],url:server.url,env:server.env_keys.map(key=>({key,value:""})),
    headers:server.header_keys.map(key=>({key,value:""})),mode:"form",json:"",
    allowedAgents:[...(server.allowed_agents??[])]};
}
function object(value:unknown):value is Record<string,unknown> {
  return value!==null && typeof value==="object" && !Array.isArray(value);
}
function entries(value:unknown):KeyValue[] {
  if(!object(value)||Object.values(value).some(v=>typeof v!=="string"))throw new Error("invalid");
  return Object.entries(value).map(([key,value])=>({key,value:value as string}));
}
function map(rows:KeyValue[]):Record<string,string> {
  const out:Record<string,string>=Object.create(null);
  for(const row of rows) {
    if(!row.key.trim() || Object.prototype.hasOwnProperty.call(out,row.key))throw new Error("invalid");
    out[row.key]=row.value;
  }
  return out;
}
export function connectionJson(draft:ConnectionDraft):string {
  const config=draft.transport==="stdio"
    ? {transport:draft.transport,command:draft.command,args:draft.args,env:map(draft.env)}
    : {transport:draft.transport,url:draft.url,headers:map(draft.headers)};
  return JSON.stringify(config,null,2);
}
export function fromConnectionJson(draft:ConnectionDraft):ConnectionDraft {
  const value:unknown=JSON.parse(draft.json);
  if(!object(value))throw new Error("invalid");
  const transport=value.transport;
  if(transport!=="stdio"&&transport!=="streamable_http"&&transport!=="sse")throw new Error("invalid");
  const keys=transport==="stdio"?["transport","command","args","env"]:["transport","url","headers"];
  if(Object.keys(value).some(key=>!keys.includes(key)))throw new Error("invalid");
  if(transport==="stdio") {
    if(typeof value.command!=="string" || !Array.isArray(value.args) || value.args.some(x=>typeof x!=="string"))
      throw new Error("invalid");
    return {...draft,transport,command:value.command,args:value.args as string[],env:Object.prototype.hasOwnProperty.call(value,"env")?entries(value.env):draft.env};
  }
  if(typeof value.url!=="string")throw new Error("invalid");
  return {...draft,transport,url:value.url,headers:Object.prototype.hasOwnProperty.call(value,"headers")?entries(value.headers):draft.headers};
}
function secretPatch(rows:KeyValue[],savedKeys:string[]):Record<string,string|null> {
  const values=map(rows),changes:Record<string,string|null>=Object.create(null);
  for(const key of savedKeys)if(!Object.prototype.hasOwnProperty.call(values,key))changes[key]=null;
  for(const [key,value] of Object.entries(values))
    if(value!==""||!savedKeys.includes(key))changes[key]=value;
  return changes;
}
export function connectionPatch(input:ConnectionDraft):ServerPatch {
  const d=input.mode==="json"?fromConnectionJson(input):input;
  if(!d.name.trim()||d.name.trim().length>128)throw new Error("invalid");
  if(d.transport==="stdio"?!d.command.trim():!d.url.trim())throw new Error("invalid");
  const result:ServerPatch={id:d.server.id,name:d.name.trim(),enabled:d.server.enabled,
    transport:d.transport,command:d.transport==="stdio"?d.command.trim():"",
    args:d.transport==="stdio"?d.args:[],cwd:d.transport==="stdio"?d.server.cwd:"",
    url:d.transport==="stdio"?"":d.url.trim(),allowed_agents:[...d.allowedAgents]};
  if(d.transport==="stdio") {
    const changes=secretPatch(d.env,d.server.env_keys);
    if(Object.keys(changes).length)result.env_patch=changes;
  } else {
    const changes=secretPatch(d.headers,d.server.header_keys);
    if(Object.keys(changes).length)result.headers_patch=changes;
  }
  return result;
}
