# ADR-003: Model Context Protocol (MCP) Dual-Transport Architecture

## Status
Accepted

## Context
AI agents require access to specialized tools across Kubernetes (`k8s-mcp`), Observability (`otel-mcp`), and GitOps (`gitops-mcp`). Standardizing on the Model Context Protocol (MCP) ensures interoperability with modern LLMs (Anthropic, Gemini, OpenAI). However, running tools requires different operational models:
- **Local Development / CLI**: In-process execution without container orchestration overhead or latency.
- **Enterprise Multi-Tenant Production**: Standalone microservice Deployments with separate RBAC, network policies, horizontal scaling, and audit logging.

## Decision
AegisOps implements a dual-transport `MCPToolClient`:
1. **In-Process Dispatcher**: Directly invokes Python tool callables when `MCP_TRANSPORT == "inprocess"`, enabling sub-millisecond execution and straightforward local unit testing without running sidecars.
2. **Remote HTTP / JSON-RPC Transport**: When `MCP_TRANSPORT == "http"` and environment endpoints (`K8S_MCP_URL`, `OTEL_MCP_URL`, `GITOPS_MCP_URL`) are populated, calls remote MCP services over HTTP.
3. **Data Source Metadata Tagging**: All responses (live vs simulated) include `"data_source": "kubernetes_live" | "simulated_dev" | "error"` to guarantee transparency.
4. **Typed Error Isolation (`MCPToolCallError`)**: Tool failures (network timeouts, 403 Forbidden, 500 errors) are encapsulated into typed exceptions, preventing unhandled exceptions from crashing agent loops.

## Consequences
### Positive
- Developers can test the full swarm locally in under 6 seconds without Docker or Kubernetes.
- In production, each MCP server can be isolated into its own Kubernetes Pod with dedicated least-privilege service accounts.
- Zero code changes required in agents when migrating between in-process and remote modes.
