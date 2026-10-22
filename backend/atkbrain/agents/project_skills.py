"""Shared skill library and per-project snapshots.

Bundled resources live in repository skills/. Console-created skills and edits
live under data/skills/ so upgrades cannot overwrite them. Active workspaces
retain the content copied at project-session startup.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import yaml

from ..config import REPO_ROOT, settings
from ..objective import objective_allows_flag, objective_is_src

SKILLS_ROOT = REPO_ROOT / "skills"
if not (SKILLS_ROOT / "kali-kit").is_dir():
    SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
USER_SKILLS_ROOT = Path(settings.data_dir) / "skills"
SHARED_SKILLS = ("kali-kit", "waf-bypass-methodology")
CTF_SKILLS = ("recon-fanout",)
REDTEAM_SKILLS = ("recon-spiral",)
SRC_SKILLS = ("src-hunt-playbook",)
MAX_SKILL_BYTES = 256_000
_NAME_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")
_WRITE_LOCK = threading.RLock()


class _UniqueKeyLoader(yaml.SafeLoader):
    """Pi rejects duplicate mapping keys; PyYAML's default loader accepts them."""

    def construct_mapping(self, node, deep=False):
        result = super().construct_mapping(node, deep=deep)
        if len(result) != len(node.value):
            raise yaml.constructor.ConstructorError(
                "mapping", node.start_mark, "duplicate keys are not allowed", node.start_mark,
            )
        return result


class SkillConflictError(ValueError):
    pass


def _directories(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {
        p.name: p for p in sorted(root.iterdir())
        if _NAME_RE.fullmatch(p.name) and p.is_dir() and not p.is_symlink()
        and (p / "SKILL.md").is_file() and not (p / "SKILL.md").is_symlink()
        and (p / "SKILL.md").resolve().is_relative_to(root.resolve())
    }


def skill_names(*, objective: str | None = None) -> list[str]:
    available = set(_directories(SKILLS_ROOT)) | set(_directories(USER_SKILLS_ROOT))
    if objective is None:
        return sorted(available)
    if objective_allows_flag(objective):
        extra = CTF_SKILLS
    elif objective_is_src(objective):
        extra = SRC_SKILLS
    else:
        extra = REDTEAM_SKILLS
    return [n for n in (*SHARED_SKILLS, *extra) if n in available]


def validate_skill_selection(value: object) -> list[str] | None:
    """None inherits track defaults; an empty list explicitly disables skills."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("skills 必须是名称数组或 null")
    available = set(skill_names())
    if any(not isinstance(n, str) or n not in available for n in value):
        raise ValueError("包含不存在或无效的 skill")
    return list(dict.fromkeys(value))


def skill_content(name: str) -> str:
    stored = _directories(USER_SKILLS_ROOT).get(name)
    if stored is not None:
        return (stored / "SKILL.md").read_text(encoding="utf-8")
    builtin = _directories(SKILLS_ROOT).get(name)
    if builtin is None:
        raise FileNotFoundError("Skill 不存在")
    if name == "kali-kit":
        from .kali_kit import skill_markdown
        return skill_markdown()
    return (builtin / "SKILL.md").read_text(encoding="utf-8")


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def skill_catalog() -> dict:
    with _WRITE_LOCK:
        entries = []
        builtins = _directories(SKILLS_ROOT)
        overrides = _directories(USER_SKILLS_ROOT)
        for name in skill_names():
            content = skill_content(name)
            entries.append({
                "name": name, "content": content, "revision": _revision(content),
                "source": "override" if name in builtins and name in overrides else
                          "builtin" if name in builtins else "custom",
            })
        return {
            "skills": entries,
            "defaults": {track: skill_names(objective=track) for track in ("redteam", "flag", "src")},
        }


def _stored_file(name: str) -> Path:
    if not _NAME_RE.fullmatch(name):
        raise ValueError("Skill 名称只允许字母、数字、短横线和下划线，1-64 位")
    folder = USER_SKILLS_ROOT / name
    path = folder / "SKILL.md"
    if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(USER_SKILLS_ROOT.resolve()):
        raise ValueError("无效的 Skill 保存路径")
    return path


def _write_content(path: Path, content: str) -> None:
    if not content.strip():
        raise ValueError("Skill 内容不能为空")
    if len(content.encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError("Skill 内容不能超过 256 KB")
    frontmatter = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.S)
    if not frontmatter:
        raise ValueError("请保留开头的 YAML 元信息，并填写 description")
    try:
        meta = yaml.load(frontmatter.group(1), Loader=_UniqueKeyLoader)
    except yaml.YAMLError:
        raise ValueError("Skill 的 YAML 元信息格式无效")
    description = meta.get("description") if isinstance(meta, dict) else None
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError("description 必须是 1-1024 字符的用途说明")
    if meta.get("name") is not None and meta["name"] != path.parent.name:
        raise ValueError("元信息中的 name 必须与 Skill 名称一致，或省略 name 字段")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            f.write(content)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def create_skill(name: str, content: str) -> None:
    with _WRITE_LOCK:
        path = _stored_file(name)
        if name in skill_names() or path.exists():
            raise FileExistsError("同名 Skill 已存在，请使用编辑")
        _write_content(path, content)


def update_skill(name: str, content: str, revision: str) -> None:
    with _WRITE_LOCK:
        path = _stored_file(name)
        if name not in skill_names():
            raise FileNotFoundError("Skill 不存在")
        if revision != _revision(skill_content(name)):
            raise SkillConflictError("Skill 已被其他页面修改，请保留草稿并重新打开最新内容")
        _write_content(path, content)


def skill_abs_paths(workspace: str | Path, names: list[str] | None = None) -> list[str]:
    root = Path(workspace) / ".agents" / "skills"
    out: list[str] = []
    for name in names or []:
        n = str(name or "").strip()
        if not _NAME_RE.fullmatch(n):
            continue
        p = (root / n).resolve()
        if p.is_dir() and (p / "SKILL.md").is_file() and (p / "SKILL.md").resolve().is_relative_to(root.resolve()):
            out.append(str(p))
    return out


def install_into_workspace(
    workspace: str | Path, *, objective: str | None = None, names: list[str] | None = None,
) -> list[str]:
    """Copy the effective shared library content, preserving bundled resources."""
    names = skill_names(objective=objective) if names is None else validate_skill_selection(names)
    dst_root = Path(workspace) / ".agents" / "skills"
    try:
        dst_root.mkdir(parents=True, exist_ok=True)
        wanted = set(names)
        for extra in list(dst_root.iterdir()):
            if extra.is_dir() and extra.name not in wanted:
                shutil.rmtree(extra, ignore_errors=True)
        builtin = _directories(SKILLS_ROOT)
        for name in names:
            dst = dst_root / name
            if name in builtin:
                shutil.copytree(builtin[name], dst, dirs_exist_ok=True)
            else:
                dst.mkdir(parents=True, exist_ok=True)
            (dst / "SKILL.md").write_text(skill_content(name), encoding="utf-8")
    except OSError:
        pass
    return names
