"""
Live LLM Agent Loop (Gemini + Model Context Protocol)
Implements a ReAct-style function-calling loop where Gemini autonomously selects and invokes
MCP tools to investigate Kubernetes incidents.
"""
import os
import json
import logging
import inspect
from typing import Dict, Any

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

# MCP Tool Registry: maps function names to callables
MCP_TOOL_DISPATCHER: Dict[str, Any] = {
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

# Maximum iterations to prevent infinite tool-calling loops
MAX_TOOL_ITERATIONS = 10


def _build_tool_declarations():
    """
    Builds google-genai compatible tool declarations from the MCP tool registry.
    Each tool gets a name, description (from docstring), and parameters (from function signature).
    """
    try:
        from google.genai import types
    except ImportError:
        return []

    declarations = []
    for name, func in MCP_TOOL_DISPATCHER.items():
        params = {}
        sig = inspect.signature(func)
        for param_name, param in sig.parameters.items():
            annotation = param.annotation
            if annotation == int:
                params[param_name] = types.Schema(type="INTEGER", description=param_name)
            elif annotation == bool:
                params[param_name] = types.Schema(type="BOOLEAN", description=param_name)
            else:
                params[param_name] = types.Schema(type="STRING", description=param_name)

        declarations.append(types.FunctionDeclaration(
            name=name,
            description=(func.__doc__ or f"MCP tool: {name}").strip(),
            parameters=types.Schema(
                type="OBJECT",
                properties=params
            ) if params else None
        ))

    return [types.Tool(function_declarations=declarations)]


def _execute_tool_call(function_name: str, arguments: dict) -> str:
    """Dispatches a function call to the corresponding MCP tool and returns the result as a string."""
    if function_name not in MCP_TOOL_DISPATCHER:
        return json.dumps({"error": f"Unknown tool: {function_name}"})

    try:
        result = MCP_TOOL_DISPATCHER[function_name](**arguments)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        logger.error(f"Tool {function_name} execution failed: {e}")
        return json.dumps({"error": str(e)})


def run_llm_investigation(service_name: str = "payment-service", namespace: str = "production"):
    """
    Executes a ReAct-style LLM investigation with MCP tool calling.
    If GEMINI_API_KEY is present, connects to Gemini and runs an autonomous function-calling loop.
    Otherwise falls back to the deterministic agent swarm.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key:
        logger.info("GEMINI_API_KEY not found. Running deterministic agent swarm.")
        from agents.orchestrator import AegisOpsOrchestrator
        import asyncio

        async def _run_fallback():
            orchestrator = AegisOpsOrchestrator()
            state = await orchestrator.create_incident(
                service_name=service_name,
                namespace=namespace,
                trigger_alert="PaymentServiceErrorBudgetFastBurn"
            )
            state = await orchestrator.run_investigation(state)
            print(f"\nRoot Cause: {state.selected_root_cause.statement if state.selected_root_cause else 'Unknown'}")
            print(f"Phase: {state.phase.value}")

        try:
            loop = asyncio.get_running_loop()
            # Already inside an event loop (FastAPI / Jupyter) — create a task instead
            loop.create_task(_run_fallback())
        except RuntimeError:
            # No event loop running — safe to use asyncio.run()
            asyncio.run(_run_fallback())
        return

    # --- Live Gemini Function-Calling Loop ---
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=gemini_key)
        tools = _build_tool_declarations()
        logger.info(f"Connected to Gemini API. Registered {len(MCP_TOOL_DISPATCHER)} MCP tools.")

        prompt = (
            f"You are an autonomous Senior SRE & Kubernetes Incident Commander.\n"
            f"An alert 'PaymentServiceErrorBudgetFastBurn' fired for service '{service_name}' "
            f"in namespace '{namespace}'.\n\n"
            f"Use your available tools to:\n"
            f"1. Inspect pod statuses and detect OOMKilled containers or crashloops.\n"
            f"2. Read previous crashed logs from the affected pod.\n"
            f"3. Query SLO burn rate to assess error budget consumption.\n"
            f"4. Inspect recent GitOps commits to identify config changes.\n"
            f"5. Conclude the exact technical root cause and recommend remediation.\n\n"
            f"Call tools iteratively. After gathering enough evidence, provide your final analysis."
        )

        # Initial request with tool declarations
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]

        for iteration in range(MAX_TOOL_ITERATIONS):
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(tools=tools)
            )

            # Check if the model wants to call functions
            has_function_calls = False
            function_response_parts = []

            for part in response.candidates[0].content.parts:
                if part.function_call:
                    has_function_calls = True
                    fc = part.function_call
                    logger.info(f"[Iteration {iteration + 1}] Tool call: {fc.name}({dict(fc.args) if fc.args else {}})")

                    # Execute the MCP tool
                    tool_result = _execute_tool_call(fc.name, dict(fc.args) if fc.args else {})

                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": tool_result}
                        )
                    )

            if not has_function_calls:
                # Model has finished reasoning — print final answer
                print("\n" + "=" * 80)
                print("LIVE GEMINI LLM ROOT CAUSE ANALYSIS:")
                print("=" * 80 + "\n")
                for part in response.candidates[0].content.parts:
                    if part.text:
                        print(part.text)
                break

            # Feed tool results back to model for next iteration
            contents.append(response.candidates[0].content)
            contents.append(types.Content(role="user", parts=function_response_parts))

        else:
            logger.warning(f"Reached max tool iterations ({MAX_TOOL_ITERATIONS}). Forcing final output.")
            # Request a final summary without tools
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text="You have reached the maximum number of tool calls. Please provide your final root cause analysis and remediation recommendation now.")]
            ))
            final_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents
            )
            print("\n" + "=" * 80)
            print("LIVE GEMINI LLM ROOT CAUSE ANALYSIS (forced):")
            print("=" * 80 + "\n")
            print(final_response.text)

    except ImportError:
        logger.error("google-genai SDK not installed. Run: pip install google-genai")
    except Exception as e:
        logger.error(f"Gemini API error: {e}", exc_info=True)


if __name__ == "__main__":
    run_llm_investigation()
