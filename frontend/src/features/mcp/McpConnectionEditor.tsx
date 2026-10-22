import { useId, useState } from "react";
import { useT } from "../../i18n";
import type { ConnectionDraft, KeyValue } from "./connection";
import { connectionJson, fromConnectionJson } from "./connection";
import type { Transport, McpAgentOption } from "./types";
import "./mcp.css";

export function McpConnectionEditor({draft:d,onChange,agents=[]}:{
  draft:ConnectionDraft;onChange:(draft:ConnectionDraft)=>void;agents?:McpAgentOption[];
}) {
  const {t}=useT(),id=useId();
  const [error,setError]=useState("");
  const update=(value:Partial<ConnectionDraft>)=>{setError("");onChange({...d,...value});};
  const options=[...agents,...d.allowedAgents.filter(a=>!agents.some(option=>option.id===a))
    .map(id=>({id,enabled:false}))];
  function mode(next:"form"|"json") {
    if(next===d.mode)return;
    try {
      onChange(next==="json"?{...d,mode:next,json:connectionJson(d)}:{...fromConnectionJson(d),mode:next});
      setError("");
    } catch {setError(t("mcp.connectionInvalid"));}
  }
  function transport(next:Transport) {update({transport:next});}
  function keyValues(kind:"env"|"headers") {
    const rows=d[kind],label=t(kind==="env"?"mcp.envLabel":"mcp.headersLabel");
    const saved=kind==="env"?d.server.env_keys:d.server.header_keys;
    const change=(index:number,value:Partial<KeyValue>)=>update({[kind]:rows.map((row,i)=>i===index?{...row,...value}:row)});
    return <div className="mcp-field">
      <span className="mcp-label">{label}</span>
      {rows.map((row,index)=><div className="mcp-pair" key={index}>
        <input aria-label={label+t("mcp.keySuffix")+" "+(index+1)} placeholder={t("mcp.keyPlaceholder")}
          value={row.key} onChange={e=>change(index,{key:e.target.value})} spellCheck={false} autoComplete="off"/>
        <input aria-label={label+t("mcp.valueSuffix")+" "+(index+1)} placeholder={saved.includes(row.key)?t("mcp.savedValue"):t("mcp.valuePlaceholder")}
          type="password" value={row.value} onChange={e=>change(index,{value:e.target.value})} autoComplete="new-password"/>
        <button type="button" className="mcp-remove" aria-label={t("mcp.remove")+label+" "+(index+1)}
          onClick={()=>update({[kind]:rows.filter((_,i)=>i!==index)})}>×</button>
      </div>)}
      <button type="button" className="mcp-add-row" onClick={()=>update({[kind]:[...rows,{key:"",value:""}]})}>
        <span aria-hidden="true">＋</span>{t(kind==="env"?"mcp.addEnv":"mcp.addHeader")}
      </button>
    </div>;
  }
  return <div className="mcp-editor">
    <div className="mcp-field">
      <label className="mcp-label" htmlFor={id+"-name"}>{t("mcp.name")}<span className="mcp-required" aria-hidden="true">*</span>
        <span className="mcp-help" title={t("mcp.nameHelp")} aria-label={t("mcp.nameHelp")}>?</span>
      </label>
      <input aria-label={t("mcp.name")} id={id+"-name"} value={d.name} onChange={e=>update({name:e.target.value})}
        placeholder={t("mcp.namePlaceholder")} maxLength={128} required/>
    </div>
    <fieldset className="mcp-agent-access">
      <legend className="mcp-label">{t("mcp.allowedAgents")}</legend>
      <p className="mcp-agent-hint" id={id+"-agent-hint"}>{t("mcp.agentHint")}</p>
      <div className="mcp-agent-options" aria-describedby={id+"-agent-hint"}>
        {options.map(agent=><label className="mcp-agent-option" key={agent.id}>
          <input type="checkbox" aria-label={agent.id} checked={d.allowedAgents.includes(agent.id)}
            disabled={!agent.enabled&&!d.allowedAgents.includes(agent.id)}
            onChange={e=>update({allowedAgents:e.target.checked?[...d.allowedAgents,agent.id]:d.allowedAgents.filter(a=>a!==agent.id)})}/>
          <span>{agent.id}</span>
          {!agent.enabled&&<small>{t("mcp.agentUnavailable")}</small>}
        </label>)}
      </div>
      {!d.allowedAgents.length&&<p className="mcp-agent-hint">{t("mcp.noAgentsHint")}</p>}
    </fieldset>
    <div className="mcp-connection-heading">
      <strong>{t("mcp.connection")}</strong>
      <div className="mcp-segmented" role="tablist" aria-label={t("mcp.editMode")}>
        <button type="button" role="tab" aria-selected={d.mode==="form"} onClick={()=>mode("form")}>{t("mcp.form")}</button>
        <button type="button" role="tab" aria-selected={d.mode==="json"} onClick={()=>mode("json")}>JSON</button>
      </div>
    </div>
    {error&&<p role="alert" className="mcp-error">{error}</p>}
    {d.mode==="json"?<textarea className="mcp-json" aria-label={t("mcp.connectionJson")} value={d.json}
      onChange={e=>update({json:e.target.value})} spellCheck={false} rows={12}/>:<>
      <div className="mcp-field">
        <span className="mcp-label">{t("mcp.transport")}</span>
        <div className="mcp-segmented mcp-transports" role="tablist" aria-label={t("mcp.transport")}>
          {([["stdio",t("mcp.local")],["streamable_http","HTTP"],["sse","SSE"]] as const).map(([value,label])=>
            <button key={value} type="button" role="tab" aria-selected={d.transport===value}
              onClick={()=>transport(value)}>{label}</button>)}
        </div>
      </div>
      {d.transport==="stdio"?<>
        <div className="mcp-field">
          <label className="mcp-label" htmlFor={id+"-command"}>{t("mcp.commandLabel")}<span className="mcp-required" aria-hidden="true">*</span></label>
          <input aria-label={t("mcp.commandLabel")} id={id+"-command"} value={d.command} onChange={e=>update({command:e.target.value})}
            placeholder={t("mcp.commandPlaceholder")} spellCheck={false} required/>
        </div>
        <div className="mcp-field">
          <span className="mcp-label">{t("mcp.argsLabel")}</span>
          {d.args.map((arg,index)=><div className="mcp-argument" key={index}>
            <input aria-label={t("mcp.argsLabel")+" "+(index+1)} value={arg}
              onChange={e=>update({args:d.args.map((item,i)=>i===index?e.target.value:item)})}/>
            <button type="button" className="mcp-remove" aria-label={t("mcp.remove")+t("mcp.argsLabel")+" "+(index+1)}
              onClick={()=>update({args:d.args.filter((_,i)=>i!==index)})}>×</button>
          </div>)}
          <button type="button" className="mcp-add-row" onClick={()=>update({args:[...d.args,""]})}>
            <span aria-hidden="true">＋</span>{t("mcp.addArgument")}
          </button>
        </div>
        {keyValues("env")}
      </>:<>
        <div className="mcp-field">
          <label className="mcp-label" htmlFor={id+"-url"}>URL<span className="mcp-required" aria-hidden="true">*</span></label>
          <input aria-label="URL" id={id+"-url"} value={d.url} onChange={e=>update({url:e.target.value})}
            placeholder={d.transport==="sse"?"https://mcp.example.com/sse":"https://mcp.example.com/mcp"}
            type="url" spellCheck={false} required/>
        </div>
        {keyValues("headers")}
      </>}
    </>}
  </div>;
}
