import { useEffect, useState } from "react";
import { useT } from "../../i18n";
import { Modal } from "../../components/Modal";
import { api } from "../../api";
import { getMcpConfig, saveMcpConfig, testMcpServer } from "./api";
import { McpConnectionEditor } from "./McpConnectionEditor";
import { connectionDraft, connectionPatch } from "./connection";
import type { ConnectionDraft } from "./connection";
import type { PublicMcpConfig, PublicServerConfig, ServerPatch, McpTestResult, McpAgentOption } from "./types";

function savedPatch(server:PublicServerConfig):ServerPatch {
  const {env_keys,header_keys,...fields}=server;
  return fields;
}
export function McpSettingsPanel() {
  const {t}=useT();
  const [config,setConfig]=useState<PublicMcpConfig|null>(null);
  const [agents,setAgents]=useState<McpAgentOption[]>([]);
  const [editor,setEditor]=useState<ConnectionDraft|null>(null);
  const [busy,setBusy]=useState(false),[message,setMessage]=useState("");
  const [dialogMessage,setDialogMessage]=useState("");
  const [results,setResults]=useState<Record<string,McpTestResult>>({});
  function failure(e:unknown) {
    const detail=e instanceof Error?e.message:"";
    if(detail.includes("mcp_config_changed"))return t("mcp.conflict");
    if(detail.includes("invalid_mcp_config"))return t("mcp.connectionInvalid");
    return t("mcp.failed");
  }
  async function reload() {
    setBusy(true);
    try{
      const [next,catalog]=await Promise.all([getMcpConfig(),api.listAgents()]);
      setConfig(next);
      setAgents([{id:"lead",enabled:true},...catalog.builtin.map(a=>({id:a.id,enabled:a.enabled})),
        ...catalog.custom.map(a=>({id:a.id,enabled:a.enabled,custom:true}))]);
      setResults({});setMessage("");
    }
    catch(e){setMessage(failure(e));}
    finally{setBusy(false);}
  }
  useEffect(()=>{void reload();},[]);
  function edit(server?:PublicServerConfig) {
    if(!config)return;
    let next=1;while(config.servers.some(s=>s.id==="server-"+next))next++;
    const draft=connectionDraft(server??{id:"server-"+next,enabled:false,transport:"stdio",
      command:"",cwd:"",url:"",args:[],allowed_agents:[],env_keys:[],header_keys:[]});
    if(!server)draft.name="";
    setEditor(draft);setDialogMessage("");
  }
  async function persist(servers:ServerPatch[],closeEditor=false) {
    if(!config)return;
    setBusy(true);
    try {
      setConfig(await saveMcpConfig({revision:config.revision,servers}));
      setResults({});setMessage(t("mcp.saved"));
      if(closeEditor)setEditor(null);
    } catch(e) {if(closeEditor)setDialogMessage(failure(e));else setMessage(failure(e));}
    finally{setBusy(false);}
  }
  function saveEditor() {
    if(!editor||!config)return;
    let patch:ServerPatch;
    try{patch=connectionPatch(editor);}catch{setDialogMessage(t("mcp.connectionInvalid"));return;}
    const exists=config.servers.some(s=>s.id===patch.id);
    const servers=config.servers.map(s=>s.id===patch.id?patch:savedPatch(s));
    if(!exists)servers.push(patch);
    void persist(servers,true);
  }
  async function test(server:PublicServerConfig) {
    setBusy(true);
    try{const result=await testMcpServer(server.id);setResults(old=>({...old,[server.id]:result}));}
    catch(e){setMessage(failure(e));}
    finally{setBusy(false);}
  }
  return <section className="card-cream" style={{gridColumn:"1 / -1"}}>
    <h3>{t("mcp.title")}</h3><p className="muted">{t("mcp.connectionHint")}</p>
    {message&&<p role="status">{message}</p>}
    <fieldset disabled={busy} style={{border:0,padding:0,minWidth:0}}>
      {!config?<p>{t("common.loading")}</p>:!config.servers.length?<p>{t("mcp.empty")}</p>:null}
      {config?.servers.map(server=><div key={server.id} data-testid="mcp-server">
        <div className="mcp-server-summary">
          <strong className="mcp-server-title">{server.name||server.id}</strong>
          <span className="muted">{server.transport==="stdio"?"stdio":server.transport==="sse"?"SSE":"HTTP"}</span>
          <span className="muted mcp-grants-summary">{t("mcp.allowedAgents")}: {server.allowed_agents?.join(", ")||t("mcp.noAgents")}</span>
          <label><input type="checkbox" aria-label={t("mcp.enabled")} checked={server.enabled}
            onChange={e=>void persist(config.servers.map(s=>({...savedPatch(s),enabled:s.id===server.id?e.target.checked:s.enabled})))}/>{t("mcp.enabled")}</label>
          <button type="button" className="btn" onClick={()=>edit(server)}>{t("mcp.edit")}</button>
          <button type="button" className="btn" onClick={()=>void test(server)}>{t("mcp.test")}</button>
          <button type="button" className="btn" onClick={()=>void persist(config.servers.filter(s=>s.id!==server.id).map(savedPatch))}>{t("mcp.delete")}</button>
        </div>
        {results[server.id]&&<pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",maxHeight:300,overflow:"auto"}}>{JSON.stringify(results[server.id],null,2)}</pre>}
      </div>)}
      <div style={{display:"flex",gap:8,flexWrap:"wrap",marginTop:16}}>
        <button type="button" className="btn btn-primary" disabled={!config} onClick={()=>edit()}>{t("mcp.add")}</button>
        <button type="button" className="btn" onClick={()=>void reload()}>{t("mcp.reload")}</button>
      </div>
    </fieldset>
    {editor&&<Modal bare className="mcp-dialog" onClose={()=>{if(!busy)setEditor(null);}}>
      <div className="mcp-dialog-header">
        <h3>{t("mcp.title")}</h3>
        <button type="button" className="btn btn-ghost" aria-label={t("common.close")} disabled={busy} onClick={()=>setEditor(null)}>×</button>
      </div>
      <fieldset disabled={busy} style={{border:0,padding:0,margin:0,minWidth:0}}>
        <McpConnectionEditor draft={editor} agents={agents} onChange={draft=>{setEditor(draft);setDialogMessage("");}}/>
        {dialogMessage&&<p role="alert" className="mcp-dialog-message">{dialogMessage}</p>}
        <div className="mcp-dialog-footer">
          <button type="button" className="btn" onClick={()=>setEditor(null)}>{t("common.cancel")}</button>
          <button type="button" className="btn btn-primary" onClick={saveEditor}>{busy?t("common.saving"):t("mcp.save")}</button>
        </div>
      </fieldset>
    </Modal>}
  </section>;
}
