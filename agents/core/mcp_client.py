"""
Unified MCP Client and Tool Dispatcher for AegisOps AI Agents
Interfaces with k8s-mcp, otel-mcp, and gitops-mcp servers.
Raises MCPToolCallError on failure so agents can handle it explicitly.
"""
import os
import json
import logging
from typing import Dict, Any, Optional
import httpx

# Import underlying server tool functions for in-process mode
from mcp_servers.k8s_mcp.server import (
    get_pods,
    get_pod_logs,
    get_cluster_events,
    get_deployment_spec
)
from mcp_servers.otel_mcp.server import (
    query_promql,
    query_slo_burn_rate,
    query_loki_logs,
    get_trace_tree
)
from mcp_servers.gitops_mcp.server import (
    get_argocd_sync_status,
    get_git_commit_history,
    create_remediation_pr,
    trigger_argocd_sync
)

logger = logging.getLogger("aegisops-mcp-client")

# Remote MCP Server Endpoints (for standalone container/Kubernetes deployments)
REMOTE_MCP_ENDPOINTS = {
    "k8s-mcp": os.getenv("K8S_MCP_URL", ""),
    "otel-mcp": os.getenv("OTEL_MCP_URL", ""),
    "gitops-mcp": os.getenv("GITOPS_MCP_URL", ""),
}
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "inprocess")  # "inprocess" | "http"


class MCPToolCallError(RuntimeError):
    """Raised when an MCP tool call fails, so agents can react explicitly."""
    def __init__(self, server: str, tool: str, cause: Exception):
        self.server = server
        self.tool = tool
        self.cause = cause
        super().__init__(f"MCP tool call failed: [{server}] {tool}() -> {type(cause).__name__}: {cause}")


class MCPToolClient:
    """Provides a clean API for agents to call MCP server tools via in-process or HTTP transport."""

    @staticmethod
    def call_tool(server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call to the appropriate MCP server.
        
        Supports both in-process dispatch and remote HTTP transport.
        Raises:
            MCPToolCallError: If the tool execution fails. Agents MUST catch this
                              and handle accordingly (retry, fallback, or fail the incident).
        """
        logger.info(f"MCP Call -> [{server_name}] {tool_name}({arguments})")

        remote_url = REMOTE_MCP_ENDPOINTS.get(server_name)
        if MCP_TRANSPORT == "http" and remote_url:
            return MCPToolClient._dispatch_remote(remote_url, server_name, tool_name, arguments)

        try:
            raw = MCPToolClient._dispatch(server_name, tool_name, arguments)
            if isinstance(raw, str):
                return json.loads(raw)
            return raw
        except MCPToolCallError:
            raise  # re-raise our typed error as-is
        except Exception as e:
            logger.error(f"MCP tool [{server_name}] {tool_name} raised an unexpected error: {e}")
            raise MCPToolCallError(server_name, tool_name, e) from e

    @staticmethod
    def _dispatch_remote(base_url: str, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches an MCP tool call to an external MCP HTTP server."""
        url = f"{base_url.rstrip('/')}/call_tool"
        payload = {"tool": tool_name, "arguments": arguments}
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, str):
                    return json.loads(data)
                return data
        except Exception as e:
            logger.error(f"Remote MCP HTTP call to [{server_name}] at {url} failed: {e}")
            raise MCPToolCallError(server_name, tool_name, e) from e

    @staticmethod
    def _dispatch(server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Internal dispatcher. Raises ValueError for unknown tools."""
        # 1. K8s MCP Server
        if server_name == "k8s-mcp":
            if tool_name == "get_pods":
                return get_pods(namespace=arguments.get("namespace", "production"))
            elif tool_name == "get_pod_logs":
                raw = get_pod_logs(
                    pod_name=arguments["pod_name"],
                    namespace=arguments.get("namespace", "production"),
                    tail_lines=arguments.get("tail_lines", 50),
                    previous=arguments.get("previous", False)
                )
                return {"logs": raw}
            elif tool_name == "get_cluster_events":
                return get_cluster_events(
                    namespace=arguments.get("namespace", "production"),
                    limit=arguments.get("limit", 25)
                )
            elif tool_name == "get_deployment_spec":
                return get_deployment_spec(
                    deployment_name=arguments["deployment_name"],
                    namespace=arguments.get("namespace", "production")
                )

        # 2. OpenTelemetry & O11y MCP Server
        elif server_name == "otel-mcp":
            if tool_name == "query_promql":
                return query_promql(query=arguments["query"])
            elif tool_name == "query_slo_burn_rate":
                return query_slo_burn_rate(
                    service_name=arguments["service_name"],
                    window=arguments.get("window", "1h")
                )
            elif tool_name == "query_loki_logs":
                return query_loki_logs(
                    logql_query=arguments["logql_query"],
                    limit=arguments.get("limit", 25)
                )
            elif tool_name == "get_trace_tree":
                return get_trace_tree(trace_id=arguments["trace_id"])

        # 3. GitOps MCP Server
        elif server_name == "gitops-mcp":
            if tool_name == "get_argocd_sync_status":
                return get_argocd_sync_status(app_name=arguments.get("app_name", "payment-service"))
            elif tool_name == "get_git_commit_history":
                return get_git_commit_history(
                    repo=arguments.get("repo", "gitops-repo"),
                    service=arguments.get("service", "payment-service"),
                    limit=arguments.get("limit", 5)
                )
            elif tool_name == "create_remediation_pr":
                return create_remediation_pr(
                    repo=arguments["repo"],
                    branch=arguments["branch"],
                    title=arguments["title"],
                    file_path=arguments["file_path"],
                    patch_content=arguments["patch_content"]
                )
            elif tool_name == "trigger_argocd_sync":
                return trigger_argocd_sync(
                    app_name=arguments["app_name"],
                    prune=arguments.get("prune", True)
                )

        raise ValueError(f"Unknown tool '{tool_name}' on MCP server '{server_name}'")
