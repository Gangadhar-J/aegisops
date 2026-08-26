"""
Model Context Protocol (MCP) FastMCP Compatibility Layer
Provides standard MCP Tool decorators, schema extraction, and JSON-RPC dispatch.
"""
import inspect
from typing import Callable, Dict, Any, List, Optional


class FastMCP:
    def __init__(self, name: str, dependencies: Optional[List[str]] = None):
        self.name = name
        self.dependencies = dependencies or []
        self._tools: Dict[str, Callable] = {}

    def tool(self, name: Optional[str] = None):
        def decorator(fn: Callable):
            tool_name = name or fn.__name__
            self._tools[tool_name] = fn
            return fn
        return decorator

    def list_tools(self) -> List[Dict[str, Any]]:
        tools = []
        for name, fn in self._tools.items():
            sig = inspect.signature(fn)
            doc = inspect.getdoc(fn) or ""
            params = {}
            for p_name, p in sig.parameters.items():
                p_type = "string"
                if p.annotation == int:
                    p_type = "integer"
                elif p.annotation == bool:
                    p_type = "boolean"
                elif p.annotation == float:
                    p_type = "number"
                params[p_name] = {"type": p_type, "default": p.default if p.default != inspect._empty else None}

            tools.append({
                "name": name,
                "description": doc.strip(),
                "parameters": params
            })
        return tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' not found in MCP server '{self.name}'")
        return self._tools[tool_name](**arguments)

    def run(self):
        print(f"MCP Server '{self.name}' initialized with tools: {list(self._tools.keys())}")


# Try official mcp import or fallback to compatibility layer
try:
    from mcp.server.fastmcp import FastMCP as OfficialFastMCP
    FastMCP = OfficialFastMCP
except ImportError:
    pass
