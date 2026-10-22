import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
from ..config import settings
from ..main import api_auth_middleware
from .config import ConfigStore
from .transport import RemoteTool, TransportError
from .api import make_router

class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=ConfigStore(Path(self.tmp.name)/"mcp.json")
        self.transport=SimpleNamespace(describe=AsyncMock(return_value=[RemoteTool("echo","",{"type":"object"})]),
                                       invoke=AsyncMock())
        app=FastAPI()
        app.middleware("http")(api_auth_middleware)
        app.include_router(make_router(self.store,self.transport),prefix="/api")
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test",
                                     headers={"x-api-token":"test-only-token"})
        self.addAsyncCleanup(self.client.aclose)
        p=patch.object(settings,"api_token","test-only-token"); p.start(); self.addCleanup(p.stop)
        self.data={"revision":0,"servers":[{"id":"echo","transport":"stdio","command":"/bin/echo","cwd":"/tmp",
                                           "env":{"TOKEN":"do-not-return"}}]}

    async def test_authentication_and_password_change_gate(self):
        for method,path in (("GET",""),("PUT",""),("POST","/echo/test")):
            r=await self.client.request(method,"/api/settings/mcp"+path,headers={"x-api-token":""},json=self.data)
            self.assertEqual(r.status_code,401)
        with patch("atkbrain.auth.gate.session_from_request",AsyncMock(return_value={"user":{"must_change_password":1}})):
            r=await self.client.get("/api/settings/mcp")
            self.assertEqual(r.status_code,403)

    async def test_save_keep_clear_conflict_and_test_disabled(self):
        r=await self.client.put("/api/settings/mcp",json=self.data)
        self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn("do-not-return",r.text)
        self.transport.describe.assert_not_called()
        self.data["revision"]=1; self.data["servers"][0].pop("env")
        r=await self.client.put("/api/settings/mcp",json=self.data)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.store.get("echo").env["TOKEN"],"do-not-return")
        self.assertEqual((await self.client.put("/api/settings/mcp",json=self.data)).status_code,409)
        self.data["revision"]=2; self.data["servers"][0]["env"]={}
        await self.client.put("/api/settings/mcp",json=self.data)
        self.assertEqual(self.store.get("echo").env,{})
        r=await self.client.post("/api/settings/mcp/echo/test")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["tools"][0]["inputSchema"],{"type":"object"})
        self.transport.invoke.assert_not_called()

    async def test_invalid_and_protocol_error_do_not_echo_secrets(self):
        self.data["servers"][0]["command"]="relative/path"
        r=await self.client.put("/api/settings/mcp",json=self.data)
        self.assertEqual(r.status_code,422)
        self.assertNotIn("do-not-return",r.text)
        self.data["servers"][0]["command"]="/bin/echo"
        await self.client.put("/api/settings/mcp",json=self.data)
        self.transport.describe.side_effect=TransportError("protocol_error")
        r=await self.client.post("/api/settings/mcp/echo/test")
        self.assertEqual(r.json()["error_code"],"protocol_error")
        self.assertNotIn("do-not-return",r.text)


    async def test_remote_http_connection_saves_without_connecting_or_exposing_headers(self):
        self.data["servers"]=[{
            "id":"remote","name":"Remote MCP","enabled":False,"transport":"streamable_http",
            "url":"http://192.0.2.10:8011/api/mcp","command":"","args":[],"cwd":"",
            "allowed_tools":[],"headers_patch":{"X-Api-Token":"test-header-secret"}
        }]
        r=await self.client.put("/api/settings/mcp",json=self.data)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.store.get("remote").url,"http://192.0.2.10:8011/api/mcp")
        self.assertEqual(self.store.get("remote").headers,{"X-Api-Token":"test-header-secret"})
        self.assertEqual(r.json()["servers"][0]["header_keys"],["X-Api-Token"])
        self.assertNotIn("test-header-secret",r.text)
        self.transport.describe.assert_not_called()
        self.transport.invoke.assert_not_called()

    async def test_agent_grants_roundtrip_and_validation_remains_private(self):
        self.data["servers"][0]["allowed_agents"] = ["reverse", "custom-parser"]
        saved = await self.client.put("/api/settings/mcp", json=self.data)
        self.assertEqual(saved.status_code, 200, saved.text)
        loaded = await self.client.get("/api/settings/mcp")
        self.assertEqual(loaded.json()["servers"][0]["allowed_agents"], ["reverse", "custom-parser"])
        self.assertNotIn("allowed_tools", loaded.json()["servers"][0])
        self.assertNotIn("do-not-return", loaded.text)
        self.data["revision"] = 1
        for invalid in (["invalid id"], ["recon", "recon"], "recon"):
            self.data["servers"][0]["allowed_agents"] = invalid
            result = await self.client.put("/api/settings/mcp", json=self.data)
            self.assertEqual(result.status_code, 422)
            self.assertNotIn("do-not-return", result.text)
        self.assertEqual(self.store.get("echo").allowed_agents, ["reverse", "custom-parser"])
