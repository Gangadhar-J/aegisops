"""
Incident State and Data Models for AegisOps Multi-Agent Swarm
"""
from typing import List, Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentPhase(str, Enum):
    INITIALIZING = "INITIALIZING"
    TRIAGING = "TRIAGING"
    HYPOTHESIS_TESTING = "HYPOTHESIS_TESTING"
    EVALUATING_SECURITY = "EVALUATING_SECURITY"
    PLAN_FORMULATED = "PLAN_FORMULATED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ActionType(str, Enum):
    ROLLBACK_DEPLOYMENT = "ROLLBACK_DEPLOYMENT"
    PATCH_RESOURCE_LIMITS = "PATCH_RESOURCE_LIMITS"
    RESTART_PODS = "RESTART_PODS"
    SCALE_REPLICAS = "SCALE_REPLICAS"
    APPLY_GITOPS_PATCH = "APPLY_GITOPS_PATCH"


class EvidenceItem(BaseModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    source: str  # e.g., "k8s-mcp", "otel-mcp", "gitops-mcp"
    evidence_type: str  # e.g., "METRIC", "LOG", "TRACE", "K8S_EVENT", "GIT_DIFF"
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)


class Hypothesis(BaseModel):
    id: str
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    root_cause_category: str  # e.g. "RESOURCE_EXHAUSTION", "CODE_DEFECT", "CONFIG_REGRESSION", "SECURITY_BREACH"
    culprit_artifact: Optional[str] = None  # e.g., "Commit 8f3b92c1" or "Memory limit 256Mi"
    supporting_evidence_ids: List[str] = Field(default_factory=list)


class SecurityAudit(BaseModel):
    is_compliant: bool
    risk_score: int = Field(ge=1, le=10)  # 1 = Low risk (e.g. read-only/restart), 10 = High risk (destructive)
    blast_radius: str  # e.g., "Single pod replica set in 'production' namespace"
    policy_violations: List[str] = Field(default_factory=list)
    requires_human_approval: bool = True
    audit_notes: str


class RemediationPlan(BaseModel):
    action_type: ActionType
    target_service: str
    target_namespace: str = "production"
    proposed_patch: Dict[str, Any]
    rollback_command: str
    gitops_pr_url: Optional[str] = None
    approval_status: str = "PENDING_HITL"  # "PENDING_HITL", "APPROVED", "REJECTED"


class IncidentTimelineEntry(BaseModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    stage: str
    agent_name: str
    message: str


class IncidentState(BaseModel):
    incident_id: str
    service_name: str
    namespace: str = "production"
    trigger_alert: str
    created_at: str = Field(default_factory=utc_now_iso)
    phase: IncidentPhase = IncidentPhase.INITIALIZING
    timeline: List[IncidentTimelineEntry] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    selected_root_cause: Optional[Hypothesis] = None
    security_audit: Optional[SecurityAudit] = None
    remediation_plan: Optional[RemediationPlan] = None
    postmortem_markdown: Optional[str] = None

    def add_timeline(self, agent_name: str, stage: str, message: str):
        self.timeline.append(
            IncidentTimelineEntry(agent_name=agent_name, stage=stage, message=message)
        )
