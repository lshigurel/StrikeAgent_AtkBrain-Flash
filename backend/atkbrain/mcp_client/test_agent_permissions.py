"""Server-level agent grants apply to discovery and direct calls, without tool allowlists."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ..agents.agent_registry import AgentStore
from .bridge import McpBridge
from .config import ConfigStore, ServerConfigPatch
from .transport import RemoteTool, ToolReply


class AgentPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.agents = AgentStore(root / "agents.json")
        self.agents.create_custom(agent_id="custom-parser", description="Parser", prompt="Parse text", tracks=["src"])
        self.store = ConfigStore(root / "mcp.json")
        self.server = dict(id="echo", enabled=True, transport="stdio", command="/bin/echo", cwd="/tmp")
        self.transport = SimpleNamespace(
            describe=AsyncMock(return_value=[RemoteTool("echo", "", {"type": "object"}), RemoteTool("other", "", {"type": "object"})]),
            invoke=AsyncMock(return_value=ToolReply("echo result")),
        )
        self.ctx = SimpleNamespace(project_id="p", run_id=None, _http_blocked=lambda url: None if url == "https://allowed.test/" else "outside")
        self.bridge = McpBridge(self.store, self.transport, lambda _: True)
        registry = patch("atkbrain.agents.agent_registry.STORE", self.agents)
        registry.start()
        self.addCleanup(registry.stop)
        audit = patch("atkbrain.mcp_client.bridge.emit", new_callable=AsyncMock)
        audit.start()
        self.addCleanup(audit.stop)

    def save(self, agents):
        self.store.save([ServerConfigPatch(**self.server, allowed_agents=agents)], self.store.load().revision)

    async def test_lead_requires_explicit_grant_and_loses_access_when_revoked(self):
        self.save([])
        catalog = await self.bridge.list_tools(self.ctx, "lead")
        self.assertFalse(catalog["is_error"])
        self.assertEqual(json.loads(catalog["content"][0]["text"])["tools"], [])
        self.assertEqual((await self.bridge.call_tool(self.ctx, "lead", "echo", "echo", {}))["code"], "denied")
        self.transport.describe.assert_not_called()
        self.transport.invoke.assert_not_called()
        self.save(["lead"])
        catalog = await self.bridge.list_tools(self.ctx, "lead")
        self.assertEqual([t["name"] for t in json.loads(catalog["content"][0]["text"])["tools"]], ["echo", "other"])
        result = await self.bridge.call_tool(self.ctx, "lead", "echo", "other", {})
        self.assertFalse(result["is_error"])
        self.assertEqual(result["content"][0]["text"], "echo result")
        self.save([])
        self.assertEqual((await self.bridge.call_tool(self.ctx, "lead", "echo", "echo", {}))["code"], "denied")

    async def test_lead_prompt_includes_only_explicitly_granted_mcp_tools(self):
        from ..agents.session import ProjectAgent
        agent = object.__new__(ProjectAgent)
        agent.scope = {}
        agent.workspace_dir = self.tmp.name
        agent.objective = "src"
        agent.brief = ""
        agent.project = {}
        agent.ctx = SimpleNamespace(project={})
        with patch("atkbrain.mcp_client.runtime.store", self.store), patch("atkbrain.agents.session.build_system_prompt", return_value="Lead instructions"):
            self.save(["lead"])
            self.assertIn("mcp_list_tools", agent._lead_system())
            self.assertIn("mcp_call_tool", agent._lead_system())
            self.save([])
            self.assertEqual(agent._lead_system(), "Lead instructions")

    async def test_selected_builtin_and_custom_agents_can_use_all_server_tools(self):
        self.save(["reverse", "custom-parser"])
        for agent in ("reverse", "custom-parser"):
            with self.subTest(agent=agent):
                catalog = await self.bridge.list_tools(self.ctx, agent)
                self.assertFalse(catalog["is_error"])
                self.assertEqual([t["name"] for t in json.loads(catalog["content"][0]["text"])["tools"]], ["echo", "other"])
                result = await self.bridge.call_tool(self.ctx, agent, "echo", "other", {})
                self.assertFalse(result["is_error"])
                self.assertEqual(result["content"][0]["text"], "echo result")

    async def test_unselected_and_revoked_agents_cannot_discover_or_call(self):
        self.save(["custom-parser"])
        catalog = await self.bridge.list_tools(self.ctx, "recon")
        self.assertEqual(json.loads(catalog["content"][0]["text"])["tools"], [])
        self.assertEqual((await self.bridge.call_tool(self.ctx, "recon", "echo", "echo", {}))["code"], "denied")
        self.save([])
        self.assertEqual((await self.bridge.call_tool(self.ctx, "custom-parser", "echo", "echo", {}))["code"], "denied")
        self.transport.describe.assert_not_called()
        self.transport.invoke.assert_not_called()

    async def test_disabled_deleted_and_unknown_agents_are_denied(self):
        self.save(["custom-parser", "reverse", "unknown"])
        self.agents.update_custom("custom-parser", enabled=False)
        self.agents.update_builtin("reverse", enabled=False)
        for agent in ("custom-parser", "reverse", "unknown", "supervisor", ""):
            with self.subTest(agent=agent):
                self.assertEqual((await self.bridge.list_tools(self.ctx, agent))["code"], "denied")
                self.assertEqual((await self.bridge.call_tool(self.ctx, agent, "echo", "echo", {}))["code"], "denied")
        self.agents.delete_custom("custom-parser")
        self.assertEqual((await self.bridge.call_tool(self.ctx, "custom-parser", "echo", "echo", {}))["code"], "denied")
        self.transport.invoke.assert_not_called()

    async def test_urls_in_nested_arguments_still_obey_project_scope(self):
        self.save(["recon"])
        for args in ({"url": "https://outside.test/"}, {"requests": [{"url": "https://outside.test/"}]}):
            self.assertEqual((await self.bridge.call_tool(self.ctx, "recon", "echo", "echo", args))["code"], "denied")
        self.transport.invoke.assert_not_called()
        self.assertFalse((await self.bridge.call_tool(self.ctx, "recon", "echo", "echo", {"url": "https://allowed.test/"}))["is_error"])

    async def test_permissions_roundtrip_without_exposing_secrets_or_tool_allowlist(self):
        self.server["env"] = {"TOKEN": "private-value"}
        self.save(["reverse", "custom-parser"])
        public = self.store.public_config()
        self.assertEqual(public["servers"][0]["allowed_agents"], ["reverse", "custom-parser"])
        self.assertNotIn("allowed_tools", public["servers"][0])
        self.assertNotIn("private-value", json.dumps(public))
        self.assertEqual(ConfigStore(self.store.path).get("echo").allowed_agents, ["reverse", "custom-parser"])

    async def test_legacy_tool_rules_do_not_filter_discovery_or_calls(self):
        self.store.save([ServerConfigPatch(**self.server, allowed_tools=[dict(name="echo", roles=["recon"], profile="pure")])], 0)
        self.assertEqual(self.store.get("echo").allowed_agents, ["recon"])
        result = await self.bridge.list_tools(self.ctx, "recon")
        self.assertEqual([t["name"] for t in json.loads(result["content"][0]["text"])["tools"]], ["echo", "other"])
        self.assertFalse((await self.bridge.call_tool(self.ctx, "recon", "echo", "other", {}))["is_error"])

    async def test_new_servers_default_to_no_agent_grants(self):
        self.store.save([ServerConfigPatch(**self.server)], 0)
        result = await self.bridge.list_tools(self.ctx, "recon")
        self.assertEqual(json.loads(result["content"][0]["text"])["tools"], [])
        self.assertEqual((await self.bridge.call_tool(self.ctx, "recon", "echo", "echo", {}))["code"], "denied")
        self.transport.describe.assert_not_called()
        self.transport.invoke.assert_not_called()

    async def test_connection_only_save_preserves_agent_grants_and_legacy_scope_rules(self):
        self.store.save([ServerConfigPatch(**self.server, allowed_agents=["reverse"], allowed_tools=[dict(name="echo", profile="http_url", target_pointers=["/url"])])], 0)
        self.store.save([ServerConfigPatch(**self.server)], 1)
        self.assertEqual(self.store.get("echo").allowed_agents, ["reverse"])
        result = await self.bridge.call_tool(self.ctx, "reverse", "echo", "echo", {})
        self.assertEqual(result["code"], "denied")

    async def test_legacy_client_resending_rules_cannot_reset_existing_agent_selection(self):
        rules = [dict(name="echo", roles=["recon"], profile="pure")]
        self.store.save([ServerConfigPatch(**self.server, allowed_agents=["custom-parser"], allowed_tools=rules)], 0)
        self.store.save([ServerConfigPatch(**self.server, allowed_tools=rules)], 1)
        self.assertEqual(self.store.get("echo").allowed_agents, ["custom-parser"])

    async def test_revocation_during_discovery_does_not_return_catalog(self):
        self.save(["recon"])
        async def revoke(server):
            self.save([])
            return [RemoteTool("echo", "", {"type": "object"})]
        self.transport.describe.side_effect = revoke
        self.assertEqual((await self.bridge.list_tools(self.ctx, "recon"))["code"], "denied")

    async def test_worker_prompt_tracks_custom_agent_grants(self):
        from ..agents.session import ProjectAgent
        agent = object.__new__(ProjectAgent)
        agent._roles = {"custom-parser": {"prompt": "Parse text"}}
        agent.workspace_dir = self.tmp.name
        agent.objective = "src"
        agent.project = {}
        agent.ctx = SimpleNamespace(project={})
        with patch("atkbrain.mcp_client.runtime.store", self.store):
            self.save(["custom-parser"])
            self.assertIn("mcp_list_tools", agent._role_system("custom-parser"))
            self.save([])
            self.assertNotIn("mcp_list_tools", agent._role_system("custom-parser"))
