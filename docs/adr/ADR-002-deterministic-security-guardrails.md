# ADR-002: Deterministic Multi-Layer Security Guardrails and Blast-Radius Limiting

## Status
Accepted

## Context
When AI agents are granted access to Kubernetes clusters and Git repositories, relying on LLM system prompt instructions (e.g. "Do not delete production namespaces") is vulnerable to prompt injection, jailbreaking, and non-deterministic model behavior. In critical production banking and payment workloads, security boundaries must be absolute, non-bypassable, and mathematically verifiable.

## Decision
AegisOps establishes a dual-layer defense-in-depth security model:

1. **Pre-Execution Application Layer Guardrails (`GuardrailEngine`)**:
   - **Structured Recursive Dict Inspection**: Traverses all proposed manifest patches to verify `privileged: false`, `allowPrivilegeEscalation: false`, `runAsNonRoot: true`, and non-root UID assignment.
   - **Namespace Isolation**: Disallows automated remediation targeting control plane namespaces (`kube-system`, `kube-public`, `kube-node-lease`, `aegisops-system`).
   - **Prohibited Command Engine**: Evaluates CLI operations against 26 compiled regex patterns blocking filesystem destruction (`rm -rf /`), node deletion, cluster role edits, and credential exfiltration.
   - **Mandatory Human-in-the-Loop (HITL) Gate**: Any action targeting production with risk score $\ge 3$ strictly pauses the workflow in `WAITING_APPROVAL` until approved via IDP Portal / Slack.

2. **Cluster Admission Controller Layer (`Kyverno ClusterPolicy`)**:
   - Kernel and admission-level enforcement independent of agent process memory.
   - Validates resource requests/limits, non-root execution, dropped capabilities, and read-only root filesystems on all workloads.

## Consequences
### Positive
- Zero probability of LLM-induced privilege escalation or namespace deletion.
- Clean separation between policy definition and LLM prompt engineering.
- Compliance with PCI-DSS and SOC-2 least-privilege mandates.

### Negative
- Non-standard patches require explicit human approval and cannot be fully automated.
