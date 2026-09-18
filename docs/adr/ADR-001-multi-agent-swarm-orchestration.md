# ADR-001: Specialized Multi-Agent Swarm with Typed State Machine

## Status
Accepted

## Context
Autonomous incident response platforms must balance the flexibility of large language model (LLM) reasoning with the reliability, auditability, and predictability required in production enterprise infrastructure. Early agent implementations often rely on a single unconstrained ReAct loop attempting to handle triage, remediation planning, security verification, and documentation in an open-ended loop. This pattern suffers from:
1. State drift and hallucinated context across long-running investigations.
2. Unpredictable escalation paths and lack of verifiable phase boundaries.
3. Non-deterministic side effects where destructive commands can be executed mid-triage.

## Decision
AegisOps adopts a decoupled multi-agent swarm architecture where four specialized agents coordinate around a strongly-typed Pydantic `IncidentState`:

1. **TriageAgent**: Dedicated to telemetry extraction and root cause correlation across OpenTelemetry, Kubernetes, and GitOps logs. Transitions state from `DETECTED` to `TRIAGING` and `HYPOTHESIS_TESTING`.
2. **RemediationAgent**: Formulates declarative manifest patches with rollbacks. Opens GitOps Pull Requests. Transitions state to `REMEDIATING`.
3. **SecurityAgent / GuardrailEngine**: Evaluates patch blast radius, namespace isolation, and privilege escalation deterministically. Rejects non-compliant plans without human intervention.
4. **ScribeAgent**: Compiles timeline events, telemetry metrics, and remediation evidence into blameless markdown postmortems.

The orchestrator (`AegisOpsOrchestrator`) enforces phase transitions and acts as a state gatekeeper.

## Consequences
### Positive
- **Predictable Lifecycle**: Every incident flows through verifiable phases (`DETECTED` $\rightarrow$ `TRIAGING` $\rightarrow$ `WAITING_APPROVAL` $\rightarrow$ `REMEDIATING` $\rightarrow$ `COMPLETED` / `FAILED`).
- **Auditability**: All evidence, hypotheses, and timeline entries are serialized to an append-only state store.
- **Fail-Safe**: If any agent or tool fails, the orchestrator catches the typed error, marks the incident as `FAILED` or `DEGRADED`, and notifies human responders.

### Negative
- Inter-agent coordination requires passing and serializing the complete `IncidentState` model.
