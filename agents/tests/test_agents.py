"""
Unit and Integration Test Suite for AegisOps Multi-Agent Swarm
"""
import pytest
import asyncio
from agents.core.state import IncidentState, IncidentPhase, ActionType
from agents.core.guardrails import GuardrailEngine
from agents.core.mcp_client import MCPToolClient
from agents.triage_agent import TriageAgent
from agents.security_agent import SecurityAgent
from agents.remediation_agent import RemediationAgent
from agents.scribe_agent import ScribeAgent
from agents.orchestrator import AegisOpsOrchestrator


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


def test_triage_agent_rca():
    async def _run():
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
        assert res_state.selected_root_cause.confidence >= 0.90
        assert "8f3b92c1" in res_state.selected_root_cause.culprit_artifact

    asyncio.run(_run())


def test_remediation_and_security_flow():
    async def _run():
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

    asyncio.run(_run())


def test_scribe_agent_generates_valid_postmortem():
    async def _run():
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

    asyncio.run(_run())


def test_full_orchestrator_lifecycle():
    async def _run():
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

    asyncio.run(_run())
