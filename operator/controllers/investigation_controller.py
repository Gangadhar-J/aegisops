"""
AegisOps Kubernetes Operator Controller (Kopf-based)
Reconciles InvestigationRun and RemediationPlan Custom Resources.
Triggers Autonomous Multi-Agent Swarm on Alert / SLO burn rate.
"""
import os
import sys
import asyncio
import logging
import kopf
from datetime import datetime

sys.path.insert(0, "/Users/gangadharreddy/projects/ai-labs/aegisops")
from agents.orchestrator import AegisOpsOrchestrator
from agents.core.state import IncidentState, IncidentPhase

logger = logging.getLogger("aegisops-operator")
orchestrator = AegisOpsOrchestrator()


@kopf.on.create("aegisops.io", "v1alpha1", "investigationruns")
async def on_investigation_run_created(spec, name, namespace, patch, **kwargs):
    """
    Triggered whenever an alert manager webhook creates an InvestigationRun CR.
    Spins up the autonomous multi-agent swarm to triage and formulate a remediation plan.
    """
    incident_id = spec.get("incidentId", name)
    target_service = spec.get("targetService", "payment-service")
    trigger_source = spec.get("triggerSource", "ALERT_SLO_BURN")
    target_ns = spec.get("targetNamespace", "production")

    logger.info(f"Operator intercepted new InvestigationRun: {name} in ns {namespace} for service {target_service}")

    patch.status["phase"] = "TRIAGING"
    patch.status["timeline"] = [
        {"timestamp": datetime.utcnow().isoformat() + "Z", "stage": "OPERATOR_DISPATCH", "message": f"Operator triggered agent swarm for {trigger_source}"}
    ]

    # Initialize State
    state = IncidentState(
        incident_id=incident_id,
        service_name=target_service,
        namespace=target_ns,
        trigger_alert=trigger_source
    )

    # Run Autonomous Investigation
    state = await orchestrator.run_investigation(state)

    # Update CRD Status with Triage findings
    patch.status["phase"] = "WAITING_APPROVAL"
    patch.status["rootCauseSummary"] = state.selected_root_cause.statement if state.selected_root_cause else ""
    patch.status["confidenceScore"] = state.selected_root_cause.confidence if state.selected_root_cause else 0.0
    patch.status["culpritCommitOrConfig"] = state.selected_root_cause.culprit_artifact if state.selected_root_cause else ""
    patch.status["associatedRemediationPlan"] = f"rem-{name}"

    timeline_entries = [
        {"timestamp": t.timestamp, "stage": t.stage, "message": f"[{t.agent_name}] {t.message}"}
        for t in state.timeline
    ]
    patch.status["timeline"] = timeline_entries

    logger.info(f"InvestigationRun {name} processed. Status: WAITING_APPROVAL. Root Cause: {patch.status['rootCauseSummary']}")


@kopf.on.update("aegisops.io", "v1alpha1", "remediationplans", field="status.approvalStatus")
async def on_remediation_plan_approved(old, new, spec, status, name, namespace, patch, **kwargs):
    """
    Triggered when an SRE approves the RemediationPlan CR via IDP portal or kubectl patch.
    """
    if new == "APPROVED" and old != "APPROVED":
        logger.info(f"RemediationPlan {name} APPROVED by user. Triggering automated reconciliation.")
        patch.status["executionStatus"] = "IN_PROGRESS"
        patch.status["approvedAt"] = datetime.utcnow().isoformat() + "Z"

        # Apply GitOps sync
        target_service = spec.get("targetResource", "payment-service")
        sync_res = orchestrator.remediation_agent.mcp.call_tool("gitops-mcp", "trigger_argocd_sync", {
            "app_name": target_service,
            "prune": True
        })

        patch.status["executionStatus"] = "SUCCEEDED"
        patch.status["executionOutput"] = f"ArgoCD synchronized target revision: {sync_res.get('message')}"
        logger.info(f"RemediationPlan {name} executed successfully.")
