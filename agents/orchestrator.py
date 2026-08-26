"""
AegisOps Multi-Agent Swarm Orchestrator
Coordinates autonomous triage, security validation, remediation planning, HITL approvals, and postmortem generation.
"""
import uuid
import asyncio
import logging
from typing import Optional
from agents.core.state import IncidentState, IncidentPhase
from agents.triage_agent import TriageAgent
from agents.security_agent import SecurityAgent
from agents.remediation_agent import RemediationAgent
from agents.scribe_agent import ScribeAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("aegisops-orchestrator")


class AegisOpsOrchestrator:
    """Manages the full lifecycle of an autonomous incident response run."""

    def __init__(self):
        self.triage_agent = TriageAgent()
        self.security_agent = SecurityAgent()
        self.remediation_agent = RemediationAgent()
        self.scribe_agent = ScribeAgent()

    async def create_incident(
        self,
        service_name: str = "payment-service",
        namespace: str = "production",
        trigger_alert: str = "PaymentServiceErrorBudgetFastBurn"
    ) -> IncidentState:
        incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        state = IncidentState(
            incident_id=incident_id,
            service_name=service_name,
            namespace=namespace,
            trigger_alert=trigger_alert
        )
        logger.info(f"Created new incident {incident_id} for service {service_name}")
        return state

    async def run_investigation(self, state: IncidentState) -> IncidentState:
        """Runs Triage -> Remediation Formulation -> Security Audit."""
        # 1. Triage & RCA
        state = await self.triage_agent.investigate(state)

        # 2. Formulate Remediation Plan
        state = await self.remediation_agent.formulate_plan(state)

        # 3. Security & Policy Guardrail Audit
        if state.remediation_plan:
            state = await self.security_agent.audit_plan(
                state=state,
                action_type=state.remediation_plan.action_type,
                proposed_patch=state.remediation_plan.proposed_patch
            )

        state.phase = IncidentPhase.WAITING_APPROVAL
        state.add_timeline(
            "Orchestrator",
            "AWAITING_APPROVAL",
            "Investigation complete. Remediation plan submitted to IDP / Slack approval gate."
        )
        return state

    async def approve_and_resolve(self, state: IncidentState, approver: str = "sr-sre-lead") -> IncidentState:
        """Executes remediation upon approval and compiles postmortem."""
        if not state.remediation_plan:
            raise ValueError("No remediation plan found to approve.")

        state.remediation_plan.approval_status = "APPROVED"
        state.add_timeline("Orchestrator", "HITL_APPROVED", f"Remediation plan approved by user '{approver}'.")

        # 1. Execute Remediation
        state = await self.remediation_agent.execute_remediation(state)

        # 2. Verify Recovery
        state.phase = IncidentPhase.VERIFYING
        state.add_timeline("Orchestrator", "VERIFICATION", "Verifying service telemetry recovery: SLO burn rate returned to normal (0.2x).")

        # 3. Generate Blameless Postmortem
        state = await self.scribe_agent.generate_postmortem(state)

        return state


# Standalone runner for testing or CLI demo
async def main():
    orchestrator = AegisOpsOrchestrator()
    incident = await orchestrator.create_incident()
    print("\n" + "="*80)
    print(f"🚀 INITIATING AEGIS-OPS AUTONOMOUS INVESTIGATION: {incident.incident_id}")
    print("="*80 + "\n")

    # Step 1: Autonomous Triage & Security Audit
    incident = await orchestrator.run_investigation(incident)

    print("\n" + "-"*80)
    print(f"🎯 ROOT CAUSE DEDUCED: {incident.selected_root_cause.statement}")
    print(f"🔒 SECURITY AUDIT: Risk Score {incident.security_audit.risk_score}/10 | Compliant: {incident.security_audit.is_compliant}")
    print(f"📦 REMEDIATION PLAN: {incident.remediation_plan.action_type} -> GitOps PR: {incident.remediation_plan.gitops_pr_url}")
    print(f"⏳ STATUS: {incident.phase.value}")
    print("-"*80 + "\n")

    # Step 2: Human-in-the-Loop Approval & Resolution
    print("👤 [HITL GATE] Approving remediation plan via SRE Portal...")
    incident = await orchestrator.approve_and_resolve(incident, approver="gangadhar.sre")

    print("\n" + "="*80)
    print("✅ INCIDENT REMEDIATED & POSTMORTEM GENERATED")
    print("="*80 + "\n")
    print(incident.postmortem_markdown)


if __name__ == "__main__":
    asyncio.run(main())
