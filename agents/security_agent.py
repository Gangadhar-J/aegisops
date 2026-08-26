"""
Security & Policy Guardrail Agent
Validates remediation plans against Kyverno cluster policies, namespace security, and blast-radius risk scoring.
"""
import logging
from typing import Dict, Any
from agents.core.state import IncidentState, IncidentPhase, ActionType, SecurityAudit
from agents.core.guardrails import GuardrailEngine

logger = logging.getLogger("aegisops-security-agent")


class SecurityAgent:
    """Audits proposed remediations to guarantee zero unintended security or reliability side effects."""

    def __init__(self):
        self.guardrail_engine = GuardrailEngine()

    async def audit_plan(
        self,
        state: IncidentState,
        action_type: ActionType,
        proposed_patch: Dict[str, Any]
    ) -> IncidentState:
        logger.info(f"Evaluating Security & Policy compliance for incident {state.incident_id}")
        state.phase = IncidentPhase.EVALUATING_SECURITY
        state.add_timeline("SecurityAgent", "SECURITY_AUDIT_STARTED", f"Auditing proposed action '{action_type}' for service '{state.service_name}'")

        audit: SecurityAudit = self.guardrail_engine.audit_remediation_proposal(
            action_type=action_type,
            target_service=state.service_name,
            target_namespace=state.namespace,
            patch_spec=proposed_patch
        )

        state.security_audit = audit

        if not audit.is_compliant:
            state.add_timeline(
                "SecurityAgent",
                "SECURITY_VIOLATION_DETECTED",
                f"Proposed patch rejected by guardrail policies: {'; '.join(audit.policy_violations)}"
            )
            state.phase = IncidentPhase.FAILED
            return state

        state.add_timeline(
            "SecurityAgent",
            "SECURITY_AUDIT_PASSED",
            f"Security check PASSED. Risk Score: {audit.risk_score}/10. Blast radius: {audit.blast_radius}. HITL approval required: {audit.requires_human_approval}"
        )
        return state
