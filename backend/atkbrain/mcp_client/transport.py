"""Small SDK boundary; no model configuration or persistent result storage."""
from __future__ import annotations
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
import httpx2
from jsonschema import validators
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from .config import ServerConfig

# Protocol payloads/stderr may contain credentials. Application emits metadata only.
_sdk_log = logging.getLogger("mcp")
_sdk_log.addHandler(logging.NullHandler())
_sdk_log.propagate = False

@dataclass
class RemoteTool:
    name: str
    description: str
    input_schema: dict

@dataclass
class ToolReply:
    text: str
    is_error: bool = False
    code: str | None = None

class TransportError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def redact(text: str, secrets: list[str]) -> str:
    for value in sorted(set(filter(None, secrets)), key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    return text

def normalize_result(result: object, secrets: list[str]) -> ToolReply:
    data = result.model_dump(by_alias=True, exclude_none=True) if hasattr(result,"model_dump") else result
    if not isinstance(data, dict):
        return ToolReply("Invalid MCP result", True, "protocol_error")
    parts = []
    for block in data.get("content") or []:
        if not isinstance(block, dict): continue
        parts.append(str(block.get("text","")) if block.get("type")=="text"
                     else "["+str(block.get("type","unsupported"))+" content omitted]")
    structured = data.get("structuredContent", data.get("structured_content"))
    if structured is not None:
        parts.append(json.dumps(structured,ensure_ascii=False))
    raw = redact("\n".join(parts),secrets).encode("utf-8")
    text = raw[:65536].decode("utf-8",errors="ignore")
    if len(raw)>65536: text += "\n[truncated]"
    error = bool(data.get("isError",data.get("is_error",False)))
    return ToolReply(text,error,"remote_error" if error else None)

def _check_schema(schema: dict, arguments: dict) -> None:
    def local_refs(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {"$ref","$dynamicRef"} and (not isinstance(item,str) or not item.startswith("#")):
                    raise ValueError("external schema references are not supported")
                local_refs(item)
        elif isinstance(value,list):
            for item in value: local_refs(item)
    local_refs(schema)
    validator = validators.validator_for(schema)
    validator.check_schema(schema)
    validator(schema).validate(arguments)

def _code(error: BaseException) -> str:
    if isinstance(error,TransportError): return error.code
    if isinstance(error,BaseExceptionGroup):
        codes=[_code(e) for e in error.exceptions]
        return "timeout" if "timeout" in codes else codes[0]
    if isinstance(error,TimeoutError) or "timeout" in type(error).__name__.lower():
        return "timeout"
    # SDK MCPError represents request timeouts with code -32001.
    if getattr(getattr(error,"error",None),"code",None)==-32001:
        return "timeout"
    return "connect_failed"

class McpTransport:
    def __init__(self, connect_timeout: float=10, call_timeout: float=30):
        self.connect_timeout=connect_timeout
        self.call_timeout=call_timeout

    @asynccontextmanager
    async def _streams(self, server: ServerConfig):
        if server.transport=="stdio":
            env={k:os.environ[k] for k in ("HOME","PATH","LANG","TMPDIR") if k in os.environ}
            env.update(server.env)
            # env -i removes SDK-inherited variables without changing process-global os.environ.
            params=StdioServerParameters(command="/usr/bin/env",
                args=["-i",*[f"{k}={v}" for k,v in env.items()],server.command,*server.args],
                cwd=server.cwd)
            with open(os.devnull,"w") as errlog:
                async with stdio_client(params,errlog=errlog) as streams:
                    yield streams
        else:
            async def reject_redirect(response):
                if 300<=response.status_code<400:
                    raise TransportError("protocol_error")
            async with httpx2.AsyncClient(headers=server.headers,trust_env=False,
                    follow_redirects=False,verify=True,timeout=self.connect_timeout,
                    event_hooks={"response":[reject_redirect]}) as http:
                async with streamable_http_client(server.url,http_client=http) as streams:
                    yield streams

    async def _definitions(self, client: Client, server: ServerConfig) -> list[RemoteTool]:
        result=[]
        cursor=None
        seen=set()
        for _ in range(32):
            page=await client.list_tools(cursor=cursor)
            for tool in page.tools:
                raw=json.dumps(tool.model_dump(by_alias=True),ensure_ascii=False)
                clean=json.loads(redact(raw,list(server.env.values())+list(server.headers.values())))
                result.append(RemoteTool(clean["name"],clean.get("description") or "",clean.get("inputSchema") or {}))
            if len(result)>256: raise TransportError("protocol_error")
            cursor=getattr(page,"next_cursor",None) or getattr(page,"nextCursor",None)
            if not cursor: return result
            if cursor in seen: raise TransportError("protocol_error")
            seen.add(cursor)
        raise TransportError("protocol_error")

    async def describe(self, server: ServerConfig) -> list[RemoteTool]:
        try:
            async with asyncio.timeout(self.connect_timeout+5):
                async with Client(self._streams(server),read_timeout_seconds=self.connect_timeout,cache=None) as client:
                    return await self._definitions(client,server)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise TransportError(_code(error)) from None

    async def invoke(self, server: ServerConfig, name: str, arguments: dict) -> ToolReply:
        try:
            async with asyncio.timeout(self.connect_timeout+self.call_timeout+5):
                async with Client(self._streams(server),read_timeout_seconds=self.connect_timeout,cache=None) as client:
                    definitions=await self._definitions(client,server)
                    tool=next((t for t in definitions if t.name==name),None)
                    if not tool: return ToolReply("Unknown MCP tool",True,"invalid_arguments")
                    try:
                        _check_schema(tool.input_schema,arguments)
                    except Exception:
                        return ToolReply("Arguments do not match tool schema",True,"invalid_arguments")
                    result=await client.call_tool(name,arguments,read_timeout_seconds=self.call_timeout)
                    return normalize_result(result,list(server.env.values())+list(server.headers.values()))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code=_code(error)
            return ToolReply(code,True,code)

