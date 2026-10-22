import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from .config import ServerConfig
from .transport import McpTransport, normalize_result

FIXTURE = Path(__file__).parent / "fixtures/echo_server.py"
def make_server(**kwargs):
    return ServerConfig(id="echo", transport="stdio", command=sys.executable,
                        args=[str(FIXTURE)], cwd=str(FIXTURE.parent), **kwargs)

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_and_nested_validation(self):
        t = McpTransport()
        defs = await t.describe(make_server())
        nested = next(x for x in defs if x.name == "nested_echo")
        self.assertIn("$defs", nested.input_schema)
        result = await t.invoke(make_server(), "nested_echo", {"item":{"value":12}})
        self.assertFalse(result.is_error, result)
        self.assertIn("12", result.text)
        bad = await t.invoke(make_server(), "nested_echo", {"item":{"value":"bad"}})
        self.assertEqual(bad.code, "invalid_arguments")

    async def test_error_and_timeout(self):
        t = McpTransport(call_timeout=0.15)
        self.assertTrue((await t.invoke(make_server(), "error", {})).is_error)
        reply = await t.invoke(make_server(), "slow", {"seconds":5})
        self.assertEqual(reply.code, "timeout", reply)

    async def test_cancel_reaps_process(self):
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d)/"pid"
            task = asyncio.create_task(McpTransport().invoke(
                make_server(env={"PID_FILE":str(pidfile)}), "slow", {"seconds":20}))
            for _ in range(100):
                if pidfile.exists(): break
                await asyncio.sleep(.02)
            self.assertTrue(pidfile.exists())
            pid = int(pidfile.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    async def test_http(self):
        await self._network_roundtrip("streamable_http")

    async def test_sse(self):
        await self._network_roundtrip("sse")

    async def test_program_name_is_resolved_from_environment_path(self):
        server = ServerConfig(id="program", transport="stdio", command="python",
            args=[str(FIXTURE)], env={"PATH":str(Path(sys.executable).parent)+":"+os.environ["PATH"]})
        result = await McpTransport().invoke(server, "echo", {"text":"program-name-ok"})
        self.assertFalse(result.is_error, result)
        self.assertIn("program-name-ok", result.text)

    async def _network_roundtrip(self, transport):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable,str(FIXTURE),str(port),transport],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    r,w = await asyncio.open_connection("127.0.0.1",port)
                    w.close(); await w.wait_closed()
                    break
                except OSError: await asyncio.sleep(.03)
            endpoint = "sse" if transport == "sse" else "mcp"
            server = ServerConfig(id="http",transport=transport,url=f"http://127.0.0.1:{port}/{endpoint}")
            t = McpTransport()
            self.assertIn("echo",[x.name for x in await t.describe(server)])
            result = await t.invoke(server,"echo",{"text":"hello"})
            self.assertFalse(result.is_error,result)
            self.assertIn("hello",result.text)
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_normalization_redaction_and_unicode_limit(self):
        out = normalize_result({"content":[{"type":"text","text":"secret-123"+"中"*40000},
                                             {"type":"image","data":"private"}],
                                "structuredContent":{"secret":"secret-123"}}, ["secret-123"])
        self.assertNotIn("secret-123",out.text)
        self.assertNotIn("private",out.text)
        self.assertLessEqual(len(out.text.encode()),65536+40)
        self.assertIn("[truncated]",out.text)
        self.assertTrue(normalize_result({"isError":True,"content":[]},[]).is_error)

