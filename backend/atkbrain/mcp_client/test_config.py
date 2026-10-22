import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from .config import ConfigStore, ConfigConflict, ServerConfigPatch

def server(**kwargs):
    return ServerConfigPatch(id="echo", transport="stdio", command="/usr/bin/python3",
                             cwd="/tmp", **kwargs)

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "private" / "mcp.json"
        self.store = ConfigStore(self.path)

    def test_atomic_roundtrip(self):
        saved = self.store.save([server()], 0)
        self.assertEqual(saved.revision, 1)
        self.assertFalse(saved.servers[0].enabled)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_keep_and_clear_secrets(self):
        self.store.save([server(env={"TOKEN":"secret-123"})], 0)
        self.store.save([server(enabled=True)], 1)
        self.assertEqual(self.store.get("echo").env, {"TOKEN":"secret-123"})
        self.assertNotIn("secret-123", json.dumps(self.store.public_config()))
        self.assertEqual(self.store.public_config()["servers"][0]["env_keys"], ["TOKEN"])
        self.store.save([server(env={})], 2)
        self.assertEqual(self.store.get("echo").env, {})

    def test_reject_invalid(self):
        cases = [
            dict(id="a", transport="stdio", command="", cwd="/tmp"),
            dict(id="a", transport="streamable_http", url="ftp://example.com/mcp"),
            dict(id="a", transport="streamable_http", url="https://user:pass@example.com/mcp"),
            dict(id="a", transport="stdio", command="/bin/echo", cwd="/tmp",
                 allowed_tools=[{"name":"get","profile":"http_url","target_pointers":[]}]),
            dict(id="a", transport="stdio", command="/bin/echo", cwd="/tmp",
                 allowed_tools=[{"name":"get","roles":["lead"]}]),
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                ServerConfigPatch(**data)
        with self.assertRaises(ValueError):
            self.store.save([server(), server()], 0)

    def test_conflict(self):
        self.store.save([server()], 0)
        before = self.path.read_bytes()
        with self.assertRaises(ConfigConflict):
            self.store.save([], 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_replace_preserves_file(self):
        self.store.save([server()], 0)
        before = self.path.read_bytes()
        with patch("os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.store.save([], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_file_not_overwritten(self):
        self.path.parent.mkdir()
        self.path.write_text("{")
        with self.assertRaises(ValueError):
            self.store.save([], 0)
        self.assertEqual(self.path.read_text(), "{")


class ConnectionFormTests(unittest.TestCase):
    def test_display_name_bare_program_and_default_cwd(self):
        config = ServerConfigPatch(id="local", name="本机工具", transport="stdio", command="python3")
        self.assertEqual(config.name, "本机工具")
        self.assertEqual(config.cwd, str(Path.home()))

    def test_sse_uses_http_connection_fields(self):
        config = ServerConfigPatch(id="sse", transport="sse", url="http://127.0.0.1:8765/sse")
        self.assertEqual(config.transport, "sse")
        with self.assertRaises(ValidationError):
            ServerConfigPatch(id="sse", transport="sse", url="ftp://example.com/sse")

    def test_key_updates_keep_other_saved_secrets_and_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory)/"mcp.json")
            rules = [{"name":"echo","roles":["recon"],"profile":"pure"}]
            store.save([server(env={"TOKEN":"keep-secret","OLD":"remove"},allowed_tools=rules)],0)
            store.save([server(env_patch={"NEW":"new-secret","OLD":None},allowed_tools=rules)],1)
            self.assertEqual(store.get("echo").env, {"TOKEN":"keep-secret","NEW":"new-secret"})
            self.assertEqual(store.get("echo").allowed_tools[0].name,"echo")
            self.assertNotIn("keep-secret",json.dumps(store.public_config()))

    def test_cannot_mix_map_replacement_and_key_patch(self):
        with self.assertRaises(ValidationError):
            server(env={}, env_patch={"TOKEN":"value"})

class RemoteHttpConfigTests(unittest.TestCase):
    def test_remote_http_and_https_services_supported_for_both_transports(self):
        for transport in ("streamable_http","sse"):
            for url in ("http://192.0.2.10:8011/api/mcp","https://mcp.example.test/mcp"):
                with self.subTest(transport=transport,url=url):
                    config=ServerConfigPatch(id="remote",transport=transport,url=url)
                    self.assertEqual(config.url,url)
