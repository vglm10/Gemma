import webview
import threading
import json
import os
from api import OllamaChat
from tools import TOOL_DEFINITIONS, set_scheduler
from scheduler import Scheduler


class Api:
    def __init__(self):
        self.ollama = OllamaChat()
        self._cancel = False
        self._window = None
        self._scheduler = None

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
                messages, TOOL_DEFINITIONS, think_enabled
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
