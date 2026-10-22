"""Shared skill creation/editing and workspace snapshots, using temporary data only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import project_skills as skills
from .agent_registry import AgentStore

DOC = "---\ndescription: Test skill usage\n---\n\n"


class SkillLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.builtin = self.root / "builtin"
        self.builtin.mkdir()
        for name in ("kali-kit", "recon-spiral"):
            folder = self.builtin / name
            folder.mkdir()
            (folder / "SKILL.md").write_text(DOC + "# Original " + name)
        self.custom = self.root / "data/skills"
        for key, value in (("SKILLS_ROOT", self.builtin), ("USER_SKILLS_ROOT", self.custom)):
            patcher = patch.object(skills, key, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def entry(self, name):
        return next(s for s in skills.skill_catalog()["skills"] if s["name"] == name)

    def test_create_persists_without_touching_repository_and_is_bindable(self):
        skills.create_skill("api-guide", DOC + "# API guide\nRead API documentation.")
        self.assertIn("api-guide", skills.skill_names())
        self.assertEqual(self.entry("api-guide")["content"], DOC + "# API guide\nRead API documentation.")
        self.assertTrue((self.custom / "api-guide/SKILL.md").is_file())
        self.assertFalse((self.builtin / "api-guide").exists())
        store = AgentStore(self.root / "agents.json")
        store.update_builtin("recon", skills=["api-guide"])
        self.assertEqual(store.builtin_cfg("recon")["skills"], ["api-guide"])
        self.assertNotIn("api-guide", skills.skill_names(objective="redteam"))

    def test_shared_edit_reaches_both_agents_but_existing_workspace_is_unchanged(self):
        skills.create_skill("api-guide", DOC + "# Version one")
        store = AgentStore(self.root / "agents.json")
        for role in ("recon", "web-exploit"):
            store.update_builtin(role, skills=["api-guide"])
        old = self.root / "running"
        skills.install_into_workspace(old, names=["api-guide"])
        before = self.entry("api-guide")
        skills.update_skill("api-guide", DOC + "# Version two", before["revision"])
        for role in ("recon", "web-exploit"):
            workspace = self.root / role
            skills.install_into_workspace(workspace, names=store.builtin_cfg(role)["skills"])
            self.assertEqual((workspace / ".agents/skills/api-guide/SKILL.md").read_text(), DOC + "# Version two")
        self.assertEqual((old / ".agents/skills/api-guide/SKILL.md").read_text(), DOC + "# Version one")

    def test_builtin_edit_preserves_resources_and_kali_override_is_not_regenerated(self):
        for name in ("recon-spiral", "kali-kit"):
            (self.builtin / name / "reference.txt").write_text("resource")
            before = self.entry(name)
            skills.update_skill(name, DOC + "# Edited " + name, before["revision"])
            workspace = self.root / ("workspace-" + name)
            skills.install_into_workspace(workspace, names=[name])
            folder = workspace / ".agents/skills" / name
            self.assertEqual((folder / "SKILL.md").read_text(), DOC + "# Edited " + name)
            self.assertEqual((folder / "reference.txt").read_text(), "resource")
            self.assertEqual((self.builtin / name / "SKILL.md").read_text(), DOC + "# Original " + name)

    def test_invalid_duplicate_missing_and_conflicting_writes_preserve_content(self):
        skills.create_skill("api-guide", DOC + "# Original")
        before = self.entry("api-guide")
        for name in ("../escape", "a/b", ".", "name.with.dot"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                skills.create_skill(name, DOC + "# Invalid")
        for content in ("", "   ", "x" * 300000, "---\ndescription: first\ndescription: second\n---\n# Duplicate", "# Missing description", "---\ndescription: []\n---\n# Invalid", "---\nname: another-name\ndescription: test\n---\n# Wrong name"):
            with self.subTest(length=len(content)), self.assertRaises(ValueError):
                skills.update_skill("api-guide", content, before["revision"])
        with self.assertRaises(FileExistsError):
            skills.create_skill("api-guide", DOC + "# Duplicate")
        with self.assertRaises(FileNotFoundError):
            skills.update_skill("missing", DOC + "# Update", before["revision"])
        with self.assertRaises(ValueError):
            skills.update_skill("api-guide", DOC + "# Stale", "wrong-revision")
        self.assertEqual(self.entry("api-guide")["content"], DOC + "# Original")

    def test_symlink_skill_cannot_write_outside_store(self):
        self.custom.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (self.custom / "escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            skills.create_skill("escape", DOC + "# Escape")
        self.assertFalse((outside / "SKILL.md").exists())

    def test_http_create_edit_conflict_and_invalid_input(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from ..api import routes
        app = FastAPI()
        app.include_router(routes.router)
        with TestClient(app) as client:
            result = client.post("/api/agent-skills", json={"name": "api-guide", "content": DOC + "# Guide"})
            self.assertEqual(result.status_code, 201)
            item = next(s for s in result.json()["skills"] if s["name"] == "api-guide")
            result = client.put("/api/agent-skills/api-guide", json={"content": DOC + "# Shared edit", "revision": item["revision"]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(client.put("/api/agent-skills/api-guide", json={"content": DOC + "# Stale", "revision": item["revision"]}).status_code, 409)
            self.assertEqual(client.post("/api/agent-skills", json={"name": "api-guide", "content": DOC + "# Duplicate"}).status_code, 409)
            self.assertEqual(client.post("/api/agent-skills", json={"name": "../bad", "content": DOC + "# Invalid"}).status_code, 400)
            self.assertEqual(client.put("/api/agent-skills/missing", json={"content": DOC + "# Missing", "revision": "x"}).status_code, 404)
