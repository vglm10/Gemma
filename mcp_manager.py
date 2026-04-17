import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mcp.json")


def _default_config():
    return {"servers": {}}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return _default_config()


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def _mcp_tool_to_ollama(server_name, tool):
    """Convert an MCP tool definition to Ollama tool format."""
    input_schema = tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": f"{server_name}__{tool.name}",
            "description": f"[{server_name}] {tool.description or tool.name}",
            "parameters": input_schema,
        },
    }


class MCPManager:
    """Manages connections to MCP servers and routes tool calls."""

    def __init__(self):
        self._servers = {}  # name -> {session, tools, connected}
        self._loop = None
        self._thread = None
        self._exit_stack = None
        self._ready = threading.Event()

    def start(self):
        """Start the async event loop in a background thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _run_async(self, coro):
        """Run an async coroutine from sync code. Returns the result."""
        if not self._loop:
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def connect_all(self):
        """Connect to all servers in the config."""
        config = load_config()
        results = {}
        for name, server_conf in config.get("servers", {}).items():
            try:
                self._run_async(self._connect_server(name, server_conf))
                results[name] = {"connected": True, "tools": len(self._servers[name]["tools"])}
            except Exception as e:
                results[name] = {"connected": False, "error": str(e)}
        return results

    async def _connect_server(self, name, server_conf):
        """Connect to a single MCP server."""
        # Disconnect if already connected
        if name in self._servers and self._servers[name].get("session"):
            try:
                await self._servers[name]["exit_stack"].aclose()
            except Exception:
                pass

        command = server_conf.get("command", "")
        args = server_conf.get("args", [])
        env_vars = server_conf.get("env", {})

        # Merge with current environment
        env = {**os.environ, **env_vars}

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )

        exit_stack = AsyncExitStack()
        stdio_transport = await exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = stdio_transport
        session = await exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()

        # Discover tools
        tools_response = await session.list_tools()
        tools = tools_response.tools

        self._servers[name] = {
            "session": session,
            "exit_stack": exit_stack,
            "tools": tools,
            "connected": True,
        }

    def disconnect_all(self):
        """Disconnect from all servers."""
        for name in list(self._servers.keys()):
            try:
                self._run_async(self._disconnect_server(name))
            except Exception:
                pass
        self._servers.clear()

    async def _disconnect_server(self, name):
        if name in self._servers:
            try:
                await self._servers[name]["exit_stack"].aclose()
            except Exception:
                pass

    def get_ollama_tools(self):
        """Get all MCP tools converted to Ollama format."""
        tools = []
        for name, server in self._servers.items():
            if not server.get("connected"):
                continue
            for tool in server.get("tools", []):
                tools.append(_mcp_tool_to_ollama(name, tool))
        return tools

    def get_status(self):
        """Get connection status of all servers."""
        config = load_config()
        status = {}
        for name in config.get("servers", {}):
            if name in self._servers and self._servers[name].get("connected"):
                tool_names = [t.name for t in self._servers[name]["tools"]]
                status[name] = {"connected": True, "tools": tool_names}
            else:
                status[name] = {"connected": False, "tools": []}
        return status

    def call_tool(self, full_name, arguments):
        """Call an MCP tool. full_name is 'servername__toolname'."""
        parts = full_name.split("__", 1)
        if len(parts) != 2:
            return f"Error: Invalid MCP tool name: {full_name}"

        server_name, tool_name = parts
        if server_name not in self._servers:
            return f"Error: MCP server '{server_name}' not connected"
        if not self._servers[server_name].get("connected"):
            return f"Error: MCP server '{server_name}' is not connected"

        try:
            result = self._run_async(
                self._call_tool_async(server_name, tool_name, arguments)
            )
            return result
        except Exception as e:
            return f"Error calling {full_name}: {e}"

    async def _call_tool_async(self, server_name, tool_name, arguments):
        session = self._servers[server_name]["session"]
        result = await session.call_tool(tool_name, arguments=arguments)
        # Extract text content from result
        texts = []
        for block in result.content:
            if hasattr(block, "text"):
                texts.append(block.text)
            else:
                texts.append(str(block))
        return "\n".join(texts) if texts else "(no output)"

    def is_mcp_tool(self, tool_name):
        """Check if a tool name belongs to an MCP server."""
        if "__" not in tool_name:
            return False
        prefix = tool_name.split("__", 1)[0]
        # A tool prefixed `skill__` is owned by the skills layer, not MCP.
        if prefix == "skill":
            return False
        return prefix in self._servers
