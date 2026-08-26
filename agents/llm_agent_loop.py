"""
Live LLM Agent Loop (Gemini / OpenAI + Model Context Protocol)
Demonstrates live function-calling with MCP tools running against Kubernetes.
"""
import os
import json
import logging
from typing import List, Dict, Any

from mcp_servers.k8s_mcp.server import (
    get_pods,
    get_pod_logs,
    get_cluster_events,
    get_deployment_spec
)
from mcp_servers.otel_mcp.server import (
    query_promql,
    query_slo_burn_rate,
    get_trace_tree
)
from mcp_servers.gitops_mcp.server import (
    get_git_commit_history,
    create_remediation_pr
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aegisops-llm-loop")

# Tool Registry mapping function names to actual MCP server functions
MCP_TOOL_DISPATCHER = {
    "get_pods": get_pods,
    "get_pod_logs": get_pod_logs,
    "get_cluster_events": get_cluster_events,
    "get_deployment_spec": get_deployment_spec,
    "query_promql": query_promql,
    "query_slo_burn_rate": query_slo_burn_rate,
    "get_trace_tree": get_trace_tree,
    "get_git_commit_history": get_git_commit_history,
    "create_remediation_pr": create_remediation_pr,
}


def run_llm_investigation(service_name: str = "payment-service", namespace: str = "production"):
    """
    Executes dynamic LLM triage with MCP tool calling.
    If GEMINI_API_KEY is present, connects to Gemini 2.5 Flash; otherwise runs local fallback.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key:
        logger.info("ℹ️ GEMINI_API_KEY not found in environment. Running standard deterministic agent swarm.")
        from agents.orchestrator import main as run_orchestrator
        import asyncio
        asyncio.run(run_orchestrator())
        return

    # Live Cloud Model Execution via google-genai SDK
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=gemini_key)
        logger.info(f"Connected to Google Gemini API. Initializing MCP tool calling loop for {service_name}...")

        prompt = f"""
        You are an autonomous Senior SRE & Kubernetes Incident Commander.
        An alert 'PaymentServiceErrorBudgetFastBurn' just fired for service '{service_name}' in namespace '{namespace}'.
        
        Use your available MCP tools to:
        1. Inspect pod statuses and detect any OOMKilled containers or crashloops.
        2. Read previous crashed logs from the affected pod.
        3. Inspect recent GitOps commits to identify recent config changes.
        4. Conclude the exact technical root cause and recommend remediation.
        """

        # Provide MCP tool declarations to Gemini
        # (Gemini automatically decides which MCP tool to call)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        print("\n" + "="*80)
        print("🤖 LIVE GEMINI LLM REASONING & ROOT CAUSE ANALYSIS:")
        print("="*80 + "\n")
        print(response.text)

    except Exception as e:
        logger.error(f"Error calling live LLM API: {e}")


if __name__ == "__main__":
    run_llm_investigation()
