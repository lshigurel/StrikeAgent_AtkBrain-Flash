"""二次验证 / 红队评级：入库门闩、pending 过滤、开关缺键当开。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class GateTests(unittest.TestCase):
    def test_merged_duplicate_title_is_not_a_new_vuln(self) -> None:
        from ..graph.model import is_merged_duplicate_title
        self.assertTrue(is_merged_duplicate_title("（重复节点，已并入 vuln:crossdomain-wildcard）通配策略"))
        self.assertFalse(is_merged_duplicate_title("crossdomain.xml 通配 domain=*"))

    def test_first_ingest_empty_ok(self) -> None:
        from ..graph.model import secondary_review_error
        self.assertIsNone(secondary_review_error(False, None, None))
        self.assertIsNone(secondary_review_error(False, "", "  "))

    def test_secondary_only_needs_rationale(self) -> None:
        from ..graph.model import secondary_review_error
        self.assertIsNotNone(secondary_review_error(True, None, "太短"))
        why = "换通道重放 PoC，对照首次回显，命令未打成，二次确认仍是任意文件写而非 RCE。"
        self.assertGreaterEqual(len(why), 40)
        self.assertIsNone(secondary_review_error(True, None, why))
        self.assertIsNone(secondary_review_error(True, "", why))

    def test_rating_only_needs_rationale(self) -> None:
        from ..graph.model import secondary_review_error
        self.assertIsNotNone(secondary_review_error(False, "high", "高危"))
        why = "任意文件读默认中危：可拉取配置但无命令执行回显，按四级表评 medium 而不是高危。"
        self.assertGreaterEqual(len(why), 40)
        self.assertIsNone(secondary_review_error(False, "medium", why))
        self.assertIsNone(secondary_review_error(False, "中危", why))

    def test_both_still_require_three(self) -> None:
        from ..graph.model import secondary_review_error
        why = "独立重放并对照回显后仍可写任意文件，按四级表中危，不抬成高危，也不压成低危处理。"
        self.assertGreaterEqual(len(why), 40)
        self.assertIsNotNone(secondary_review_error(True, "high", "短"))
        self.assertIsNone(secondary_review_error(True, "medium", why))

    def test_pending_stays_pending_when_rating_claims_it_left_status(self) -> None:
        from ..graph.verify import merge_verification_status
        why = "本条只做 NVD CVSS 3.1 基础分，本轮未再动手二次验证，故二次验证状态保持原状不改。"
        status, sec = merge_verification_status("pending", False, "excluded", False, why)
        self.assertEqual(status, "pending")
        self.assertFalse(sec)

    def test_failed_secondary_cannot_become_verified(self) -> None:
        from ..graph.verify import merge_verification_status
        why = "二次验证换了三条独立通道，再次看到同样的属性回显。"
        status, sec = merge_verification_status("excluded", False, "verified", True, why)
        self.assertEqual(status, "excluded")
        self.assertFalse(sec)

    def test_blocked_recheck_is_not_a_failure(self) -> None:
        from ..graph.verify import is_real_secondary_failure, merge_verification_status
        why = (
            "本回合二次验证失败：run_cmd 与 http_request 全部回了"
            "「本条意图已经写回，这次会话不再改打别的类型。」"
            "因此没有看到原样落地，也没有新的独立观测。"
        )
        self.assertFalse(is_real_secondary_failure(why))
        status, sec = merge_verification_status("pending", False, "excluded", False, why)
        self.assertEqual(status, "pending")
        self.assertFalse(sec)

    def test_review_role_can_recheck_after_intent_closed(self) -> None:
        import asyncio
        from types import SimpleNamespace
        from ..engine.intent_gate import gate_intent, tool_caller_role

        ctx = SimpleNamespace(intent_closed=True)

        async def go():
            blocked = await gate_intent(ctx)
            token = tool_caller_role.set("finding-review:f_x:secondary")
            try:
                opened = await gate_intent(ctx)
            finally:
                tool_caller_role.reset(token)
            return blocked, opened

        blocked, opened = asyncio.run(go())
        self.assertIn("本条意图已经写回", blocked or "")
        self.assertIsNone(opened)

    def test_writing_a_finding_does_not_lock_the_hunt_session(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "agents" / "tools.py").read_text(encoding="utf-8")
        self.assertNotIn("ctx.intent_closed = True", text)

    def test_real_secondary_failure_sticks(self) -> None:
        from ..graph.verify import merge_verification_status
        why = "本回合二次验证失败：两条新通道都没有再看到同样的反射回显。"
        status, sec = merge_verification_status("pending", False, "excluded", False, why)
        self.assertEqual(status, "excluded")
        self.assertFalse(sec)
        status, sec = merge_verification_status(status, sec, "verified", True, "后来又说成功了")
        self.assertEqual(status, "excluded")
        self.assertFalse(sec)

    def test_pending_becomes_verified_only_after_real_recheck(self) -> None:
        from ..graph.verify import merge_verification_status
        why = "换了两条新观测通道，再次看到同样的异常栈。"
        status, sec = merge_verification_status("pending", False, None, True, why)
        self.assertEqual(status, "verified")
        self.assertTrue(sec)

    def test_rationale_without_intent_rejected(self) -> None:
        from ..graph.model import secondary_review_error
        self.assertIsNotNone(secondary_review_error(False, None, "x" * 50))

    def test_exclude_closes_without_pass(self) -> None:
        from ..graph.model import secondary_review_error
        why = "换通道重放后没有再看到同样的文件内容，这一条排除。排除只表示本条没被二次证明，不是否定这类漏洞。"
        self.assertGreaterEqual(len(why), 40)
        self.assertIsNone(secondary_review_error(False, None, why, status="excluded"))
        self.assertIsNotNone(secondary_review_error(True, None, why, status="excluded"))
        self.assertIsNotNone(secondary_review_error(False, None, "太短", status="excluded"))


class NeedTests(unittest.TestCase):
    def test_need_by_flags(self) -> None:
        from ..graph.model import finding_review_need
        row = {"secondary_verified": 0, "redteam_rating": None}
        self.assertEqual(finding_review_need(row, want_secondary=True, want_rating=True), "both")
        self.assertEqual(finding_review_need(row, want_secondary=True, want_rating=False), "secondary")
        self.assertEqual(finding_review_need(row, want_secondary=False, want_rating=True), "rating")
        self.assertIsNone(finding_review_need(row, want_secondary=False, want_rating=False))
        done = {"secondary_verified": 1, "redteam_rating": "high"}
        self.assertIsNone(finding_review_need(done, want_secondary=True, want_rating=True))
        half = {"secondary_verified": 1, "redteam_rating": None}
        self.assertEqual(finding_review_need(half, want_secondary=True, want_rating=True), "rating")
        rated = {"secondary_verified": 0, "redteam_rating": "low"}
        self.assertEqual(finding_review_need(rated, want_secondary=True, want_rating=True), "secondary")
        excluded = {"secondary_verified": 0, "redteam_rating": None, "verification_status": "excluded"}
        self.assertEqual(finding_review_need(excluded, want_secondary=True, want_rating=True), "rating")
        excluded_rated = {"secondary_verified": 0, "redteam_rating": "low", "verification_status": "excluded"}
        self.assertIsNone(finding_review_need(excluded_rated, want_secondary=True, want_rating=True))

    def test_attempt_cap_keeps_the_rest_of_the_queue(self) -> None:
        from ..review.jobs import note_review_attempt, review_attempt_open
        book: dict[tuple[str, str], int] = {}
        self.assertTrue(review_attempt_open(book, "f1", "secondary"))
        for _ in range(3):
            note_review_attempt(book, "f1", "secondary")
        self.assertFalse(review_attempt_open(book, "f1", "secondary"))
        self.assertTrue(review_attempt_open(book, "f2", "secondary"))
        self.assertTrue(review_attempt_open(book, "f1", "rating"))


class FlagTests(unittest.TestCase):
    def test_missing_keys_default_on(self) -> None:
        from ..review import flags as fl
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "proxy-settings.json"
            with patch.object(fl, "_settings_path", lambda: p):
                got = fl.get_review_flags()
                self.assertTrue(got["secondary_verify"])
                self.assertTrue(got["redteam_rating"])
                p.write_text("{}", encoding="utf-8")
                got = fl.get_review_flags()
                self.assertTrue(got["secondary_verify"])
                self.assertTrue(got["redteam_rating"])
                p.write_text(json.dumps({"finding_secondary_verify": False}), encoding="utf-8")
                got = fl.get_review_flags()
                self.assertFalse(got["secondary_verify"])
                self.assertTrue(got["redteam_rating"])

    def test_set_writes_keys(self) -> None:
        from ..review import flags as fl
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "proxy-settings.json"

            def fake_merge(updates):
                data = {}
                if p.is_file():
                    data = json.loads(p.read_text(encoding="utf-8") or "{}")
                data.update(updates)
                p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            with patch.object(fl, "_settings_path", lambda: p), patch.object(fl, "_merge_settings", fake_merge):
                out = fl.set_review_flags(secondary_verify=False, redteam_rating=True)
                self.assertFalse(out["secondary_verify"])
                data = json.loads(p.read_text(encoding="utf-8"))
                self.assertFalse(data["finding_secondary_verify"])
                self.assertTrue(data["finding_redteam_rating"])


class PendingFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_flags_split_pending(self) -> None:
        from ..graph import store as gstore

        rows = [
            {
                "id": "f1", "project_id": "p1", "node_key": "n1", "severity": "high",
                "category": "xss", "title": "stored xss", "description": "", "evidence": "e",
                "poc_curl": "", "poc_python": "", "cvss": None, "created_at": 1,
                "verification_status": "verified", "verified_at": 1,
                "proof_type": None, "proof_canary": None, "proof_url": None, "proof_detail": None,
                "secondary_verified": 0, "redteam_rating": None, "redteam_rating_rationale": None,
                "report_summary": None, "report_impact": None, "report_rating": None,
                "report_repro": None, "report_fix": None,
            },
            {
                "id": "f2", "project_id": "p1", "node_key": "n2", "severity": "medium",
                "category": "sqli", "title": "sqli", "description": "", "evidence": "e",
                "poc_curl": "", "poc_python": "", "cvss": None, "created_at": 2,
                "verification_status": "verified", "verified_at": 2,
                "proof_type": None, "proof_canary": None, "proof_url": None, "proof_detail": None,
                "secondary_verified": 1, "redteam_rating": None, "redteam_rating_rationale": "x" * 50,
                "report_summary": None, "report_impact": None, "report_rating": None,
                "report_repro": None, "report_fix": None,
            },
            {
                "id": "f3", "project_id": "p1", "node_key": "n3", "severity": "low",
                "category": "info", "title": "banner", "description": "", "evidence": "e",
                "poc_curl": "", "poc_python": "", "cvss": None, "created_at": 3,
                "verification_status": "rejected", "verified_at": None,
                "proof_type": None, "proof_canary": None, "proof_url": None, "proof_detail": None,
                "secondary_verified": 0, "redteam_rating": None, "redteam_rating_rationale": None,
                "report_summary": None, "report_impact": None, "report_rating": None,
                "report_repro": None, "report_fix": None,
            },
        ]

        async def fake_fetchall(sql, params=()):
            return list(rows)

        with patch.object(gstore.db, "fetchall", fake_fetchall), \
             patch("atkbrain.projects.get_project", new=AsyncMock(return_value={"config": {}})):
            both = await gstore.findings_pending_review("p1", want_secondary=True, want_rating=True)
            ids = {x["id"]: x["_review_mode"] for x in both}
            self.assertEqual(ids["f1"], "both")
            self.assertEqual(ids["f2"], "rating")
            self.assertNotIn("f3", ids)
            sec = await gstore.findings_pending_review("p1", want_secondary=True, want_rating=False)
            self.assertEqual([x["id"] for x in sec], ["f1"])
            self.assertEqual(sec[0]["_review_mode"], "secondary")
            rate = await gstore.findings_pending_review("p1", want_secondary=False, want_rating=True)
            self.assertEqual({x["id"] for x in rate}, {"f1", "f2"})
            none = await gstore.findings_pending_review("p1", want_secondary=False, want_rating=False)
            self.assertEqual(none, [])


class JobBusyTests(unittest.TestCase):
    def test_same_mode_conflicts(self) -> None:
        from ..review import jobs
        jobs._JOBS.clear()
        jobs._ACTIVE.clear()
        jobs.claim("p", "f", "secondary")
        with self.assertRaises(jobs.ReviewBusy):
            jobs.claim("p", "f", "secondary")
        with self.assertRaises(jobs.ReviewBusy):
            jobs.claim("p", "f", "both")
        jobs.claim("p", "f", "rating")
        jobs._JOBS.clear()
        jobs._ACTIVE.clear()

    def test_queued_is_not_running(self) -> None:
        from ..review import jobs
        jobs._JOBS.clear()
        jobs._ACTIVE.clear()
        jobs.claim("p", "f1", "secondary")
        state = jobs.review_state("p", "f1")
        self.assertEqual(state["secondary"]["status"], "queued")
        self.assertNotIn("secondary", jobs.reviewing_modes("p", "f1"))
        jid = jobs._ACTIVE[("p", "f1", "secondary")]
        jobs.mark_running(jid, "已拉起 Pi，等待模型")
        self.assertEqual(jobs.review_state("p", "f1")["secondary"]["status"], "running")
        self.assertIn("secondary", jobs.reviewing_modes("p", "f1"))
        jobs.note_review_beat(jid, "正在调用 http_request")
        jobs.pulse_review(jid)
        self.assertEqual(jobs._JOBS[jid]["detail"], "正在调用 http_request")
        jobs._JOBS[jid]["detail"] = "等待模型回复"
        jobs.pulse_review(jid)
        self.assertEqual(jobs._JOBS[jid]["detail"], "等待模型回复")
        jobs.claim("p", "f1", "rating")
        self.assertEqual(jobs.review_state("p", "f1")["rating"]["status"], "queued")
        self.assertNotIn("rating", jobs.reviewing_modes("p", "f1"))
        jobs._JOBS.clear()
        jobs._ACTIVE.clear()


if __name__ == "__main__":
    unittest.main()
