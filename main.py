import webview
import threading
import json
import os
import time
import uuid
from api import OllamaChat
from tools import TOOL_DEFINITIONS, set_scheduler
from scheduler import Scheduler

HISTORY_DIR = os.path.expanduser("~/.gemma-chat/history")


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

    def set_window(self, window):
        self._window = window

    def init_scheduler(self):
        self._scheduler = Scheduler(on_result=self._on_schedule_result)
        set_scheduler(self._scheduler)
        self._scheduler.start()

    def _on_schedule_result(self, task, result):
        """Called by scheduler when a task completes."""
        if self._window:
            safe = json.dumps({"task": task, "result": result[:500]})
            self._window.evaluate_js(f"window.onScheduleRun({safe})")

    def check_health(self):
        return self.ollama.check_health()

    def send_message(self, messages_json, think_enabled):
        """Called from JS. Starts streaming with tools in a background thread."""
        self._cancel = False
        messages = json.loads(messages_json)
        thread = threading.Thread(
            target=self._stream_response,
            args=(messages, think_enabled),
            daemon=True,
        )
        thread.start()
        return True

    def _stream_response(self, messages, think_enabled):
        try:
            for event_type, data in self.ollama.stream_with_tools(
                messages, TOOL_DEFINITIONS, think_enabled,
                project_context=self._project_context,
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
            return f.read()

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
    webview.start(debug=False)
