"""
Deterministic Security Guardrails and Blast-Radius Policy Engine for AegisOps
"""
import re
from typing import Dict, Any, List, Tuple
from agents.core.state import SecurityAudit, ActionType


PROHIBITED_COMMAND_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"drop\s+database",
    r"drop\s+table",
    r"kubectl\s+delete\s+namespace",
    r"kubectl\s+delete\s+node",
    r"--privileged",
    r"chmod\s+777"
]


class GuardrailEngine:
    """Evaluates agent-proposed remediation actions for security and safety."""

    @staticmethod
    def audit_remediation_proposal(
        action_type: ActionType,
        target_service: str,
        target_namespace: str,
        patch_spec: Dict[str, Any]
    ) -> SecurityAudit:
        violations: List[str] = []
        risk_score = 3  # baseline

        # 1. Namespace Isolation Check
        if target_namespace in ["kube-system", "kube-public", "aegisops-system"]:
            violations.append(f"Direct automated modifications to control plane namespace '{target_namespace}' are forbidden.")
            risk_score += 4

        # 2. Check for Privileged Escalation / Root User in Patches
        patch_str = str(patch_spec).lower()
        if "privileged" in patch_str and "true" in patch_str:
            violations.append("Policy Violation: Container privileged mode cannot be enabled during remediation.")
            risk_score += 5
        if "allowprivilegeescalation" in patch_str and "true" in patch_str:
            violations.append("Policy Violation: Privilege escalation is disallowed under Kyverno baseline policy.")
            risk_score += 4

        # 3. Action-Type Specific Blast-Radius Scoring
        if action_type == ActionType.ROLLBACK_DEPLOYMENT:
            blast_radius = f"Reverts deployment '{target_service}' in namespace '{target_namespace}' to last known stable revision."
            risk_score = min(risk_score + 2, 6)
        elif action_type == ActionType.PATCH_RESOURCE_LIMITS:
            blast_radius = f"Adjusts CPU/Memory resource limits on '{target_service}'. Triggers rolling pod restart."
            risk_score = min(risk_score + 1, 5)
        elif action_type == ActionType.RESTART_PODS:
            blast_radius = f"Rolling restart of '{target_service}' pods (zero-downtime expected)."
            risk_score = min(risk_score, 4)
        elif action_type == ActionType.APPLY_GITOPS_PATCH:
            blast_radius = f"Creates PR on GitOps repo and initiates ArgoCD synchronization for '{target_service}'."
            risk_score = min(risk_score + 1, 5)
        else:
            blast_radius = f"General modification to '{target_service}'"
            risk_score = 7

        # 4. Human-In-The-Loop (HITL) Threshold
        # Any change to production with risk_score >= 3 requires human approval
        requires_hitl = target_namespace == "production" or risk_score >= 3 or len(violations) > 0

        is_compliant = len(violations) == 0

        notes = (
            f"Security Policy Evaluation: {'PASSED' if is_compliant else 'FAILED'}. "
            f"Blast radius is bounded to service '{target_service}'. "
            f"Human approval required: {requires_hitl}."
        )

        return SecurityAudit(
            is_compliant=is_compliant,
            risk_score=risk_score,
            blast_radius=blast_radius,
            policy_violations=violations,
            requires_human_approval=requires_hitl,
            audit_notes=notes
        )

    @staticmethod
    def validate_safe_command(command: str) -> Tuple[bool, str]:
        """Ensures commands executed by tools do not contain destructive or escaping primitives."""
        for pattern in PROHIBITED_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Prohibited command pattern detected: '{pattern}'"
        return True, "Command passed security sandbox validation."
