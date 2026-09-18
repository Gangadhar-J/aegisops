# ADR-004: Declarative GitOps Remediation vs. Imperative Cluster Mutation

## Status
Accepted

## Context
Traditional incident self-healing tools perform imperative mutations directly against the Kubernetes API (e.g. `kubectl patch deployment ...`, `kubectl scale ...`, `kubectl edit ...`). While fast, this pattern produces:
1. **Configuration Drift**: Cluster state deviates from the Git repository; subsequent ArgoCD or Flux synchronizations overwrite hotfixes.
2. **Audit Loss**: No code review, commit history, or attribution for production changes.
3. **Rollback Friction**: Reverting an imperative hotfix requires remembering previous YAML specs.

## Decision
AegisOps mandates declarative GitOps for all permanent remediation actions:
1. **Pull Request Automation**: The `RemediationAgent` generates a declarative YAML patch and submits a GitHub Pull Request against the designated repository branch (e.g. `hotfix/INC-001-memory-tune`).
2. **Human Review Gate**: SREs review the proposed diff directly in the AegisOps IDP Web Portal or GitHub.
3. **Reconciliation via ArgoCD**: Upon approval, the orchestrator merges/triggers ArgoCD application synchronization (`trigger_argocd_sync`), converging live cluster state with Git.
4. **Pre-Computed Rollback**: Every remediation plan stores a verified `rollback_command` (`kubectl rollout undo ...`) if the deployment exhibits regression.

## Consequences
### Positive
- Git remains the single source of truth for all Kubernetes infrastructure.
- Zero configuration drift; all changes are version-controlled with full cryptographic commit signatures.
- Standard peer review workflows integrate seamlessly with automated SRE tooling.
