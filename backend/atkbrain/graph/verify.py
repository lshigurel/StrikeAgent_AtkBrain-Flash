"""发现入库：有真实性证据才标已验证；二次验证与红队评级单独记。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import CRITICAL_CATEGORIES, FindingIn, SEVERITY_ORDER, normalize_severity

# 崩溃/可用性类：可上报、可见，但不能当「已验证可利用资产」去收口。
NON_EXPLOIT_FINDING_CATS = frozenset({
    "availability", "dos", "crash", "error_handling", "misconfig",
})


def is_non_exploit_finding_category(category: str | None) -> bool:
    return str(category or "").strip().lower() in NON_EXPLOIT_FINDING_CATS


def finding_has_authenticity_proof(finding: FindingIn) -> bool:
    """是否有可核真实性的材料：证据、PoC 或证明字段。"""
    for v in (
        finding.evidence, finding.poc_curl, finding.poc_python,
        finding.proof_detail, finding.proof_canary, finding.proof_url,
    ):
        if str(v or "").strip():
            return True
    return False


@dataclass
class VerifyResult:
    status: str
    reason: str
    proof_type: str | None = None
    proof_canary: str | None = None
    proof_url: str | None = None
    proof_detail: str | None = None


def is_high_severity(severity: str | None, category: str | None) -> bool:
    """高危/严重：导出 PoC 时只用上报原文，不合成利用模板。"""
    sev = normalize_severity(category, severity)
    if SEVERITY_ORDER.get(sev, 0) >= SEVERITY_ORDER["high"]:
        return True
    return bool(category and category.lower() in CRITICAL_CATEGORIES)


def infer_canary(finding: FindingIn) -> str | None:
    raw = (finding.proof_canary or "").strip()
    return raw or None


def accept_secondary_review(vr: VerifyResult, secondary: bool) -> VerifyResult:
    """专职复核 Pi 收口后，二次验证本身就是真实性结论；不再维持 pending。"""
    if not secondary:
        return vr
    if vr.status == "verified":
        return vr
    return VerifyResult(
        status="verified",
        reason="secondary_review",
        proof_type=vr.proof_type,
        proof_canary=vr.proof_canary,
        proof_url=vr.proof_url,
        proof_detail=vr.proof_detail,
    )


async def verify_finding(
    finding: FindingIn, project_id: str | None = None,
) -> VerifyResult:
    """核真实性：无证据/PoC 不得标已验证。专职二次验证收口后另见 accept_secondary_review。"""
    _ = project_id
    detail = (finding.proof_detail or "").strip()
    canary = infer_canary(finding)
    proof_url = (finding.proof_url or "").strip() or None
    proof_type = (finding.proof_type or "").strip().lower() or None
    base = dict(
        proof_type=proof_type,
        proof_canary=canary,
        proof_url=proof_url,
        proof_detail=detail or None,
    )
    if is_non_exploit_finding_category(getattr(finding, "category", None)):
        return VerifyResult(status="pending", reason="availability_not_exploit", **base)
    if not finding_has_authenticity_proof(finding):
        return VerifyResult(status="pending", reason="no_proof", **base)
    return VerifyResult(status="verified", reason="accepted", **base)


_SECONDARY_FAIL = (
    "未复现", "未能复现", "无法复现", "没有复现", "打不出",
    "未观察到", "未能证明", "没有证明", "未看到同样", "假阳性",
)


def rating_left_verification_alone(rationale: str | None) -> bool:
    """评级回写自称没做二次验证时，不能改未验证或失败。"""
    text = str(rationale or "")
    marks = (
        "保持原状", "未再动手", "未改二次验证", "不要改二次验证",
        "只做 NVD", "只做红队评级", "本轮未再", "未做二次验证",
    )
    return any(m in text for m in marks)


def secondary_claim_failed(rationale: str | None) -> bool:
    """复核自述没有打出同样危害时，不能记成二次验证通过。"""
    text = str(rationale or "")
    return any(p in text for p in _SECONDARY_FAIL)


def recheck_did_not_run(rationale: str | None) -> bool:
    """工具被意图闸拦住，请求没有发出去。这不是二次验证失败。"""
    text = str(rationale or "")
    marks = (
        "本条意图已经写回",
        "不再改打别的类型",
        "这次会话不再",
    )
    return any(m in text for m in marks)


def is_real_secondary_failure(rationale: str | None) -> bool:
    """只有二次验证自己写明没打出同样危害，才算失败。"""
    if rating_left_verification_alone(rationale) or recheck_did_not_run(rationale):
        return False
    text = str(rationale or "")
    if "二次验证失败" in text or secondary_claim_failed(text):
        return True
    return "没看到" in text or "没有看到" in text or "没有独立证明" in text


def merge_verification_status(
    prev_status: str | None,
    prev_secondary: bool,
    incoming_status: str | None,
    incoming_secondary: bool,
    rationale: str | None,
) -> tuple[str, bool]:
    """回写同一条时：未验证保持未验证，二次验证失败保持失败。

    评级或再次上报不能把未验证改成已验证或失败。
    已经失败的条目，后面的回写不能改成已验证。
    """
    prev = (prev_status or "pending").strip().lower() or "pending"
    if prev == "excluded":
        return "excluded", False
    incoming = (incoming_status or "").strip().lower()
    if incoming == "excluded" and is_real_secondary_failure(rationale) and not incoming_secondary:
        return "excluded", False
    if incoming_secondary and not rating_left_verification_alone(rationale):
        return "verified", True
    if prev == "verified":
        return "verified", bool(prev_secondary)
    return "pending" if prev in ("", "pending") else prev, bool(prev_secondary)


def is_visible_finding(row: dict | Any) -> bool:
    """用户可见发现：rejected 隐藏；excluded 仍展示，只是这一条标成排除。"""
    try:
        st = row["verification_status"] if not isinstance(row, dict) else row.get("verification_status")
    except (KeyError, TypeError, IndexError):
        st = None
    if st is None or st == "":
        return True
    return str(st).lower() in ("verified", "flaky", "pending", "excluded")
