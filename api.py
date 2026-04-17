import httpx
import json
import os
import platform
from datetime import datetime
from tools import execute_tool

OLLAMA_BASE = "http://localhost:11434"
MAX_TOOL_ROUNDS = 10


def get_system_prompt(project_context=None, skills_index=None):
    username = os.environ.get("USER", "user")
    home = os.path.expanduser("~")
    prompt = (
        f"You are Gemma, a helpful AI assistant running locally on the user's computer.\n"
        f"System: macOS {platform.mac_ver()[0]}, User: {username}, Home: {home}\n"
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"You have access to tools that let you run shell commands, read/write files, "
        f"list directories, search files, and manage scheduled tasks.\n"
        f"Use tools when the user asks you to interact with their system. "
        f"Always use absolute paths (expand ~ to {home}). "
        f"Be concise in your responses. Show relevant output from tools."
    )
    if project_context:
        prompt += f"\n\n{project_context}"
    if skills_index:
        prompt += f"\n\n{skills_index}"
    return prompt


class OllamaChat:
    def check_health(self):
        try:
            r = httpx.get(OLLAMA_BASE, timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def stream_chat(self, messages, think_enabled=False):
        """
        Simple streaming chat without tools.
        Generator yielding (chunk_type, token) tuples.
        """
        payload = {
            "model": "gemma4:e4b",
            "messages": messages,
            "stream": True,
        }
        if think_enabled:
            payload["think"] = True

        with httpx.stream(
            "POST",
            f"{OLLAMA_BASE}/api/chat",
            json=payload,
            timeout=300.0,
        ) as response:
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("done"):
                    return
                msg = chunk.get("message", {})
                thinking_token = msg.get("thinking", "")
                content_token = msg.get("content", "")
                if thinking_token:
                    yield ("thinking", thinking_token)
                elif content_token:
                    yield ("content", content_token)

    def stream_with_tools(self, messages, tool_defs, think_enabled=False,
                          project_context=None, skills_index=None,
                          build_tool_defs=None, skill_activation_cb=None):
        """
        Streaming chat with tool calling support.

        build_tool_defs: optional callable() -> list[dict]. If provided, it is
        called before each round to re-compute the tool list (used by the
        skills layer so newly-activated skill tools appear next turn).
        skill_activation_cb: optional callable(tool_name, tool_args, tool_result)
        invoked after each tool call so the caller can detect skill activation.

        Generator yielding (event_type, data) tuples.
        Event types: "thinking", "content", "tool_call", "tool_result"
        """
        # Ensure system prompt is first message
        sys_prompt = get_system_prompt(project_context, skills_index)
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": sys_prompt})
        else:
            # Always refresh — project context or active skills may have changed.
            messages[0]["content"] = sys_prompt

        for _round in range(MAX_TOOL_ROUNDS):
            accumulated_tool_calls = []
            accumulated_content = ""
            accumulated_thinking = ""

            # Re-compute tool defs each round so freshly-activated skills appear.
            current_tool_defs = build_tool_defs() if build_tool_defs else tool_defs

            payload = {
                "model": "gemma4:e4b",
                "messages": messages,
                "tools": current_tool_defs,
                "stream": True,
            }
            if think_enabled:
                payload["think"] = True

            with httpx.stream(
                "POST",
                f"{OLLAMA_BASE}/api/chat",
                json=payload,
                timeout=300.0,
            ) as response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)

                    if chunk.get("done"):
                        break

                    msg = chunk.get("message", {})

                    # Stream thinking tokens
                    if msg.get("thinking"):
                        token = msg["thinking"]
                        accumulated_thinking += token
                        yield ("thinking", token)

                    # Stream content tokens
                    if msg.get("content"):
                        token = msg["content"]
                        accumulated_content += token
                        yield ("content", token)

                    # Accumulate tool calls
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            if tc not in accumulated_tool_calls:
                                accumulated_tool_calls.append(tc)

            # No tool calls — we're done
            if not accumulated_tool_calls:
                return

            # Append assistant message with tool calls
            assistant_msg = {"role": "assistant", "content": accumulated_content}
            if accumulated_tool_calls:
                assistant_msg["tool_calls"] = accumulated_tool_calls
            messages.append(assistant_msg)

            # Execute each tool call
            for tc in accumulated_tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                yield ("tool_call", {"name": name, "args": args})

                result = execute_tool(name, args)

                yield ("tool_result", {"name": name, "result": result})

                if skill_activation_cb:
                    try:
                        skill_activation_cb(name, args, result)
                    except Exception:
                        pass

                messages.append({"role": "tool", "content": str(result)})

        yield ("content", "\n\n*Reached maximum tool call rounds.*")


if __name__ == "__main__":
    chat = OllamaChat()
    print("Ollama healthy:", chat.check_health())
    from tools import TOOL_DEFINITIONS

    messages = [{"role": "user", "content": "What is my username? Use a command to find out."}]
    for event_type, data in chat.stream_with_tools(messages, TOOL_DEFINITIONS, think_enabled=False):
        if event_type == "content":
            print(data, end="", flush=True)
        elif event_type == "tool_call":
            print(f"\n[TOOL CALL] {data['name']}({data['args']})")
        elif event_type == "tool_result":
            print(f"[TOOL RESULT] {data['result'][:200]}")
        elif event_type == "thinking":
            print(f"[THINK] {data}", end="", flush=True)
    print()
