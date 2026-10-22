import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from .config import ConfigStore, ServerConfigPatch
from .bridge import McpBridge
from .transport import RemoteTool, ToolReply

class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=ConfigStore(Path(self.tmp.name)/"config.json")
        self.patch=dict(id="echo",enabled=True,transport="stdio",command="/bin/echo",cwd="/tmp",
                        allowed_tools=[dict(name="echo",profile="pure")])
        self.store.save([ServerConfigPatch(**self.patch)],0)
        self.transport=SimpleNamespace(
            describe=AsyncMock(return_value=[RemoteTool("echo","",{"type":"object"})]),
            invoke=AsyncMock(return_value=ToolReply("ok")))
        self.running=True
        self.ctx=SimpleNamespace(project_id="p",run_id=None,
                                 _http_blocked=lambda url: None if url=="https://allowed.test/" else "outside")
        self.bridge=McpBridge(self.store,self.transport,lambda _:self.running)

    async def test_role_and_disabled_server_deny_before_connect(self):
        for role in ("lead","","unknown","finding-review"):
            out=await self.bridge.call_tool(self.ctx,role,"echo","echo",{})
            self.assertTrue(out["is_error"])
        self.patch["enabled"]=False
        self.store.save([ServerConfigPatch(**self.patch)],1)
        self.assertTrue((await self.bridge.list_tools(self.ctx,"recon"))["is_error"] is False)
        self.assertTrue((await self.bridge.call_tool(self.ctx,"recon","echo","echo",{}))["is_error"])
        self.transport.invoke.assert_not_called()
        self.transport.describe.assert_not_called()

    async def test_all_target_pointers_checked(self):
        self.patch["allowed_tools"]=[dict(name="echo",profile="http_url",target_pointers=["/url","/extra/url"])]
        self.store.save([ServerConfigPatch(**self.patch)],1)
        for args in ({},{"url":"https://allowed.test/","extra":{"url":"https://outside.test/"}}):
            self.assertTrue((await self.bridge.call_tool(self.ctx,"recon","echo","echo",args))["is_error"])
        self.transport.invoke.assert_not_called()
        self.assertFalse((await self.bridge.call_tool(self.ctx,"recon","echo","echo",
                         {"url":"https://allowed.test/","extra":{"url":"https://allowed.test/"}}))["is_error"])

    async def test_stop_while_waiting(self):
        entered=asyncio.Event()
        async def slow(*args):
            entered.set()
            await asyncio.sleep(30)
        self.transport.invoke.side_effect=slow
        a=asyncio.create_task(self.bridge.call_tool(self.ctx,"recon","echo","echo",{}))
        await entered.wait()
        b=asyncio.create_task(self.bridge.call_tool(self.ctx,"recon","echo","echo",{}))
        await asyncio.sleep(.02)
        await self.bridge.cancel_project("p")
        await asyncio.gather(a,b,return_exceptions=True)
        self.assertEqual(self.transport.invoke.call_count,1)
        self.assertTrue((await self.bridge.call_tool(self.ctx,"recon","echo","echo",{}))["is_error"])

    async def test_revision_changed_while_waiting(self):
        entered=asyncio.Event(); release=asyncio.Event()
        async def slow(*args):
            entered.set(); await release.wait(); return ToolReply("ok")
        self.transport.invoke.side_effect=slow
        a=asyncio.create_task(self.bridge.call_tool(self.ctx,"recon","echo","echo",{}))
        await entered.wait()
        b=asyncio.create_task(self.bridge.call_tool(self.ctx,"recon","echo","echo",{}))
        await asyncio.sleep(.02)
        self.store.save([ServerConfigPatch(**self.patch)],1)
        release.set()
        first,second=await asyncio.gather(a,b)
        self.assertFalse(first["is_error"])
        self.assertTrue(second["is_error"])
        self.assertEqual(self.transport.invoke.call_count,1)

    async def test_project_isolation(self):
        other=SimpleNamespace(project_id="q",run_id=None)
        await self.bridge.cancel_project("p")
        result=await self.bridge.call_tool(other,"recon","echo","echo",{})
        self.assertFalse(result["is_error"])

    async def test_rest_and_mcp_have_same_denial(self):
        import httpx
        from fastapi import FastAPI
        from ..agents import mcp_http
        from . import runtime
        app=FastAPI()
        app.include_router(mcp_http.router)
        with patch.dict(mcp_http._CTX,{"p":self.ctx}), patch.object(runtime,"bridge",self.bridge):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                definitions=(await client.get("/projects/p/agent-tools")).json()["tools"]
                self.assertIn("mcp_call_tool",[t["name"] for t in definitions])
                args={"server_id":"echo","tool_name":"echo","arguments":{}}
                rest=await client.post("/projects/p/agent-tools/mcp_call_tool",json=args,headers={"x-atkbrain-role":"lead"})
                rpc=await client.post("/projects/p/mcp",json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mcp_call_tool","arguments":args}},headers={"x-atkbrain-role":"lead"})
                self.assertEqual(rest.json()["text"],rpc.json()["result"]["content"][0]["text"])
                self.assertTrue(rest.json()["is_error"])
                self.assertTrue(rpc.json()["result"]["isError"])

    async def test_project_serialization_and_audit_metadata_only(self):
        inflight=0; maximum=0
        async def slow(*args):
            nonlocal inflight,maximum
            inflight+=1; maximum=max(maximum,inflight)
            await asyncio.sleep(.02)
            inflight-=1
            return ToolReply("sensitive-result")
        self.transport.invoke.side_effect=slow
        with patch("atkbrain.mcp_client.bridge.emit",new_callable=AsyncMock) as emit:
            await asyncio.gather(*(self.bridge.call_tool(self.ctx,"recon","echo","echo",
                                   {"secret":"sensitive-arg"}) for _ in range(3)))
            self.assertEqual(maximum,1)
            self.assertNotIn("sensitive",str(emit.call_args_list))

