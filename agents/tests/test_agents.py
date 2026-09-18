"""
Unit and Integration Test Suite for AegisOps Multi-Agent Swarm
Uses anyio for native async test support.
"""
import pytest
from agents.core.state import IncidentState, IncidentPhase, ActionType
from agents.core.guardrails import GuardrailEngine
from agents.core.mcp_client import MCPToolClient
from agents.triage_agent import TriageAgent
from agents.security_agent import SecurityAgent
from agents.remediation_agent import RemediationAgent
from agents.scribe_agent import ScribeAgent
from agents.orchestrator import AegisOpsOrchestrator


# --- Guardrail Tests (synchronous) ---

def test_guardrail_blocks_dangerous_commands():
    engine = GuardrailEngine()
    is_safe, msg = engine.validate_safe_command("rm -rf / --no-preserve-root")
    assert not is_safe
    assert "Prohibited command pattern detected" in msg

    is_safe, msg = engine.validate_safe_command("kubectl delete namespace production")
    assert not is_safe

    is_safe, msg = engine.validate_safe_command("kubectl rollout undo deployment/payment-service -n production")
    assert is_safe


def test_guardrail_evaluates_blast_radius():
    engine = GuardrailEngine()
    audit = engine.audit_remediation_proposal(
        action_type=ActionType.APPLY_GITOPS_PATCH,
        target_service="payment-service",
        target_namespace="production",
        patch_spec={"resources": {"limits": {"memory": "512Mi"}}}
    )
    assert audit.is_compliant is True
    assert audit.risk_score <= 5
    assert audit.requires_human_approval is True
    assert "payment-service" in audit.blast_radius


def test_guardrail_rejects_privileged_escalation():
    engine = GuardrailEngine()
    audit = engine.audit_remediation_proposal(
        action_type=ActionType.APPLY_GITOPS_PATCH,
        target_service="payment-service",
        target_namespace="production",
        patch_spec={"securityContext": {"privileged": True, "allowPrivilegeEscalation": True}}
    )
    assert audit.is_compliant is False
    assert len(audit.policy_violations) > 0


# --- Agent Tests (native async with anyio) ---

@pytest.mark.anyio
async def test_triage_agent_rca():
    triage = TriageAgent()
    state = IncidentState(
        incident_id="TEST-INC-001",
        service_name="payment-service",
        namespace="production",
        trigger_alert="PaymentServiceErrorBudgetFastBurn"
    )
    res_state = await triage.investigate(state)

    assert res_state.phase == IncidentPhase.HYPOTHESIS_TESTING
    assert len(res_state.evidence) >= 4
    assert res_state.selected_root_cause is not None
    assert res_state.selected_root_cause.confidence >= 0.80


@pytest.mark.anyio
async def test_remediation_and_security_flow():
    remediation = RemediationAgent()
    security = SecurityAgent()

    state = IncidentState(
        incident_id="TEST-INC-002",
        service_name="payment-service",
        namespace="production",
        trigger_alert="PaymentServiceErrorBudgetFastBurn"
    )
    state = await remediation.formulate_plan(state)
    assert state.remediation_plan is not None
    assert state.remediation_plan.gitops_pr_url is not None

    state = await security.audit_plan(
        state=state,
        action_type=state.remediation_plan.action_type,
        proposed_patch=state.remediation_plan.proposed_patch
    )
    assert state.security_audit is not None
    assert state.security_audit.is_compliant is True


@pytest.mark.anyio
async def test_scribe_agent_generates_valid_postmortem():
    scribe = ScribeAgent()
    state = IncidentState(
        incident_id="TEST-INC-003",
        service_name="payment-service",
        namespace="production",
        trigger_alert="PaymentServiceErrorBudgetFastBurn"
    )
    state = await scribe.generate_postmortem(state)
    assert state.postmortem_markdown is not None
    assert "# 📑 Blameless Incident Postmortem" in state.postmortem_markdown
    assert "Executive Summary" in state.postmortem_markdown
    assert "Root Cause Analysis" in state.postmortem_markdown
    assert "Preventative Action Items" in state.postmortem_markdown


@pytest.mark.anyio
async def test_full_orchestrator_lifecycle():
    orchestrator = AegisOpsOrchestrator()
    state = await orchestrator.create_incident()

    # 1. Investigation
    state = await orchestrator.run_investigation(state)
    assert state.phase == IncidentPhase.WAITING_APPROVAL
    assert state.remediation_plan.approval_status == "PENDING_HITL"

    # 2. Approval
    state = await orchestrator.approve_and_resolve(state, approver="senior-sre")
    assert state.phase == IncidentPhase.COMPLETED
    assert state.remediation_plan.approval_status == "APPROVED"
    assert state.postmortem_markdown is not None


@pytest.mark.anyio
async def test_mcp_tool_call_error_propagates():
    """Verify MCPToolCallError is raised and NOT silently swallowed."""
    from agents.core.mcp_client import MCPToolCallError
    client = MCPToolClient()
    with pytest.raises((MCPToolCallError, ValueError)):
        client.call_tool("k8s-mcp", "nonexistent_tool", {})


@pytest.mark.anyio
async def test_security_incident_triage():
    triage = TriageAgent()
    state = IncidentState(
        incident_id="TEST-SEC-001",
        service_name="payment-service",
        namespace="production",
        trigger_alert="FalcoRuntimeThreatDetected"
    )
    res_state = await triage.investigate(state)
    assert res_state.selected_root_cause is not None
    assert "SECURITY" in res_state.selected_root_cause.root_cause_category
    assert res_state.selected_root_cause.confidence >= 0.95


def test_guardrail_structured_privilege_inspection_prevents_false_positive():
    """Verify that a patch with privileged=False but another field=True is NOT falsely rejected."""
    engine = GuardrailEngine()
    audit = engine.audit_remediation_proposal(
        action_type=ActionType.APPLY_GITOPS_PATCH,
        target_service="payment-service",
        target_namespace="production",
        patch_spec={
            "securityContext": {"privileged": False, "allowPrivilegeEscalation": False},
            "enableLogging": True,
            "metricsEnabled": "true"
        }
    )
    assert audit.is_compliant is True
    assert len(audit.policy_violations) == 0


def test_guardrail_blocks_kube_node_lease_namespace():
    """Verify that kube-node-lease is rejected by namespace isolation."""
    engine = GuardrailEngine()
    audit = engine.audit_remediation_proposal(
        action_type=ActionType.APPLY_GITOPS_PATCH,
        target_service="node-agent",
        target_namespace="kube-node-lease",
        patch_spec={"resources": {"limits": {"memory": "256Mi"}}}
    )
    assert audit.is_compliant is False
    assert any("kube-node-lease" in v for v in audit.policy_violations)


def test_otel_mcp_injection_sanitization():
    """Verify that PromQL injection and path traversal are rejected."""
    import json
    from mcp_servers.otel_mcp.server import query_slo_burn_rate, get_trace_tree

    # 1. PromQL injection attempt
    slo_res = json.loads(query_slo_burn_rate('payment"; DROP TABLE logs;--'))
    assert slo_res.get("status") == "error"
    assert "Invalid service_name" in slo_res.get("error", "")

    # 2. Path traversal attempt
    trace_res = json.loads(get_trace_tree("../../../etc/passwd"))
    assert trace_res.get("status") == "error"
    assert "Invalid trace_id" in trace_res.get("error", "")


def test_k8s_mcp_redacts_sensitive_env_vars():
    """Verify that sensitive environment variables are masked in get_deployment_spec."""
    from mcp_servers.k8s_mcp.server import _sanitize_env_vars

    raw_env = [
        {"name": "DATABASE_PASSWORD", "value": "supersecret123"},
        {"name": "API_KEY", "value": "live_sk_abcdef123456"},
        {"name": "AUTH_TOKEN", "value": "eyJhbGciOi..."},
        {"name": "SERVICE_NAME", "value": "payment-service"},
        {"name": "PORT", "value": "8080"}
    ]
    sanitized = _sanitize_env_vars(raw_env)
    sanitized_map = {list(item.keys())[0]: list(item.values())[0] for item in sanitized}

    assert sanitized_map["DATABASE_PASSWORD"] == "[REDACTED_SECRET]"
    assert sanitized_map["API_KEY"] == "[REDACTED_SECRET]"
    assert sanitized_map["AUTH_TOKEN"] == "[REDACTED_SECRET]"
    assert sanitized_map["SERVICE_NAME"] == "payment-service"
    assert sanitized_map["PORT"] == "8080"


def test_gitops_mcp_blocks_path_traversal():
    """Verify that create_remediation_pr rejects directory traversal in file_path."""
    import json
    from mcp_servers.gitops_mcp.server import create_remediation_pr

    res = json.loads(create_remediation_pr(
        repo="gitops-repo",
        branch="hotfix/exploit",
        title="Malicious PR",
        file_path="../../etc/shadow",
        patch_content="root::0:0:root:/:/bin/sh"
    ))
    assert res.get("status") == "ERROR"
    assert "traversal" in res.get("error", "").lower()


def test_gitops_mcp_production_mode_structured_error():
    """Verify that in production mode with missing credentials, gitops-mcp returns structured error."""
    import json, os
    from mcp_servers.gitops_mcp import server as gitops_srv

    orig_env = gitops_srv.AEGISOPS_ENV
    orig_token = gitops_srv.ARGOCD_AUTH_TOKEN
    try:
        gitops_srv.AEGISOPS_ENV = "production"
        gitops_srv.ARGOCD_AUTH_TOKEN = "test-token"
        gitops_srv.ARGOCD_SERVER = "http://127.0.0.1:59999"  # unreachable

        sync_res = json.loads(gitops_srv.trigger_argocd_sync("payment-service"))
        assert sync_res.get("status") == "ERROR"
        assert sync_res.get("data_source") == "error"
    finally:
        gitops_srv.AEGISOPS_ENV = orig_env
        gitops_srv.ARGOCD_AUTH_TOKEN = orig_token


def test_mcp_client_remote_http_dispatch():
    """Verify that MCPToolClient routes to remote HTTP when configured and raises MCPToolCallError on unreachable host."""
    from agents.core.mcp_client import MCPToolClient, MCPToolCallError, REMOTE_MCP_ENDPOINTS
    import agents.core.mcp_client as client_module

    orig_transport = client_module.MCP_TRANSPORT
    orig_endpoint = REMOTE_MCP_ENDPOINTS.get("otel-mcp")
    try:
        client_module.MCP_TRANSPORT = "http"
        REMOTE_MCP_ENDPOINTS["otel-mcp"] = "http://127.0.0.1:59998"

        client = MCPToolClient()
        with pytest.raises(MCPToolCallError) as exc_info:
            client.call_tool("otel-mcp", "query_slo_burn_rate", {"service_name": "payment-service"})
        assert "otel-mcp" in str(exc_info.value)
    finally:
        client_module.MCP_TRANSPORT = orig_transport
        REMOTE_MCP_ENDPOINTS["otel-mcp"] = orig_endpoint


def test_payment_service_chaos_guards():
    """Verify that payment-service chaos endpoints enforce parameter bounds and auth."""
    import importlib.util
    from pathlib import Path
    from fastapi.testclient import TestClient

    payment_service_path = Path(__file__).parents[2] / "apps" / "demo-services" / "payment-service" / "main.py"
    spec = importlib.util.spec_from_file_location("payment_main", str(payment_service_path))
    payment_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(payment_main)

    test_client = TestClient(payment_main.app)

    # 1. Parameter validation: mb_to_leak exceeding max (256) should fail with 422 Unprocessable Entity
    resp = test_client.post("/chaos/leak-memory?mb_to_leak=1000")
    assert resp.status_code == 422

    # 2. Authentication: if CHAOS_SECRET is set, unauthenticated call must be rejected with 401
    payment_main.CHAOS_SECRET = "secure-chaos-secret"
    try:
        resp_unauth = test_client.post("/chaos/leak-memory?mb_to_leak=10")
        assert resp_unauth.status_code == 401

        resp_auth = test_client.post("/chaos/leak-memory?mb_to_leak=10", headers={"X-Chaos-Secret": "secure-chaos-secret"})
        assert resp_auth.status_code == 200
    finally:
        payment_main.CHAOS_SECRET = ""
        payment_main.chaos_reset_memory()


