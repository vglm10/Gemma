import json
import os
import time
import uuid
import threading
import httpx

OLLAMA_BASE = "http://localhost:11434"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCHEDULES_FILE = os.path.join(DATA_DIR, "schedules.json")


class Scheduler:
    def __init__(self, on_result=None):
        """
        on_result: callback(task, result_text) called when a scheduled task finishes.
        """
        self._on_result = on_result
        self._tasks = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(SCHEDULES_FILE):
            try:
                with open(SCHEDULES_FILE, "r") as f:
                    self._tasks = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._tasks = []

    def _save(self):
        with open(SCHEDULES_FILE, "w") as f:
            json.dump(self._tasks, f, indent=2)

    def add_task(self, name, prompt, interval_minutes):
        with self._lock:
            task = {
                "id": uuid.uuid4().hex[:8],
                "name": name,
                "prompt": prompt,
                "interval_minutes": max(1, interval_minutes),
                "last_run": 0,
                "last_result": "",
                "enabled": True,
            }
            self._tasks.append(task)
            self._save()
            return task

    def remove_task(self, task_id):
        with self._lock:
            before = len(self._tasks)
            self._tasks = [t for t in self._tasks if t["id"] != task_id]
            if len(self._tasks) < before:
                self._save()
                return True
            return False

    def toggle_task(self, task_id):
        with self._lock:
            for t in self._tasks:
                if t["id"] == task_id:
                    t["enabled"] = not t["enabled"]
                    self._save()
                    return t["enabled"]
            return None

    def get_tasks(self):
        with self._lock:
            return list(self._tasks)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _tick_loop(self):
        while self._running:
            self._check_tasks()
            time.sleep(60)

    def _check_tasks(self):
        now = time.time()
        with self._lock:
            tasks_to_run = []
            for t in self._tasks:
                if not t["enabled"]:
                    continue
                elapsed = now - t["last_run"]
                if elapsed >= t["interval_minutes"] * 60:
                    tasks_to_run.append(t)

        for task in tasks_to_run:
            try:
                result = self._execute_prompt(task["prompt"])
                with self._lock:
                    task["last_run"] = time.time()
                    task["last_result"] = result[:2000]
                    self._save()
                if self._on_result:
                    self._on_result(task, result)
            except Exception as e:
                with self._lock:
                    task["last_result"] = f"Error: {e}"
                    self._save()

    def _execute_prompt(self, prompt):
        try:
            response = httpx.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": "gemma4:e4b",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=120.0,
            )
            data = response.json()
            return data.get("message", {}).get("content", "(no response)")
        except Exception as e:
            return f"Error running prompt: {e}"
