"""NVD 的 CVSS v3.1 评价。

NVD 只公布基础指标（Base），不公布时间分、环境分。
定性分档用 NVD 的 CVSS v3.x 表：None 0.0、Low 0.1–3.9、Medium 4.0–6.9、High 7.0–8.9、Critical 9.0–10.0。
三项影响都是 None 时，NVD 不打分。
计算器方程与 NVD CVSS v3.1 计算器相同。
https://nvd.nist.gov/vuln-metrics/cvss
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

_AV = {"N": Decimal("0.85"), "A": Decimal("0.62"), "L": Decimal("0.55"), "P": Decimal("0.20")}
_AC = {"L": Decimal("0.77"), "H": Decimal("0.44")}
_UI = {"N": Decimal("0.85"), "R": Decimal("0.62")}
_CIA = {"H": Decimal("0.56"), "L": Decimal("0.22"), "N": Decimal("0")}
_BASE_KEYS = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")
_WORDS = {
    "NETWORK": "N", "ADJACENT": "A", "LOCAL": "L", "PHYSICAL": "P",
    "LOW": "L", "HIGH": "H", "NONE": "N", "REQUIRED": "R",
    "UNCHANGED": "U", "CHANGED": "C",
    "网络": "N", "相邻": "A", "本地": "L", "物理": "P",
    "低": "L", "高": "H", "无": "N", "需要": "R",
    "不变": "U", "改变": "C",
}


def roundup(value: Decimal) -> Decimal:
    """附录 A：先把输入乘 100000 取最近整数，再用整数运算进到一位小数。"""
    int_input = int((value * Decimal(100000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if int_input % 10000 == 0:
        return Decimal(int_input) / Decimal(100000)
    return Decimal(int_input // 10000 + 1) / Decimal(10)


def _pr(code: str, scope_changed: bool) -> Decimal:
    if code == "N":
        return Decimal("0.85")
    if code == "L":
        return Decimal("0.68") if scope_changed else Decimal("0.62")
    return Decimal("0.50") if scope_changed else Decimal("0.27")


def qualitative(score: Decimal) -> str:
    """NVD CVSS v3.x 定性分档。0.0 对应 None，内部记为 info；NVD 充实数据时不收这种向量。"""
    if score <= 0:
        return "info"
    if score <= Decimal("3.9"):
        return "low"
    if score <= Decimal("6.9"):
        return "medium"
    if score <= Decimal("8.9"):
        return "high"
    return "critical"


def band_zh(score: Decimal) -> str:
    return {"info": "无", "low": "低危", "medium": "中危", "high": "高危", "critical": "严重"}[qualitative(score)]


@dataclass(frozen=True)
class CvssBase:
    vector: str
    score: float
    rating: str
    band_zh: str


def base_score(metrics: dict[str, str]) -> CvssBase:
    av = _AV[metrics["AV"]]
    ac = _AC[metrics["AC"]]
    ui = _UI[metrics["UI"]]
    scope_changed = metrics["S"] == "C"
    pr = _pr(metrics["PR"], scope_changed)
    c, i, a = _CIA[metrics["C"]], _CIA[metrics["I"]], _CIA[metrics["A"]]
    iss = Decimal(1) - ((Decimal(1) - c) * (Decimal(1) - i) * (Decimal(1) - a))
    if scope_changed:
        impact = Decimal("7.52") * (iss - Decimal("0.029")) - Decimal("3.25") * ((iss - Decimal("0.02")) ** 15)
    else:
        impact = Decimal("6.42") * iss
    exploitability = Decimal("8.22") * av * ac * pr * ui
    if impact <= 0:
        score = Decimal(0)
    elif scope_changed:
        score = roundup(min(Decimal("1.08") * (impact + exploitability), Decimal(10)))
    else:
        score = roundup(min(impact + exploitability, Decimal(10)))
    vector = "CVSS:3.1/" + "/".join(f"{k}:{metrics[k]}" for k in _BASE_KEYS)
    shown = score.quantize(Decimal("0.1"))
    return CvssBase(vector=vector, score=float(shown), rating=qualitative(shown), band_zh=band_zh(shown))


def _code(raw: str, allowed: set[str]) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    up = s.upper()
    if up in allowed:
        return up
    word = _WORDS.get(up) or _WORDS.get(s)
    if word in allowed:
        return word
    return None


def normalize_metrics(raw: dict[str, str]) -> dict[str, str] | None:
    allowed = {
        "AV": set(_AV), "AC": set(_AC), "PR": {"N", "L", "H"}, "UI": set(_UI),
        "S": {"U", "C"}, "C": set(_CIA), "I": set(_CIA), "A": set(_CIA),
    }
    out: dict[str, str] = {}
    for key in _BASE_KEYS:
        code = _code(raw.get(key, ""), allowed[key])
        if not code:
            return None
        out[key] = code
    return out


def parse_vector(text: str) -> dict[str, str] | None:
    parts = [p for p in str(text or "").strip().split("/") if p and not p.upper().startswith("CVSS:")]
    raw: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        raw[key.strip().upper()] = val.strip()
    if not all(raw.get(k) for k in _BASE_KEYS):
        return None
    return normalize_metrics(raw)


def metrics_from_args(args: dict) -> tuple[dict[str, str] | None, bool]:
    """返回 (指标, 是否试图评级)。指标不全且试图评级时，指标为 None。"""
    fields = {
        "AV": args.get("cvss_av"), "AC": args.get("cvss_ac"), "PR": args.get("cvss_pr"),
        "UI": args.get("cvss_ui"), "S": args.get("cvss_s"), "C": args.get("cvss_c"),
        "I": args.get("cvss_i"), "A": args.get("cvss_a"),
    }
    touched = any(str(v or "").strip() for v in fields.values()) or bool(str(args.get("cvss_vector") or "").strip())
    rating = bool(str(args.get("redteam_rating") or "").strip())
    if not touched and not rating:
        return None, False
    if all(str(v or "").strip() for v in fields.values()):
        got = normalize_metrics({k: str(v) for k, v in fields.items()})
        return got, True
    parsed = parse_vector(str(args.get("cvss_vector") or ""))
    if parsed:
        return parsed, True
    return None, True


def nvd_reject_reason(metrics: dict[str, str]) -> str | None:
    """NVD 不给没有任何机密性、完整性、可用性影响的向量打分。"""
    if metrics.get("C") == "N" and metrics.get("I") == "N" and metrics.get("A") == "N":
        return "NVD 不对三项影响都是 None 的向量打分。这条如果确实没有机密性、完整性或可用性影响，不要当作漏洞评级。"
    return None


def attach_vector(rationale: str | None, scored: CvssBase) -> str:
    text = str(rationale or "").strip()
    line = f"NVD {scored.vector} 基础分 {scored.score:.1f}，定性 {scored.band_zh}。"
    if scored.vector in text:
        return text
    return f"{line}\n{text}".strip()


CVSS31_REVIEW = """\
二次验证的级别按 NVD 的 CVSS v3.1 评价（https://nvd.nist.gov/vuln-metrics/cvss）。不要用旧四级表，不要自己算分。
NVD 只公布基础分，不要填时间分或环境分。八项基础指标都要填，系统按 NVD 的 CVSS v3.1 计算器写入分数和定性：
低危 Low 0.1–3.9，中危 Medium 4.0–6.9，高危 High 7.0–8.9，严重 Critical 9.0–10.0。
三项影响都是 N 时 NVD 不打分，不要提交。
细节不够判断某一项时，按 NVD 的最坏情况取值。公开信息完全没有技术细节时，NVD 记 10.0（Critical）。已经能判断影响范围时，按这个漏洞本身打，不要把已知的有限影响改成 10.0。
攻击者本来就懂这个洞，不算攻击复杂度高。所需权限是打之前就有的，不是打完拿到的。
没有命令执行回显时，不要按代码执行的完全失控来打；能读全部数据、改全部数据或让服务不可用，仍然可以是 High。

AV 攻击向量：N 跨网络（从内网其它机器远程打也算 N），A 必须在同一链路或相邻管理域，L 本地能力或要别人打开文件，P 要物理接触。
AC 攻击复杂度：L 可以重复打成，H 还要攻击者控制不了的条件（竞态、中间人、先摸清目标环境）。
PR 所需权限：N 未授权，L 普通用户，H 管理员。
UI 用户交互：N 不需要别人配合，R 需要其他用户先做动作。
S 范围：U 影响停在同一个安全域；C 打穿到另一个安全域。只给这个应用用的数据库仍算 U。
C/I/A：H 这一类影响基本全部失去，或后果直接且严重；L 有限或部分；N 没有。只记相对攻击前新增加的影响。
"""
