"""
Postmortem & SRE Knowledge Scribe Agent
Generates comprehensive, blameless SRE postmortems adhering to Google SRE best practices.
All content is dynamically derived from the actual incident evidence and root cause.
"""
import logging
from datetime import datetime, timezone
from agents.core.state import IncidentState, IncidentPhase

logger = logging.getLogger("aegisops-scribe-agent")

# Action items registry keyed by root cause category
ACTION_ITEMS_REGISTRY = {
    "RESOURCE_EXHAUSTION_AND_CONFIG_REGRESSION": [
        ("Add Kyverno pre-commit admission webhook enforcing minimum 512Mi memory limits on all Tier-1 services", "Platform Eng", "P1", "Prevent"),
        ("Introduce memory-gradient chaos test in CI/CD pipeline to catch regressions before production merge", "SRE Team", "P2", "Mitigate"),
        ("Tune Alertmanager memory alert window from 3m to 1m for faster OOM detection", "SRE Team", "P3", "Detect"),
    ],
    "RESOURCE_EXHAUSTION_OOM": [
        ("Add memory VPA (Vertical Pod Autoscaler) recommendations to all Tier-1 services", "Platform Eng", "P1", "Prevent"),
        ("Set up OOMKill rate alert with 1-minute evaluation window", "SRE Team", "P2", "Detect"),
        ("Profile memory usage under peak load in staging before each release", "Dev Team", "P2", "Mitigate"),
    ],
    "SECURITY_BREACH_RUNTIME_ESC": [
        ("Enforce runAsNonRoot: true and readOnlyRootFilesystem: true on all production Deployments via Kyverno", "Platform Eng", "P0", "Prevent"),
        ("Enable Falco alerting with PagerDuty webhook for CRITICAL severity rules", "SecOps", "P1", "Detect"),
        ("Rotate all Kubernetes service account tokens in affected namespace", "SecOps", "P0", "Mitigate"),
        ("Conduct post-incident security forensics and access audit", "SecOps", "P1", "Investigate"),
    ],
    "CONFIG_REGRESSION": [
        ("Add automated canary analysis to ArgoCD sync using Flagger before full rollout", "Platform Eng", "P1", "Prevent"),
        ("Add SLO burn rate gate to GitOps PR checks via GitHub Actions", "SRE Team", "P2", "Detect"),
        ("Require SRE sign-off on any change to resource limits or connection pool configuration", "Engineering Mgmt", "P2", "Process"),
    ],
    "UNKNOWN": [
        ("Add more granular distributed tracing to identify future unknown failures faster", "SRE Team", "P2", "Detect"),
        ("Schedule blameless postmortem review meeting within 48 hours", "SRE Team", "P1", "Process"),
    ],
}


class ScribeAgent:
    """Compiles incident telemetry, timeline, and mitigation details into a blameless postmortem."""

    async def generate_postmortem(self, state: IncidentState) -> IncidentState:
        logger.info(f"Generating Blameless Postmortem for incident {state.incident_id}")
        state.add_timeline("ScribeAgent", "POSTMORTEM_GENERATION", "Synthesizing timeline, root cause analysis, and preventative action items")

        rca = state.selected_root_cause
        root_cause_text = rca.statement if rca else "Root cause investigation inconclusive."
        culprit_text = rca.culprit_artifact if rca else "N/A"
        confidence_text = f"{int((rca.confidence if rca else 0) * 100)}%"
        root_cause_category = rca.root_cause_category if rca else "UNKNOWN"
        now_utc = datetime.now(timezone.utc).isoformat()

        # Determine severity from root cause category and burn rate
        severity = self._derive_severity(state, root_cause_category)

        # Build timeline markdown
        timeline_md_rows = "\n".join([
            f"| `{t.timestamp}` | **{t.agent_name}** | `{t.stage}` | {t.message} |"
            for t in state.timeline
        ])

        # Build evidence markdown
        evidence_md_items = "\n".join([
            f"- **[{e.source}] ({e.evidence_type})**: {e.summary}"
            for e in state.evidence
        ]) or "- No structured evidence collected."

        # Build technical mechanism from evidence
        tech_mechanism = self._derive_technical_mechanism(state, root_cause_category)

        # Build action items from registry
        action_rows = ""
        items = ACTION_ITEMS_REGISTRY.get(root_cause_category, ACTION_ITEMS_REGISTRY["UNKNOWN"])
        for i, (action, owner, priority, atype) in enumerate(items, 1):
            action_rows += f"| **{i}** | {action} | {owner} | {priority} | {atype} |\n"

        plan = state.remediation_plan
        audit = state.security_audit

        postmortem = f"""# 📑 Blameless Incident Postmortem: {state.incident_id}

**Target Service**: `{state.service_name}`  
**Namespace**: `{state.namespace}`  
**Incident Severity**: `{severity}`  
**Trigger Alert**: `{state.trigger_alert}`  
**Root Cause Category**: `{root_cause_category}`  
**Status**: `RESOLVED & MITIGATED`  
**Generated At**: `{now_utc}`  

---

## 🎯 Executive Summary
On `{state.created_at[:10]}`, `{state.service_name}` triggered alert `{state.trigger_alert}`. 
AegisOps autonomous multi-agent swarm intercepted the alert, correlated multi-modal telemetry via MCP tools, 
deduced the root cause with **{confidence_text} confidence**, formulated a validated GitOps remediation PR, 
and restored normal service health upon human approval.

---

## 🔍 Root Cause Analysis (RCA)
- **Primary Root Cause**: {root_cause_text}
- **Identified Culprit Artifact**: `{culprit_text}`
- **Diagnostic Confidence Score**: `{confidence_text}`
- **Root Cause Category**: `{root_cause_category}`
- **Technical Mechanism**:
{tech_mechanism}

---

## 📊 Telemetry & Evidence Artifacts
{evidence_md_items}

---

## ⏱️ Incident Chronology & Multi-Agent Timeline

| Timestamp (UTC) | Agent | Stage | Description |
|---|---|---|---|
{timeline_md_rows}

---

## 🛡️ Remediation & Verification Summary
- **Action Applied**: `{plan.action_type if plan else 'N/A'}`
- **GitOps Pull Request**: [{plan.gitops_pr_url if plan else 'N/A'}]({plan.gitops_pr_url if plan else '#'})
- **Security Audit Risk Score**: `{audit.risk_score if audit else 'N/A'}/10 ({'PASSED' if audit and audit.is_compliant else 'FAILED'})`
- **Rollback Safety Command**: `{plan.rollback_command if plan else 'N/A'}`
- **Approver**: `{plan.approval_status if plan else 'N/A'}`

---

## 📋 Preventative Action Items

| Item | Action Item | Owner | Priority | Type |
|---|---|---|---|---|
{action_rows}
---
*Report auto-generated by AegisOps Autonomous SRE Control Plane. Root cause category: {root_cause_category}.*
"""

        state.postmortem_markdown = postmortem
        state.phase = IncidentPhase.COMPLETED
        state.add_timeline("ScribeAgent", "INCIDENT_RESOLVED", "Postmortem successfully published and archived.")
        return state

    @staticmethod
    def _derive_severity(state: IncidentState, category: str) -> str:
        """Derives P-level severity from root cause category and alert name."""
        if "Falco" in state.trigger_alert or "Security" in state.trigger_alert:
            return "P0 - CRITICAL (Security Breach)"
        if "FastBurn" in state.trigger_alert or category in ("RESOURCE_EXHAUSTION_AND_CONFIG_REGRESSION", "RESOURCE_EXHAUSTION_OOM"):
            return "P1 - CRITICAL (SLO Fast-Burn)"
        if "SlowBurn" in state.trigger_alert or category == "CONFIG_REGRESSION":
            return "P2 - HIGH (SLO Slow-Burn / Config Regression)"
        return "P3 - MEDIUM (Degraded Service)"

    @staticmethod
    def _derive_technical_mechanism(state: IncidentState, category: str) -> str:
        """Builds the technical mechanism section from actual evidence."""
        lines = []
        oom_evidence = [e for e in state.evidence if e.evidence_type == "K8S_EVENT" and "OOMKilled" in e.summary]
        git_evidence = [e for e in state.evidence if e.evidence_type == "GIT_DIFF"]
        trace_evidence = [e for e in state.evidence if e.evidence_type == "TRACE"]

        if oom_evidence:
            lines.append(f"  1. Kubernetes detected OOMKilled containers: {oom_evidence[0].summary}")
        if git_evidence:
            lines.append(f"  2. GitOps correlation: {git_evidence[0].summary}")
        if trace_evidence:
            lines.append(f"  3. Distributed tracing revealed: {trace_evidence[0].summary}")
        if not lines:
            lines.append(f"  1. {state.trigger_alert} alert fired. Evidence collection incomplete — manual investigation required.")
        return "\n".join(lines)
