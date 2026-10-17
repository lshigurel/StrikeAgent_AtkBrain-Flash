"""Web 控制台 Agent 注册表：启停、自定义角色和投影。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .agent_registry import AgentStore
from . import agent_registry
from .prompts import _builtin_subagents, default_fanout_roles


class AgentRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AgentStore(Path(self.tmp.name) / "agents.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_marks_core(self) -> None:
        snap = self.store.snapshot()
        by_id = {row["id"]: row for row in snap["builtin"]}
        self.assertIn("flag", by_id["recon"]["core"])
        self.assertIn("src", by_id["src-hunt"]["core"])
        self.assertTrue(by_id["web-exploit"]["enabled"])
        self.assertEqual(snap["limits"]["per_project"], 4)

    def test_custom_agent_only_in_selected_tracks(self) -> None:
        self.store.create_custom(
            agent_id="api-hunter",
            description="API hunter",
            prompt="Hunt API authorization differences.",
            tracks=["redteam", "src"],
        )
        red = self.store.apply_to_agents(_builtin_subagents("redteam"), "redteam")
        src = self.store.apply_to_agents(_builtin_subagents("src"), "src")
        flag = self.store.apply_to_agents(_builtin_subagents("flag"), "flag")
        self.assertIn("api-hunter", red)
        self.assertIn("api-hunter", src)
        self.assertNotIn("api-hunter", flag)
        self.assertEqual(red["api-hunter"]["description"], "API hunter")

    def test_optional_role_can_be_disabled(self) -> None:
        self.store.update_builtin("privesc", enabled=False)
        red = self.store.apply_to_agents(_builtin_subagents("redteam"), "redteam")
        self.assertNotIn("privesc", red)

    def test_core_role_cannot_be_disabled(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_builtin("web-exploit", enabled=False)
        with self.assertRaises(ValueError):
            self.store.update_builtin("web-exploit", default=False)

    def test_default_extra_roles(self) -> None:
        self.store.create_custom(
            agent_id="api-hunter",
            description="API hunter",
            prompt="Hunt APIs.",
            tracks=["redteam"],
            default=True,
        )
        self.assertEqual(self.store.default_extra_roles("redteam"), ["api-hunter"])
        self.assertEqual(self.store.default_extra_roles("flag"), [])

    def test_invalid_custom_id(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create_custom(
                agent_id="Web",
                description="bad",
                prompt="bad",
                tracks=["redteam"],
            )
        with self.assertRaises(ValueError):
            self.store.create_custom(
                agent_id="recon",
                description="collision",
                prompt="collision",
                tracks=["redteam"],
            )

    def test_persists_and_reloads(self) -> None:
        self.store.create_custom(
            agent_id="api-hunter",
            description="API hunter",
            prompt="Hunt APIs.",
            tracks=["redteam"],
        )
        reopened = AgentStore(self.store.path)
        self.assertIsNotNone(reopened.custom("api-hunter"))

    def test_custom_agent_reaches_supervisor_and_fanout(self) -> None:
        from ..engine.ai_supervisor import supervisor_system_prompt

        self.store.create_custom(
            agent_id="api-hunter",
            description="API hunter",
            prompt="Hunt APIs.",
            tracks=["redteam"],
            default=True,
        )
        old = agent_registry.STORE
        agent_registry.STORE = self.store
        try:
            text = supervisor_system_prompt("redteam")
            fanout = default_fanout_roles("redteam")
        finally:
            agent_registry.STORE = old
        self.assertIn("api-hunter", text)
        self.assertIn("api-hunter", fanout)


if __name__ == "__main__":
    unittest.main()
