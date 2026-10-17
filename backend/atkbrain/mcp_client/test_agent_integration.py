"""Real HTTP -> existing Pi extension -> bridge -> local MCP fixtures, without a model."""
import asyncio
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uvicorn
from fastapi import FastAPI
from .config import ConfigStore, ServerConfigPatch
from .bridge import McpBridge
from .transport import McpTransport
from .test_transport import FIXTURE

ROOT=Path(__file__).resolve().parents[3]

class AgentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pi_extension_stdio_and_http(self):
        node=os.environ.get("NODE_BIN","node")
        package=os.environ.get("PI_PACKAGE_ROOT")
        if not package:
            self.skipTest("Set PI_PACKAGE_ROOT to the installed Pi node_modules directory")
        with tempfile.TemporaryDirectory() as directory:
            pidfile=Path(directory)/"pid"
            calllog=Path(directory)/"calls"
            # Reserve and hand a socket to uvicorn, avoiding a port selection race.
            sock=socket.socket()
            sock.bind(("127.0.0.1",0))
            port=sock.getsockname()[1]
            with socket.socket() as probe:
                probe.bind(("127.0.0.1",0))
                mcp_port=probe.getsockname()[1]
            remote=await asyncio.create_subprocess_exec(sys.executable,str(FIXTURE),str(mcp_port),
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            store=ConfigStore(Path(directory)/"config.json")
            rules=[dict(name="echo",profile="pure"),dict(name="nested_echo",profile="pure")]
            store.save([
                ServerConfigPatch(id="stdio",enabled=True,transport="stdio",command=sys.executable,
                    args=[str(FIXTURE)],cwd=str(FIXTURE.parent),allowed_tools=rules,
                    env={"PID_FILE":str(pidfile),"CALL_LOG":str(calllog)}),
                ServerConfigPatch(id="http",enabled=True,transport="streamable_http",
                    url=f"http://127.0.0.1:{mcp_port}/mcp",allowed_tools=rules)],0)
            bridge=McpBridge(store,McpTransport(),lambda _:True)
            ctx=SimpleNamespace(project_id="fixture",run_id=None)
            from ..agents import mcp_http
            from . import runtime
            app=FastAPI()
            app.include_router(mcp_http.router,prefix="/api")
            server=uvicorn.Server(uvicorn.Config(app,log_level="critical",lifespan="off"))
            task=None
            try:
                for _ in range(150):
                    try:
                        _,writer=await asyncio.open_connection("127.0.0.1",mcp_port)
                        writer.close();await writer.wait_closed();break
                    except OSError: await asyncio.sleep(.02)
                with patch.dict(mcp_http._CTX,{"fixture":ctx}),patch.object(runtime,"bridge",bridge),patch("atkbrain.mcp_client.bridge.emit",new_callable=AsyncMock):
                    task=asyncio.create_task(server.serve(sockets=[sock]))
                    for _ in range(100):
                        if server.started:break
                        await asyncio.sleep(.02)
                    process=await asyncio.create_subprocess_exec(node,str(ROOT/"pi/tests/mcp-extension-smoke.mjs"),
                        cwd=str(ROOT),env={**os.environ,"PI_PACKAGE_ROOT":package,
                            "ATKBRAIN_TOOLS_BASE":f"http://127.0.0.1:{port}",
                            "ATKBRAIN_PROJECT_ID":"fixture","ATKBRAIN_PI_ROLE":"recon",
                            "ATKBRAIN_API_TOKEN":""},
                        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    out,err=await asyncio.wait_for(process.communicate(),40)
                    self.assertEqual(process.returncode,0,err.decode()+out.decode())
                    self.assertIn("extension smoke passed",out.decode())
                    self.assertEqual(calllog.read_text().splitlines(),["echo"])
                    await bridge.cancel_project("fixture")
                    with self.assertRaises(ProcessLookupError):os.kill(int(pidfile.read_text()),0)
            finally:
                await bridge.close()
                server.should_exit=True
                if task:await asyncio.wait_for(task,5)
                sock.close()
                remote.terminate()
                await asyncio.wait_for(remote.wait(),5)

