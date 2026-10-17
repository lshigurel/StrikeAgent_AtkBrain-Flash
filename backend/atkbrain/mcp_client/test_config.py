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
            dict(id="a", transport="stdio", command="python", cwd="/tmp"),
            dict(id="a", transport="streamable_http", url="http://example.com/mcp"),
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

