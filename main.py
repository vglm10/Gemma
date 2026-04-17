import webview
import threading
import json
import os
import time
from api import OllamaChat
from tools import TOOL_DEFINITIONS, set_scheduler, set_mcp_manager, set_skills_manager
from scheduler import Scheduler
from mcp_manager import MCPManager, load_config, save_config
from pml import PMLManager
from skills_manager import SkillsManager

DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HISTORY_DIR = os.path.join(DATA_ROOT, "history")


IGNORE_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".env", ".idea", ".vscode", ".DS_Store", "dist", "build", ".next",
    ".nuxt", "target", "Pods", ".gradle", "vendor",
}
CONTEXT_FILES = {
    "readme.md", "readme.txt", "readme", "readme.rst",
    "claude.md", "instructions.md", "contributing.md",
    "package.json", "pyproject.toml", "cargo.toml", "go.mod",
    "makefile", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", "requirements.txt", "gemfile",
}
MAX_CONTEXT_FILE_SIZE = 30_000
MAX_TREE_FILES = 500


def scan_project(folder_path):
    """Scan a project folder and build context for the system prompt."""
    if not os.path.isdir(folder_path):
        return None

    tree_lines = []
    context_files = {}
    file_count = 0

    for root, dirs, files in os.walk(folder_path):
        # Skip ignored directories
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")])

        rel_root = os.path.relpath(root, folder_path)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1

        if depth > 4:
            dirs.clear()
            continue

        # Show directory name in tree
        if rel_root != ".":
            dir_indent = "  " * (depth - 1)
            tree_lines.append(f"{dir_indent}{os.path.basename(root)}/")

        for f in sorted(files):
            if f.startswith(".") and f.lower() not in CONTEXT_FILES:
                continue
            file_count += 1
            if file_count > MAX_TREE_FILES:
                break

            rel_path = os.path.join(rel_root, f) if rel_root != "." else f
            indent = "  " * depth
            tree_lines.append(f"{indent}{f}")

            # Read key context files
            if f.lower() in CONTEXT_FILES:
                full_path = os.path.join(root, f)
                try:
                    size = os.path.getsize(full_path)
                    if size <= MAX_CONTEXT_FILE_SIZE:
                        with open(full_path, "r", errors="replace") as fh:
                            content = fh.read()
                        context_files[rel_path] = content
                except (IOError, OSError):
                    pass

        if file_count > MAX_TREE_FILES:
            tree_lines.append("  ... (truncated)")
            break

    tree_str = "\n".join(tree_lines)

    context = (
        f"## PROJECT FOLDER: {folder_path}\n\n"
        f"The user has set this as their active project. All file operations should default "
        f"to this directory unless the user specifies otherwise. Use absolute paths based on "
        f"this root: {folder_path}\n\n"
        f"### File tree:\n```\n{tree_str}\n```\n"
    )

    if context_files:
        context += "\n### Key files:\n"
        for path, content in context_files.items():
            context += f"\n**{path}**:\n```\n{content}\n```\n"

    return context


class Api:
    def __init__(self):
        self.ollama = OllamaChat()
        self._cancel = False
        self._window = None
        self._scheduler = None
        self._project_folder = None
        self._project_context = None
        self._mcp = MCPManager()
        self._pml = PMLManager()
        self._skills = SkillsManager()
        # per-chat set of skill names activated this session
        self._active_skills: dict[str, set] = {}
        self._current_chat_id: str = ""

    def set_window(self, window):
        self._window = window

    def init_scheduler(self):
        self._scheduler = Scheduler(on_result=self._on_schedule_result)
        set_scheduler(self._scheduler)
        self._scheduler.start()

    def init_skills(self):
        self._skills.load()
        self._skills.set_context(
            api=self,
            pml=self._pml,
            scheduler=self._scheduler,
            mcp=self._mcp,
            window=self._window,
        )
        set_skills_manager(self._skills)

    def init_mcp(self):
        """Start MCP event loop and connect to configured servers."""
        self._mcp.start()
        set_mcp_manager(self._mcp)
        try:
            self._mcp.connect_all()
        except Exception:
            pass

    def _on_schedule_result(self, task, result):
        """Called by scheduler when a task completes."""
        if self._window:
            safe = json.dumps({"task": task, "result": result[:500]})
            self._window.evaluate_js(f"window.onScheduleRun({safe})")

    def check_health(self):
        return self.ollama.check_health()

    def send_message(self, messages_json, think_enabled, chat_id=""):
        """Called from JS. Starts streaming with tools in a background thread."""
        self._cancel = False
        self._current_chat_id = chat_id or ""
        # Seed per-chat active_skills with pinned skills if this chat is new.
        if self._current_chat_id and self._current_chat_id not in self._active_skills:
            self._active_skills[self._current_chat_id] = set(self._skills.pinned_names())
        messages = json.loads(messages_json)
        thread = threading.Thread(
            target=self._stream_response,
            args=(messages, think_enabled, self._current_chat_id),
            daemon=True,
        )
        thread.start()
        return True

    def _stream_response(self, messages, think_enabled, chat_id):
        try:
            def _active_set():
                return self._active_skills.get(chat_id, set())

            def _build_tool_defs():
                return (
                    TOOL_DEFINITIONS
                    + self._mcp.get_ollama_tools()
                    + self._skills.tool_defs_for_active(_active_set())
                )

            def _on_tool_call(name, args, result):
                if name != "read_file":
                    return
                path = (args or {}).get("path", "")
                skill = self._skills.skill_for_path(path)
                if skill:
                    self._active_skills.setdefault(chat_id, set()).add(skill)

            skills_index = self._skills.get_index(_active_set())
            initial_tools = _build_tool_defs()

            for event_type, data in self.ollama.stream_with_tools(
                messages, initial_tools, think_enabled,
                project_context=self._project_context,
                skills_index=skills_index,
                build_tool_defs=_build_tool_defs,
                skill_activation_cb=_on_tool_call,
            ):
                if self._cancel:
                    break

                if event_type == "thinking":
                    safe = json.dumps(data)
                    self._window.evaluate_js(
                        f'window.onStreamChunk("thinking", {safe})'
                    )
                elif event_type == "content":
                    safe = json.dumps(data)
                    self._window.evaluate_js(
                        f'window.onStreamChunk("content", {safe})'
                    )
                elif event_type == "tool_call":
                    safe = json.dumps(data)
                    self._window.evaluate_js(f"window.onToolCall({safe})")
                elif event_type == "tool_result":
                    safe = json.dumps(data)
                    self._window.evaluate_js(f"window.onToolResult({safe})")

            # Send updated messages (including tool messages) back to JS
            safe_msgs = json.dumps(messages)
            self._window.evaluate_js(f"window.onMessagesSync({safe_msgs})")
            self._window.evaluate_js("window.onStreamEnd()")
        except Exception as e:
            safe_err = json.dumps(str(e))
            self._window.evaluate_js(f"window.onStreamError({safe_err})")

    def stop_generation(self):
        self._cancel = True

    # --- File upload (called from JS) ---

    def pick_file(self):
        """Open native file picker and return file info + content."""
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=os.path.expanduser("~"),
            allow_multiple=False,
            file_types=(
                "All files (*.*)",
                "Text files (*.txt;*.md;*.csv;*.json;*.xml;*.yaml;*.yml;*.log;*.py;*.js;*.html;*.css)",
                "Documents (*.pdf;*.doc;*.docx)",
            ),
        )
        if not result or len(result) == 0:
            return json.dumps({"ok": False})

        path = result[0]
        name = os.path.basename(path)
        size = os.path.getsize(path)
        ext = os.path.splitext(name)[1].lower()

        # Size limit: 500KB
        if size > 500_000:
            return json.dumps({"ok": False, "error": f"File too large ({size} bytes, max 500KB)"})

        try:
            if ext == ".pdf":
                content = self._read_pdf(path)
            else:
                with open(path, "r", errors="replace") as f:
                    content = f.read()

            return json.dumps({
                "ok": True,
                "name": name,
                "path": path,
                "size": size,
                "content": content[:50000],  # cap at 50K chars
            })
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _read_pdf(self, path):
        """Extract text from a PDF using pymupdf4llm — outputs clean Markdown."""
        import pymupdf4llm
        return pymupdf4llm.to_markdown(path)

    # --- Project folder (called from JS) ---

    def pick_project_folder(self):
        """Open a native folder picker dialog. Returns the chosen path or None."""
        result = self._window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=os.path.expanduser("~"),
        )
        if result and len(result) > 0:
            folder = result[0]
            return self.set_project_folder(folder)
        return json.dumps({"path": None})

    def set_project_folder(self, folder_path):
        """Set the project folder and scan it for context."""
        if not folder_path or not os.path.isdir(folder_path):
            return json.dumps({"path": None, "error": "Invalid folder"})
        self._project_folder = folder_path
        self._project_context = scan_project(folder_path)
        return json.dumps({"path": folder_path})

    def clear_project_folder(self):
        """Clear the project folder context."""
        self._project_folder = None
        self._project_context = None
        return True

    def get_project_folder(self):
        """Get the current project folder path."""
        return self._project_folder or ""

    # --- Chat history (called from JS) ---

    def save_chat(self, chat_id, title, messages_json):
        """Save or update a conversation."""
        os.makedirs(HISTORY_DIR, exist_ok=True)
        path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
        messages = json.loads(messages_json)

        # Load existing to preserve created timestamp
        created = time.time()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    existing = json.load(f)
                    created = existing.get("created", created)
            except (json.JSONDecodeError, IOError):
                pass

        data = {
            "id": chat_id,
            "title": title[:80],
            "created": created,
            "updated": time.time(),
            "messages": messages,
            "active_skills": sorted(self._active_skills.get(chat_id, set())),
        }
        with open(path, "w") as f:
            json.dump(data, f)
        return True

    def load_chat(self, chat_id):
        """Load a conversation by ID."""
        path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
        if not os.path.exists(path):
            return "{}"
        with open(path, "r") as f:
            raw = f.read()
        try:
            data = json.loads(raw)
            skills = data.get("active_skills") or []
            self._active_skills[chat_id] = set(skills)
        except (json.JSONDecodeError, TypeError):
            pass
        return raw

    def list_chats(self):
        """List all saved conversations, most recent first."""
        os.makedirs(HISTORY_DIR, exist_ok=True)
        chats = []
        for fname in os.listdir(HISTORY_DIR):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(HISTORY_DIR, fname)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                chats.append({
                    "id": data["id"],
                    "title": data.get("title", "Untitled"),
                    "updated": data.get("updated", 0),
                })
            except (json.JSONDecodeError, IOError, KeyError):
                continue
        chats.sort(key=lambda c: c["updated"], reverse=True)
        return json.dumps(chats)

    def delete_chat(self, chat_id):
        """Delete a saved conversation."""
        path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    # --- Skills panel (called from JS) ---

    def get_skills_status(self):
        status = self._skills.list_status()
        # Augment with connector auth state for oauth skills.
        for s in status:
            if s.get("auth_kind") == "oauth" and s["name"] == "gmail":
                from connectors import gmail as gmail_connector
                gc = gmail_connector.get()
                s["auth"] = {
                    "configured": gc.is_configured(),
                    "authed": gc.is_authed(),
                    "email": gc.user_email() if gc.is_authed() else "",
                }
        return json.dumps(status)

    def toggle_skill(self, name, enabled):
        ok = self._skills.set_enabled(name, bool(enabled))
        return json.dumps({"ok": ok})

    def toggle_skill_pin(self, name, pinned):
        ok = self._skills.set_pinned(name, bool(pinned))
        return json.dumps({"ok": ok})

    def rescan_skills(self):
        self._skills.load()
        self._skills.set_context(
            api=self, pml=self._pml, scheduler=self._scheduler,
            mcp=self._mcp, window=self._window,
        )
        return self.get_skills_status()

    # --- Gmail OAuth (called from JS) ---

    def gmail_connect(self):
        """Kick off OAuth in a background thread. JS gets notified via
        window.onGmailAuthResult(raw_json) when it finishes."""
        from connectors import gmail as gmail_connector

        def _run():
            conn = gmail_connector.get()
            result = conn.start_auth()
            if self._window:
                payload = json.dumps(result)
                self._window.evaluate_js(f"window.onGmailAuthResult({payload})")

        threading.Thread(target=_run, daemon=True).start()
        return True

    def gmail_disconnect(self):
        from connectors import gmail as gmail_connector
        ok = gmail_connector.get().revoke()
        return json.dumps({"ok": ok})

    # --- PML dashboard (called from JS) ---

    def pml_get_patients(self):
        return json.dumps(self._pml.list_patients())

    def pml_get_patient_scripts(self, patient_id):
        return json.dumps(self._pml.get_scripts_for_status(patient_id))

    def pml_get_script_text(self, patient_id, script_name):
        return self._pml.get_script(patient_id, script_name)

    def pml_advance_patient(self, patient_id):
        p = self._pml.advance_status(patient_id)
        return json.dumps(p) if p else "{}"

    def pml_delete_patient(self, patient_id):
        return self._pml.delete_patient(patient_id)

    def pml_add_patient(self, name, clinician, weeks, has_therapist,
                        therapist_name, therapist_contact):
        p = self._pml.create_patient(
            name, clinician, int(weeks), has_therapist,
            therapist_name, therapist_contact,
        )
        return json.dumps(p)

    def pml_get_checklist(self, patient_id):
        return json.dumps(self._pml.get_checklist(patient_id))

    def pml_get_pipeline(self):
        return json.dumps(self._pml.get_pipeline_summary())

    # --- MCP management (called from JS) ---

    def get_mcp_status(self):
        """Get status of all MCP servers."""
        return json.dumps(self._mcp.get_status())

    def get_mcp_config(self):
        """Get the MCP config."""
        return json.dumps(load_config())

    def add_mcp_server(self, name, command, args_json, env_json):
        """Add an MCP server to config and connect."""
        config = load_config()
        args = json.loads(args_json) if args_json else []
        env = json.loads(env_json) if env_json else {}
        config["servers"][name] = {
            "command": command,
            "args": args,
            "env": env,
        }
        save_config(config)
        # Connect to the new server
        try:
            result = self._mcp.connect_all()
            return json.dumps({"ok": True, "result": result})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def remove_mcp_server(self, name):
        """Remove an MCP server from config."""
        config = load_config()
        if name in config.get("servers", {}):
            del config["servers"][name]
            save_config(config)
        self._mcp.disconnect_all()
        self._mcp.connect_all()
        return True

    def reconnect_mcp(self):
        """Reconnect all MCP servers."""
        self._mcp.disconnect_all()
        result = self._mcp.connect_all()
        return json.dumps(result)

    # --- Schedule management (called from JS) ---

    def get_schedules(self):
        if self._scheduler:
            return json.dumps(self._scheduler.get_tasks())
        return "[]"

    def delete_schedule(self, task_id):
        if self._scheduler:
            return self._scheduler.remove_task(task_id)
        return False

    def toggle_schedule(self, task_id):
        if self._scheduler:
            return self._scheduler.toggle_task(task_id)
        return None


if __name__ == "__main__":
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)

    api = Api()
    static_dir = os.path.join(app_dir, "static")
    window = webview.create_window(
        "Gemma Chat",
        os.path.join(static_dir, "index.html"),
        js_api=api,
        width=900,
        height=700,
        min_size=(600, 400),
        text_select=True,
    )
    api.set_window(window)
    api.init_scheduler()
    api.init_skills()
    api.init_mcp()
    webview.start(debug=False)
