"""Agent skill configuration, validation and runtime selection."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from .agent_registry import AgentStore
from .project_skills import skill_names, install_into_workspace
from .session import ProjectAgent


class AgentSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AgentStore(Path(self.tmp.name) / "agents.json")

    def test_builtin_skills_persist_and_other_agents_keep_defaults(self):
        self.store.update_builtin("recon", skills=["recon-fanout"])
        snap = AgentStore(self.store.path).snapshot()
        rows = {a["id"]: a for a in snap["builtin"]}
        self.assertEqual(rows["recon"]["skills"], ["recon-fanout"])
        self.assertIsNone(rows["web-exploit"]["skills"])
        projected = self.store.apply_to_agents({"recon": {}, "web-exploit": {}}, "flag")
        self.assertEqual(projected["recon"]["skills"], ["recon-fanout"])
        self.store.update_builtin("recon", skills=[])
        self.assertEqual(self.store.builtin_cfg("recon")["skills"], [])
        self.store.update_builtin("recon", skills=None)
        self.assertIsNone(self.store.builtin_cfg("recon")["skills"])

    def test_custom_skills_survive_edit_and_reset(self):
        self.store.create_custom(agent_id="api-hunter", description="API", prompt="Inspect API",
                                 tracks=["flag"], skills=["kali-kit"])
        self.store.update_custom("api-hunter", model="test-model")
        self.assertEqual(self.store.snapshot()["custom"][0]["skills"], ["kali-kit"])
        self.assertEqual(self.store.apply_to_agents({}, "flag")["api-hunter"]["skills"], ["kali-kit"])
        self.store.update_custom("api-hunter", skills=[])
        self.assertEqual(self.store.custom("api-hunter")["skills"], [])
        self.store.update_custom("api-hunter", skills=None)
        self.assertIsNone(self.store.snapshot()["custom"][0]["skills"])

    def test_reject_unknown_or_path_skills_without_saving(self):
        for value in (["missing"], ["../kali-kit"], "kali-kit", [1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.update_builtin("recon", skills=value)
        self.assertFalse(self.store.path.exists())

    def test_install_explicit_skills_including_empty_selection(self):
        workspace = Path(self.tmp.name) / "workspace"
        names = install_into_workspace(workspace, objective="flag", names=["recon-spiral"])
        self.assertEqual(names, ["recon-spiral"])
        self.assertTrue((workspace / ".agents/skills/recon-spiral/SKILL.md").is_file())
        self.assertEqual(install_into_workspace(workspace, objective="flag", names=[]), [])
        self.assertFalse((workspace / ".agents/skills/recon-spiral").exists())

    def test_runtime_passes_only_selected_skills_to_pi(self):
        agent = object.__new__(ProjectAgent)
        agent.workspace_dir = str(Path(self.tmp.name) / "workspace")
        agent.objective = "flag"
        agent._roles = {"recon": {"skills": ["recon-spiral"]}, "web-exploit": {"skills": []}}
        agent._project_skill_names = agent._write_skills()
        agent._pi_locks, agent._pi_pool, agent._sessions = {}, {}, []
        agent.project_id = "test"
        agent.ctx = SimpleNamespace(run_id="test", mark_activity=lambda: None)
        agent.model = "test"
        with patch("atkbrain.agents.session.PiSession") as pi:
            pi.return_value.start = AsyncMock()
            asyncio.run(agent._acquire_pi("recon", "test"))
            paths = pi.call_args.kwargs["skill_paths"]
            self.assertEqual([Path(p).name for p in paths], ["recon-spiral"])
            asyncio.run(agent._acquire_pi("web-exploit", "test"))
            self.assertEqual(pi.call_args.kwargs["skill_paths"], [])
            asyncio.run(agent._acquire_pi("lead", "test"))
            self.assertEqual({Path(p).name for p in pi.call_args.kwargs["skill_paths"]}, set(skill_names(objective="flag")))

    def test_removed_persisted_skill_does_not_block_project_startup(self):
        agent = object.__new__(ProjectAgent)
        agent.workspace_dir = str(Path(self.tmp.name) / "workspace")
        agent.objective = "flag"
        agent._roles = {"recon": {"skills": ["removed-skill", "kali-kit"]}}
        names = agent._write_skills()
        self.assertNotIn("removed-skill", names)
        self.assertIn("kali-kit", names)

    def test_api_catalog_and_patch(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from ..api import routes
        app = FastAPI()
        app.include_router(routes.router)
        with patch.object(routes, "agent_store", self.store), TestClient(app) as client:
            catalog = client.get("/api/agent-skills")
            self.assertEqual(catalog.status_code, 200)
            self.assertTrue(any(s["name"] == "kali-kit" and s["content"] for s in catalog.json()["skills"]))
            self.assertEqual(catalog.json()["defaults"]["flag"], skill_names(objective="flag"))
            result = client.patch("/api/agents/recon", json={"skills": []})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["builtin"][0]["skills"], [])
            self.assertEqual(client.patch("/api/agents/recon", json={"skills": ["../bad"]}).status_code, 400)
            result = client.patch("/api/agents/recon", json={"skills": None})
            self.assertIsNone(result.json()["builtin"][0]["skills"])
