"""Project-scoped policy and cancellation for outbound MCP operations."""
from __future__ import annotations
import asyncio
import json
import time
from collections import defaultdict
from urllib.parse import urlsplit
from ..events import emit
from .config import ConfigStore, ROLES
from .transport import McpTransport, TransportError

# Large MCP servers (for example HexStrike's 150 tools) need a larger catalog
# envelope. Individual tool results remain capped at 65536 bytes in transport.py.
MAX_CATALOG_BYTES = 262144

def response(text: str, code: str|None=None) -> dict:
    return {"content":[{"type":"text","text":text}],"is_error":code is not None,"code":code}

def pointer(data: object, path: str):
    for part in path[1:].split("/"):
        key=part.replace("~1","/").replace("~0","~")
        data=data[int(key)] if isinstance(data,list) else data[key]
    return data

class McpBridge:
    def __init__(self, store: ConfigStore, transport: McpTransport, is_running):
        self.store=store
        self.transport=transport
        self.is_running=is_running
        self._locks={}
        self._tasks=defaultdict(set)
        self._stopped=set()

    def resume_project(self, project_id: str):
        self._stopped.discard(project_id)

    def _allowed(self, ctx, role):
        return role in ROLES and ctx.project_id not in self._stopped and self.is_running(ctx.project_id)

    async def _owned(self, pid, operation):
        task=asyncio.create_task(operation())
        self._tasks[pid].add(task)
        try:
            return await task
        finally:
            self._tasks[pid].discard(task)
            if not self._tasks[pid]:
                self._tasks.pop(pid,None)

    async def list_tools(self, ctx, role: str, server_id: str|None=None) -> dict:
        if not self._allowed(ctx,role): return response("MCP access denied","denied")
        async def operation():
            results=[]
            config=self.store.load()
            async with self._locks.setdefault(ctx.project_id,asyncio.Lock()):
                if not self._allowed(ctx,role) or self.store.load().revision!=config.revision:
                    return response("Project or configuration changed; discover again","denied")
                for server in config.servers:
                    if server_id and server.id!=server_id: continue
                    rules={r.name:r for r in server.allowed_tools if role in r.roles}
                    if not server.enabled or not rules: continue
                    if not self._allowed(ctx,role): return response("Project stopped","denied")
                    try:
                        tools=await self.transport.describe(server)
                        for tool in tools:
                            if tool.name in rules:
                                results.append({"server_id":server.id,"name":tool.name,
                                    "description":tool.description,"inputSchema":tool.input_schema})
                    except TransportError as error:
                        results.append({"server_id":server.id,"error_code":error.code})
            # Discovery schemas must remain complete; reject oversize rather than truncate JSON.
            raw=json.dumps({"tools":results},ensure_ascii=False)
            if len(raw.encode())>MAX_CATALOG_BYTES:
                return response("Tool catalog too large; select one server and narrow its allowlist","catalog_too_large")
            return response(raw)
        return await self._owned(ctx.project_id,operation)

    async def call_tool(self, ctx, role: str, server_id: str, tool_name: str, arguments: dict) -> dict:
        if not self._allowed(ctx,role) or not isinstance(arguments,dict):
            return response("MCP access denied","denied")
        config=self.store.load()
        server=next((s for s in config.servers if s.id==server_id and s.enabled),None)
        rule=next((r for r in server.allowed_tools if r.name==tool_name and role in r.roles),None) if server else None
        if not rule: return response("Server or tool is not allowed","denied")
        if rule.profile=="http_url":
            try:
                for path in rule.target_pointers:
                    target=pointer(arguments,path)
                    parsed=urlsplit(target) if isinstance(target,str) else None
                    if (parsed is None or parsed.scheme not in {"http","https"} or not parsed.hostname
                        or parsed.username or parsed.password or ctx._http_blocked(target)):
                        return response("Target is outside the project scope","denied")
            except (ValueError,TypeError,KeyError,IndexError,AttributeError):
                return response("Required target is missing or invalid","denied")
        async def operation():
            async with self._locks.setdefault(ctx.project_id,asyncio.Lock()):
                if not self._allowed(ctx,role) or self.store.load().revision!=config.revision:
                    return response("Project or configuration changed; discover again","denied")
                started=time.monotonic()
                code=None
                try:
                    reply=await self.transport.invoke(server,tool_name,arguments)
                    code=reply.code
                    return response(reply.text,code if reply.is_error else None)
                except asyncio.CancelledError:
                    code="cancelled"
                    raise
                finally:
                    await emit(ctx.project_id,"mcp.call",{
                        "server_id":server_id,"tool_name":tool_name,"role":role,
                        "status":"error" if code else "ok","error_code":code,
                        "latency_ms":round((time.monotonic()-started)*1000)},run_id=ctx.run_id)
        return await self._owned(ctx.project_id,operation)

    async def cancel_project(self, project_id: str) -> None:
        self._stopped.add(project_id)
        tasks=list(self._tasks.get(project_id,()))
        for task in tasks: task.cancel()
        if tasks:
            done,pending=await asyncio.wait(tasks,timeout=5)
            for task in pending: task.cancel()
        if not self._tasks.get(project_id):
            self._locks.pop(project_id,None)

    async def close(self) -> None:
        await asyncio.gather(*(self.cancel_project(pid) for pid in list(self._tasks)))

