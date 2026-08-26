"""
Unified MCP Client and Tool Dispatcher for AegisOps AI Agents
Interfaces with k8s-mcp, otel-mcp, and gitops-mcp servers.
"""
import json
import logging
from typing import Dict, Any, List, Optional

# Import underlying server tool functions
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


class MCPToolClient:
    """Provides a clean API for agents to call MCP server tools."""

    @staticmethod
    def call_tool(server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call to the appropriate MCP server."""
        logger.info(f"MCP Call -> [{server_name}] {tool_name}({arguments})")
        
        try:
            # 1. K8s MCP Server
            if server_name == "k8s-mcp":
                if tool_name == "get_pods":
                    raw = get_pods(namespace=arguments.get("namespace", "production"))
                    return json.loads(raw)
                elif tool_name == "get_pod_logs":
                    raw = get_pod_logs(
                        pod_name=arguments["pod_name"],
                        namespace=arguments.get("namespace", "production"),
                        tail_lines=arguments.get("tail_lines", 50),
                        previous=arguments.get("previous", False)
                    )
                    return {"logs": raw}
                elif tool_name == "get_cluster_events":
                    raw = get_cluster_events(
                        namespace=arguments.get("namespace", "production"),
                        limit=arguments.get("limit", 25)
                    )
                    return json.loads(raw)
                elif tool_name == "get_deployment_spec":
                    raw = get_deployment_spec(
                        deployment_name=arguments["deployment_name"],
                        namespace=arguments.get("namespace", "production")
                    )
                    return json.loads(raw)

            # 2. OpenTelemetry & O11y MCP Server
            elif server_name == "otel-mcp":
                if tool_name == "query_promql":
                    raw = query_promql(query=arguments["query"])
                    return json.loads(raw)
                elif tool_name == "query_slo_burn_rate":
                    raw = query_slo_burn_rate(
                        service_name=arguments["service_name"],
                        window=arguments.get("window", "1h")
                    )
                    return json.loads(raw)
                elif tool_name == "query_loki_logs":
                    raw = query_loki_logs(
                        logql_query=arguments["logql_query"],
                        limit=arguments.get("limit", 25)
                    )
                    return json.loads(raw)
                elif tool_name == "get_trace_tree":
                    raw = get_trace_tree(trace_id=arguments["trace_id"])
                    return json.loads(raw)

            # 3. GitOps MCP Server
            elif server_name == "gitops-mcp":
                if tool_name == "get_argocd_sync_status":
                    raw = get_argocd_sync_status(app_name=arguments.get("app_name", "payment-service"))
                    return json.loads(raw)
                elif tool_name == "get_git_commit_history":
                    raw = get_git_commit_history(
                        repo=arguments.get("repo", "gitops-repo"),
                        service=arguments.get("service", "payment-service"),
                        limit=arguments.get("limit", 5)
                    )
                    return json.loads(raw)
                elif tool_name == "create_remediation_pr":
                    raw = create_remediation_pr(
                        repo=arguments["repo"],
                        branch=arguments["branch"],
                        title=arguments["title"],
                        file_path=arguments["file_path"],
                        patch_content=arguments["patch_content"]
                    )
                    return json.loads(raw)
                elif tool_name == "trigger_argocd_sync":
                    raw = trigger_argocd_sync(
                        app_name=arguments["app_name"],
                        prune=arguments.get("prune", True)
                    )
                    return json.loads(raw)

            raise ValueError(f"Unknown tool '{tool_name}' on MCP server '{server_name}'")
        except Exception as e:
            logger.error(f"Error executing MCP tool {server_name}/{tool_name}: {e}")
            return {"error": str(e), "server": server_name, "tool": tool_name}
