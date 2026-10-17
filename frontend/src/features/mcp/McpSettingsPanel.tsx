import { useEffect, useState } from "react";
import { useT } from "../../i18n";
import { getMcpConfig, saveMcpConfig, testMcpServer } from "./api";
import type { PublicMcpConfig, PublicServerConfig, ServerPatch, McpTestResult } from "./types";

type Draft = PublicServerConfig & { key:number; savedId?:string; argsText:string; rulesText:string; envText:string; headersText:string; clearEnv:boolean; clearHeaders:boolean };
let nextKey=0;
function draft(s:PublicServerConfig,saved=true):Draft {
  return {...s,key:nextKey++,savedId:saved?s.id:undefined,argsText:JSON.stringify(s.args,null,2),rulesText:JSON.stringify(s.allowed_tools,null,2),
    envText:"",headersText:"",clearEnv:false,clearHeaders:false};
}
function object(value:unknown):value is Record<string,unknown> { return !!value && typeof value==="object" && !Array.isArray(value); }
function secret(text:string):Record<string,string> {
  const v:unknown=JSON.parse(text);
  if(!object(v)||Object.values(v).some(x=>typeof x!=="string")) throw new Error("invalid");
  return v as Record<string,string>;
}
function patch(d:Draft):ServerPatch {
  const args:unknown=JSON.parse(d.argsText),rules:unknown=JSON.parse(d.rulesText);
  if(!Array.isArray(args)||args.some(x=>typeof x!=="string")||!Array.isArray(rules)) throw new Error("invalid");
  for(const r of rules) {
    if(!object(r)||typeof r.name!=="string"||!r.name||!Array.isArray(r.roles)||!r.roles.length||
      r.roles.some((x:unknown)=>x!=="recon"&&x!=="web-exploit")||!["pure","http_url"].includes(String(r.profile))||
      !Array.isArray(r.target_pointers)||r.target_pointers.some((x:unknown)=>typeof x!=="string"||!x.startsWith("/"))||
      (r.profile==="http_url"&&!r.target_pointers.length)) throw new Error("invalid");
  }
  const out:ServerPatch={id:d.id,enabled:d.enabled,transport:d.transport,command:d.command,cwd:d.cwd,url:d.url,args:args as string[],allowed_tools:rules as ServerPatch["allowed_tools"]};
  if(d.clearEnv)out.env={}; else if(d.envText.trim())out.env=secret(d.envText);
  if(d.clearHeaders)out.headers={}; else if(d.headersText.trim())out.headers=secret(d.headersText);
  return out;
}
export function McpSettingsPanel() {
  const {t}=useT();
  const [rows,setRows]=useState<Draft[]>([]),[revision,setRevision]=useState<number|null>(null);
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(""),[results,setResults]=useState<Record<number,McpTestResult>>({});
  function accept(c:PublicMcpConfig) { setRevision(c.revision);setRows(c.servers.map(s=>draft(s)));setResults({}); }
  function failure(e:unknown) { setMessage(e instanceof Error&&e.message.includes("mcp_config_changed")?t("mcp.conflict"):t("mcp.failed")); }
  async function reload() { setBusy(true);try{accept(await getMcpConfig());setMessage("");}catch(e){failure(e);}finally{setBusy(false);} }
  useEffect(()=>{void reload();},[]);
  function update(key:number,values:Partial<Draft>) { setRows(old=>old.map(r=>r.key===key?{...r,...values}:r)); }
  function add(transport:Draft["transport"]) {
    let n=1;while(rows.some(r=>r.id==="server-"+n))n++;
    setRows(old=>[...old,draft({id:"server-"+n,enabled:false,transport,command:"",cwd:"",url:"",args:[],allowed_tools:[],env_keys:[],header_keys:[]},false)]);
  }
  async function save() {
    let servers:ServerPatch[];
    try{servers=rows.map(patch);}catch{setMessage(t("mcp.invalid"));return;}
    if(revision===null)return;
    setBusy(true);
    try { accept(await saveMcpConfig({revision,servers}));setMessage(t("mcp.saved")); }
    catch(e){failure(e);}finally{setBusy(false);}
  }
  async function test(row:Draft) {
    if(!row.savedId)return;
    setBusy(true);
    try{const result=await testMcpServer(row.savedId);setResults(old=>({...old,[row.key]:result}));}
    catch(e){failure(e);}finally{setBusy(false);}
  }
  return <section className="card-cream" style={{gridColumn:"1 / -1"}}>
    <h3>{t("mcp.title")}</h3><p className="muted">{t("mcp.hint")}</p>
    {message&&<p role="status">{message}</p>}
    <fieldset disabled={busy} style={{border:0,padding:0,minWidth:0}}>
      {revision===null?<p>{t("common.loading")}</p>:rows.length===0?<p>{t("mcp.empty")}</p>:null}
      {rows.map(row=><div key={row.key} data-testid="mcp-server" style={{borderTop:"1px solid #9995",padding:"18px 0"}}>
        <div style={{display:"flex",gap:16,alignItems:"center",flexWrap:"wrap"}}>
          <label className="login-field"><span>{t("mcp.id")}</span><input className="input" value={row.id} onChange={e=>update(row.key,{id:e.target.value})}/></label>
          <strong>{row.transport==="stdio"?"stdio":"Streamable HTTP"}</strong>
          <label><input type="checkbox" checked={row.enabled} onChange={e=>update(row.key,{enabled:e.target.checked})}/>{t("mcp.enabled")}</label>
          <button type="button" className="btn" onClick={()=>setRows(old=>old.filter(r=>r.key!==row.key))}>{t("mcp.delete")}</button>
        </div>
        {row.transport==="stdio"?<>
          <label className="login-field"><span>{t("mcp.command")}</span><input className="input" value={row.command} onChange={e=>update(row.key,{command:e.target.value})}/></label>
          <label className="login-field"><span>{t("mcp.cwd")}</span><input className="input" value={row.cwd} onChange={e=>update(row.key,{cwd:e.target.value})}/></label>
          <label className="login-field"><span>{t("mcp.args")}</span><textarea className="input" rows={2} value={row.argsText} onChange={e=>update(row.key,{argsText:e.target.value})}/></label>
        </>:<label className="login-field"><span>{t("mcp.url")}</span><input className="input" value={row.url} onChange={e=>update(row.key,{url:e.target.value})}/></label>}
        <label className="login-field"><span>{t("mcp.rules")}</span><textarea className="input" rows={5} value={row.rulesText} onChange={e=>update(row.key,{rulesText:e.target.value})}/></label>
        <p className="muted">{t("mcp.ruleHint")}</p>
        <code style={{overflowWrap:"anywhere"}}>{'{"name":"echo","roles":["recon"],"profile":"pure","target_pointers":[]}'}</code>
        {(["env","headers"] as const).map(kind=>{
          const env=kind==="env",value=env?row.envText:row.headersText,clear=env?row.clearEnv:row.clearHeaders;
          if((env&&row.transport!=="stdio")||(!env&&row.transport!=="streamable_http"))return null;
          return <div key={kind}><p className="muted">{t("mcp.secretHint")} {(env?row.env_keys:row.header_keys).join(", ")||"—"}</p>
            <label className="login-field"><span>{t(env?"mcp.env":"mcp.headers")}</span><textarea className="input" rows={2} autoComplete="off" spellCheck={false} disabled={clear} value={value} onChange={e=>update(row.key,env?{envText:e.target.value}:{headersText:e.target.value})}/></label>
            <label><input type="checkbox" checked={clear} onChange={e=>update(row.key,env?{clearEnv:e.target.checked}:{clearHeaders:e.target.checked})}/>{t(env?"mcp.clearEnv":"mcp.clearHeaders")}</label>
          </div>;
        })}
        <p className="muted">{t("mcp.testHint")}</p>
        <button type="button" className="btn" disabled={!row.savedId} onClick={()=>void test(row)}>{t("mcp.test")}</button>
        {results[row.key]&&<pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:300,overflow:"auto"}}>{JSON.stringify(results[row.key],null,2)}</pre>}
      </div>)}
      <div style={{display:"flex",gap:8,flexWrap:"wrap",marginTop:16}}>
        <button type="button" className="btn" disabled={revision===null} onClick={()=>add("stdio")}>{t("mcp.addStdio")}</button>
        <button type="button" className="btn" disabled={revision===null} onClick={()=>add("streamable_http")}>{t("mcp.addHttp")}</button>
        <button type="button" className="btn btn-primary" disabled={revision===null} onClick={()=>void save()}>{t("mcp.save")}</button>
        <button type="button" className="btn" onClick={()=>void reload()}>{t("mcp.reload")}</button>
      </div>
    </fieldset>
  </section>;
}

