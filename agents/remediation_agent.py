"""
Remediation & GitOps Agent
Generates safe, rollback-capable patches, opens GitOps pull requests, and orchestrates remediation execution.
"""
import logging
from typing import Dict, Any
from agents.core.state import IncidentState, IncidentPhase, ActionType, RemediationPlan
from agents.core.mcp_client import MCPToolClient

logger = logging.getLogger("aegisops-remediation-agent")


class RemediationAgent:
    """Formulates and executes remediation plans with automated GitOps rollback workflows."""

    def __init__(self, mcp_client: MCPToolClient = None):
        self.mcp = mcp_client or MCPToolClient()

    async def formulate_plan(self, state: IncidentState) -> IncidentState:
        logger.info(f"Formulating Remediation Plan for incident {state.incident_id}")
        state.phase = IncidentPhase.PLAN_FORMULATED
        state.add_timeline("RemediationAgent", "PLAN_FORMULATION", "Designing safe remediation patch and rollback strategy")

        is_security_incident = "Security" in state.trigger_alert or "Falco" in state.trigger_alert

        if is_security_incident:
            # Security Hardening & Isolation Patch
            patch_spec = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": state.service_name,
                                    "securityContext": {
                                        "runAsNonRoot": True,
                                        "runAsUser": 10001,
                                        "allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True
                                    }
                                }
                            ]
                        }
                    }
                }
            }
            pr_title = f"security(fix): enforce non-root (UID 10001) & read-only filesystem on {state.service_name}"
            pr_branch = f"sec-hotfix/{state.incident_id}-enforce-non-root"
        else:
            # Standard Resource / Memory Fix
            patch_spec = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": state.service_name,
                                    "resources": {
                                        "limits": {"memory": "512Mi", "cpu": "500m"},
                                        "requests": {"memory": "256Mi", "cpu": "100m"}
                                    },
                                    "env": [
                                        {"name": "DB_MAX_CONNECTIONS", "value": "50"},
                                        {"name": "CONNECTION_TIMEOUT_MS", "value": "5000"}
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
            pr_title = f"fix(hotfix): restore 512Mi memory limits & 50 db connections for {state.service_name}"
            pr_branch = f"hotfix/{state.incident_id}-memory-and-pool-tune"

        pr_data = self.mcp.call_tool("gitops-mcp", "create_remediation_pr", {
            "repo": "gitops-repo",
            "branch": pr_branch,
            "title": pr_title,
            "file_path": f"k8s/demo-apps/{state.service_name}.yaml",
            "patch_content": str(patch_spec)
        })

        rollback_command = f"kubectl rollout undo deployment/{state.service_name} -n {state.namespace}"

        state.remediation_plan = RemediationPlan(
            action_type=ActionType.APPLY_GITOPS_PATCH,
            target_service=state.service_name,
            target_namespace=state.namespace,
            proposed_patch=patch_spec,
            rollback_command=rollback_command,
            gitops_pr_url=pr_data.get("pull_request_url"),
            approval_status="PENDING_HITL"
        )

        state.add_timeline(
            "RemediationAgent",
            "PLAN_READY",
            f"Remediation Plan created. Opened GitOps PR: {pr_data.get('pull_request_url')}. Awaiting Human-in-the-Loop approval."
        )
        return state

    async def execute_remediation(self, state: IncidentState) -> IncidentState:
        if not state.remediation_plan or state.remediation_plan.approval_status != "APPROVED":
            logger.warning("Attempted to execute unapproved remediation plan.")
            return state

        logger.info(f"Executing approved remediation for incident {state.incident_id}")
        state.phase = IncidentPhase.REMEDIATING
        state.add_timeline("RemediationAgent", "EXECUTION_STARTED", f"Triggering ArgoCD sync for application '{state.service_name}'")

        sync_result = self.mcp.call_tool("gitops-mcp", "trigger_argocd_sync", {
            "app_name": state.service_name,
            "prune": True
        })

        state.add_timeline(
            "RemediationAgent",
            "EXECUTION_COMPLETED",
            f"ArgoCD reconciliation triggered successfully. Message: {sync_result.get('message')}"
        )
        return state
