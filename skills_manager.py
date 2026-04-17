import importlib
import importlib.util
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

import yaml

log = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_SKILLS_DIR = os.path.join(APP_DIR, "skills")
USER_SKILLS_DIR = os.path.expanduser("~/.gemma/skills")
STATE_FILE = os.path.join(APP_DIR, "data", "skills.json")

MAX_SKILLS = 150
MAX_INDEX_CHARS = 18_000
MAX_SKILL_FILE_BYTES = 256 * 1024


# ── status codes ──
S_READY = "ready"
S_DISABLED = "disabled"
S_MISSING_BIN = "missing_bin"
S_MISSING_ENV = "missing_env"
S_MISSING_PYTHON = "missing_python"
S_LOAD_ERROR = "load_error"


@dataclass
class Skill:
    name: str
    description: str
    path: str                    # absolute path to SKILL.md
    dir: str                     # absolute path to skill directory
    version: str = "0"
    emoji: str = ""
    requires_bins: list = field(default_factory=list)
    requires_env: list = field(default_factory=list)
    requires_python: list = field(default_factory=list)
    tools_module_rel: str = ""   # relative path within skill dir, e.g. "tools.py"
    auth_kind: str = "none"      # none | apikey | oauth
    user_invocable: bool = False
    # Runtime
    module = None                # loaded Python module if tools_module_rel set
    tool_names: list = field(default_factory=list)
    status: str = S_READY
    status_detail: str = ""
    enabled: bool = True
    pinned: bool = False


@dataclass
class SkillContext:
    """Handed to a skill's execute() so it can reach app services."""
    api: object = None
    mcp: object = None
    pml: object = None
    scheduler: object = None
    window: object = None


class SkillsManager:
    def __init__(self):
        self.skills: dict[str, Skill] = {}
        self._tool_to_skill: dict[str, str] = {}
        self._path_to_skill: dict[str, str] = {}  # realpath → skill name
        self._ctx = SkillContext()
        self._state: dict = {"skills": {}}  # persisted enabled/pinned per skill
        self._load_state()

    # ── public setup ────────────────────────────────────────────────

    def set_context(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self._ctx, k, v)

    def load(self):
        """Scan both roots and (re)load all skills. User root overrides bundled."""
        self.skills.clear()
        self._tool_to_skill.clear()
        self._path_to_skill.clear()

        candidates: dict[str, str] = {}  # name → dir (user wins over bundled)
        for root in (BUNDLED_SKILLS_DIR, USER_SKILLS_DIR):
            if not os.path.isdir(root):
                continue
            for entry in sorted(os.listdir(root)):
                skill_dir = os.path.join(root, entry)
                skill_md = os.path.join(skill_dir, "SKILL.md")
                if os.path.isfile(skill_md):
                    candidates[entry] = skill_dir

        if len(candidates) > MAX_SKILLS:
            log.warning("Found %d skills; capping at %d", len(candidates), MAX_SKILLS)
            candidates = dict(list(candidates.items())[:MAX_SKILLS])

        for name, skill_dir in candidates.items():
            skill = self._load_one(name, skill_dir)
            if skill:
                self.skills[name] = skill
                self._path_to_skill[os.path.realpath(skill.path)] = name

        self._apply_state()
        log.info("Loaded %d skills: %s",
                 len(self.skills), ", ".join(self.skills.keys()) or "(none)")

    # ── skill loading ───────────────────────────────────────────────

    def _load_one(self, name: str, skill_dir: str) -> Optional[Skill]:
        skill_md = os.path.join(skill_dir, "SKILL.md")
        try:
            size = os.path.getsize(skill_md)
            if size > MAX_SKILL_FILE_BYTES:
                log.warning("Skill %s SKILL.md too large (%d bytes); skipping", name, size)
                return None
            with open(skill_md, "r", errors="replace") as f:
                raw = f.read()
        except (IOError, OSError) as e:
            log.warning("Skill %s unreadable: %s", name, e)
            return None

        meta = self._parse_frontmatter(raw)
        if not meta:
            log.warning("Skill %s has no YAML frontmatter; skipping", name)
            return None

        requires = meta.get("requires") or {}
        auth = meta.get("auth") or {}

        skill = Skill(
            name=meta.get("name") or name,
            description=meta.get("description") or "",
            path=skill_md,
            dir=skill_dir,
            version=str(meta.get("version", "0")),
            emoji=meta.get("emoji") or "",
            requires_bins=list(requires.get("bins") or []),
            requires_env=list(requires.get("env") or []),
            requires_python=list(requires.get("python") or []),
            tools_module_rel=meta.get("tools_module") or "",
            auth_kind=(auth.get("kind") or "none"),
            user_invocable=bool(meta.get("user_invocable", False)),
        )

        self._check_requires(skill)
        if skill.status == S_READY and skill.tools_module_rel:
            self._import_tools(skill)

        return skill

    def _parse_frontmatter(self, raw: str) -> Optional[dict]:
        if not raw.startswith("---"):
            return None
        end = raw.find("\n---", 3)
        if end == -1:
            return None
        block = raw[3:end].strip()
        try:
            meta = yaml.safe_load(block) or {}
            return meta if isinstance(meta, dict) else None
        except yaml.YAMLError as e:
            log.warning("YAML error in frontmatter: %s", e)
            return None

    def _check_requires(self, skill: Skill):
        for b in skill.requires_bins:
            if not shutil.which(b):
                skill.status = S_MISSING_BIN
                skill.status_detail = f"missing binary: {b}"
                return
        for e in skill.requires_env:
            if not os.environ.get(e):
                skill.status = S_MISSING_ENV
                skill.status_detail = f"missing env: {e}"
                return
        for p in skill.requires_python:
            if not importlib.util.find_spec(p):
                skill.status = S_MISSING_PYTHON
                skill.status_detail = f"missing python package: {p}"
                return
        skill.status = S_READY
        skill.status_detail = ""

    def _import_tools(self, skill: Skill):
        """Import skills/<name>/tools.py (or the file named by tools_module_rel)."""
        module_path = os.path.join(skill.dir, skill.tools_module_rel)
        if not os.path.isfile(module_path):
            skill.status = S_LOAD_ERROR
            skill.status_detail = f"tools_module missing: {skill.tools_module_rel}"
            return
        mod_name = f"_skill_{skill.name.replace('-', '_')}_tools"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, module_path)
            if not spec or not spec.loader:
                raise ImportError("spec_from_file_location returned None")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            skill.status = S_LOAD_ERROR
            skill.status_detail = f"import error: {e}"
            log.warning("Failed to import tools for skill %s: %s", skill.name, e)
            return

        tool_defs = getattr(module, "TOOL_DEFINITIONS", None)
        executor = getattr(module, "execute", None)
        if not tool_defs or not callable(executor):
            skill.status = S_LOAD_ERROR
            skill.status_detail = "tools module missing TOOL_DEFINITIONS or execute()"
            return

        names = []
        for td in tool_defs:
            tn = td.get("function", {}).get("name", "")
            if not tn:
                continue
            if tn in self._tool_to_skill:
                log.warning("Skill %s tool name collision with %s: %s — skipping this skill",
                            skill.name, self._tool_to_skill[tn], tn)
                skill.status = S_LOAD_ERROR
                skill.status_detail = f"tool name collision: {tn}"
                return
            names.append(tn)
        # Only register after all names validated
        for tn in names:
            self._tool_to_skill[tn] = skill.name
        skill.tool_names = names
        skill.module = module

    # ── state persistence ───────────────────────────────────────────

    def _load_state(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE, "r") as f:
                self._state = json.load(f) or {"skills": {}}
        except (IOError, json.JSONDecodeError):
            self._state = {"skills": {}}

    def _save_state(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self._state, f, indent=2)

    def _apply_state(self):
        """Apply persisted enabled/pinned flags to loaded skills."""
        defaults = {
            # PML is opt-in on-disk because the skill contains coercion-style
            # scripts; disabled by default after refactor.
            "pml": {"enabled": False, "pinned": False},
        }
        for name, skill in self.skills.items():
            entry = self._state.get("skills", {}).get(name)
            if entry is None:
                entry = defaults.get(name, {"enabled": True, "pinned": False})
            skill.enabled = bool(entry.get("enabled", True))
            skill.pinned = bool(entry.get("pinned", False))

    # ── public query & action ──────────────────────────────────────

    def get_index(self, active: Optional[set] = None) -> str:
        """XML block for the system prompt. Only lists *enabled* skills."""
        active = active or set()
        lines = ["<available_skills>"]
        for skill in self.skills.values():
            if not skill.enabled or skill.status != S_READY:
                continue
            active_attr = ' status="active"' if skill.name in active else ""
            desc = (skill.description or "").replace("\n", " ").strip()
            lines.append(
                f'  <skill name="{skill.name}" path="{skill.path}"{active_attr}>\n'
                f'    {desc}\n'
                f'  </skill>'
            )
        lines.append("</available_skills>")
        lines.append("")
        lines.append(
            "To use a skill, call read_file on its path. "
            "After that, skill-specific tools become available for the rest of this chat."
        )
        xml = "\n".join(lines)
        if len(xml) > MAX_INDEX_CHARS:
            log.warning("Skill index %d chars exceeds %d; truncating",
                        len(xml), MAX_INDEX_CHARS)
            xml = xml[:MAX_INDEX_CHARS] + "\n<!-- truncated -->\n"
        return xml

    def tool_defs_for_active(self, active: set) -> list:
        defs = []
        for name in active:
            skill = self.skills.get(name)
            if not skill or not skill.enabled or skill.status != S_READY:
                continue
            if skill.module:
                defs.extend(getattr(skill.module, "TOOL_DEFINITIONS", []))
        return defs

    def is_skill_tool(self, tool_name: str) -> bool:
        return tool_name in self._tool_to_skill

    def execute_tool(self, tool_name: str, args: dict) -> str:
        owner = self._tool_to_skill.get(tool_name)
        if not owner:
            return f"Error: unknown skill tool {tool_name}"
        skill = self.skills.get(owner)
        if not skill or not skill.module:
            return f"Error: skill {owner} not loaded"
        try:
            return skill.module.execute(tool_name, args or {}, self._ctx)
        except Exception as e:
            log.exception("Skill tool %s failed", tool_name)
            return f"Error: {e}"

    def skill_for_path(self, path: str) -> Optional[str]:
        """If path points at a known SKILL.md, return the skill name."""
        if not path:
            return None
        try:
            rp = os.path.realpath(os.path.expanduser(path))
        except (OSError, ValueError):
            return None
        return self._path_to_skill.get(rp)

    def list_status(self) -> list:
        out = []
        for skill in self.skills.values():
            out.append({
                "name": skill.name,
                "description": skill.description,
                "emoji": skill.emoji,
                "status": skill.status,
                "status_detail": skill.status_detail,
                "enabled": skill.enabled,
                "pinned": skill.pinned,
                "auth_kind": skill.auth_kind,
                "tool_count": len(skill.tool_names),
            })
        return out

    def pinned_names(self) -> set:
        return {s.name for s in self.skills.values() if s.pinned and s.enabled}

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self.skills:
            return False
        self.skills[name].enabled = enabled
        self._state.setdefault("skills", {}).setdefault(name, {})["enabled"] = enabled
        self._save_state()
        return True

    def set_pinned(self, name: str, pinned: bool) -> bool:
        if name not in self.skills:
            return False
        self.skills[name].pinned = pinned
        self._state.setdefault("skills", {}).setdefault(name, {})["pinned"] = pinned
        self._save_state()
        return True
