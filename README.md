# 🛡️ AegisOps — Autonomous Agentic SRE & Self-Healing Platform Control Plane

[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Tracing%20%7C%20Metrics%20%7C%20Logs-F5A800?logo=opentelemetry&logoColor=white)](https://opentelemetry.io/)
[![Model Context Protocol](https://img.shields.io/badge/Protocol-MCP-black)](https://modelcontextprotocol.io/)
[![Kyverno](https://img.shields.io/badge/Security-Kyverno-blue?logo=kyverno&logoColor=white)](https://kyverno.io/)
[![Falco](https://img.shields.io/badge/Runtime-Falco-00AEC7?logo=falco&logoColor=white)](https://falco.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

**AegisOps** is an enterprise-grade autonomous SRE and Internal Developer Platform (IDP) control plane. When anomalies, SLO error budget burns, or Kubernetes failures occur, an ensemble of **GenAI Agents** queries cluster state and telemetry via **Model Context Protocol (MCP)** servers, deduces the technical root cause, evaluates security blast radius, formulates a validated **GitOps Pull Request**, and safely reconciles the cluster with **Human-in-the-Loop (HITL)** approvals before auto-generating a **Google SRE standard blameless postmortem**.

---

## 🏛️ System Architecture

```mermaid
graph TD
    subgraph Platform_Layer [Platform Engineering IDP & HITL Portal]
        UI[IDP Web Dashboard - Port 8005]
        HITL[Human-In-The-Loop Approval Gate]
        PM[Blameless Postmortem Archive]
    end

    subgraph Agent_Swarm [GenAI Multi-Agent Swarm]
        Triage[1. Triage & RCA Agent]
        Security[2. Security & Guardrail Agent]
        Remediation[3. Remediation & GitOps Agent]
        Scribe[4. Postmortem Scribe Agent]
    end

    subgraph MCP_Layer [Model Context Protocol Servers]
        K8sMCP[k8s-mcp: Pod Health, Crashed Logs, Events]
        OtelMCP[otel-mcp: PromQL Burn Rates, Traces, LogQL]
        GitOpsMCP[gitops-mcp: ArgoCD Sync, Git Diffs, PRs]
    end

    subgraph K8s_Infrastructure [Kubernetes Cluster]
        Operator[AegisOps Operator & CRDs]
        Observability[Prometheus, Loki & Tempo Stack]
        Kyverno[Kyverno Policy Engine]
        Falco[Falco eBPF Threat DaemonSet]
        Apps[Production Microservices: payment, order]
    end

    Observability -- SLO Burn Alert --> Operator
    Falco -- Runtime Breach Webhook --> Operator
    Operator --> Triage
    Triage <--> OtelMCP
    Triage <--> K8sMCP
    Triage <--> GitOpsMCP
    Triage --> Security
    Security <--> Kyverno
    Security --> Remediation
    Remediation --> HITL
    HITL -- Approved --> GitOpsMCP
    GitOpsMCP -- ArgoCD Sync / Rollout --> Apps
    Remediation --> Scribe
    Scribe --> PM
    UI <--> Operator
```

---

## 🚀 Step-by-Step Deployment Guide

AegisOps supports two distinct deployment workflows:
1. **Mode 1: Developer Feedback / Fast Iteration Mode** (Recommended for local Mac testing).
2. **Mode 2: Full In-Cluster Production Setup** (Complete enterprise multi-namespace setup).

---

### 💻 Mode 1: Developer Feedback Mode (Local Host + Kind Pods)

In Developer Mode, workload pods run inside the local `kind` cluster, while the SRE Control Plane & Web Portal run on your Mac host for zero-resource overhead and rapid agent iteration.

```
                  YOUR MAC HOST OS (Fast Execution)
 ┌─────────────────────────────────────────────────────────────┐
 │  • AegisOps IDP Web Server & Agents (server.py on :8005)    │
 │  • otel-mcp Zero-Overhead Telemetry Provider                │
 └──────────────────────────────┬──────────────────────────────┘
                                │ (~/.kube/config)
                                ▼
                 LOCAL KUBERNETES CLUSTER (Kind)
 ┌─────────────────────────────────────────────────────────────┐
 │  Namespace: `production`                                    │
 │  ├── payment-service pods (Real containers with OOMKills)   │
 │  └── order-service pods                                     │
 └─────────────────────────────────────────────────────────────┘
```

#### Step 1: Bootstrap the Local Cluster & Demo Pods
```bash
# 1. Create Kind cluster, apply CRDs, namespaces, RBAC, and demo apps
cd /Users/gangadharreddy/projects/ai-labs/aegisops
./scripts/setup_cluster.sh

# 2. Verify pods are running in 'production'
kubectl get pods -n production
```

#### Step 2: Start the AegisOps Control Plane Web Dashboard
```bash
# Starts web dashboard on http://localhost:8005
./scripts/run_demo.sh
```
Open **`http://localhost:8005`** in your browser.

#### Step 3: Run Chaos Scenarios & Watch Live Healing
Open a separate terminal tab:

* **Scenario A: Memory Leak & Pod OOMKill**:
  ```bash
  # 1. Port-forward the payment service
  kubectl port-forward svc/payment-service 8000:8000 -n production

  # 2. Inject memory leak until kernel OOMKill (SIGKILL exit 137)
  /Users/gangadharreddy/projects/ai-labs/.venv/bin/python chaos/trigger_oomkill.py
  ```
  *Watch the pod restart on Kubernetes (`kubectl get pods -n production`) and see the alert pop up on [http://localhost:8005](http://localhost:8005).*

* **Scenario B: Falco Runtime Security Anomaly**:
  ```bash
  /Users/gangadharreddy/projects/ai-labs/.venv/bin/python chaos/trigger_security_anomaly.py
  ```
  *See the `FalcoRuntimeThreatDetected` security incident appear with a non-root hardening patch on [http://localhost:8005](http://localhost:8005).*

---

### 🏢 Mode 2: Full In-Cluster Production Setup

In Full Production Mode, every layer runs natively inside isolated Kubernetes namespaces:
* **`production`**: Microservices under management.
* **`aegisops-system`**: AegisOps Operator and IDP Portal deployments with RBAC ServiceAccounts.
* **`observability`**: Full Prometheus, Alertmanager, Grafana, Loki, and Tempo stack.
* **`kyverno` & `falco`**: Admission policy enforcement & eBPF runtime threat detection.

```
                      ENTERPRISE KUBERNETES CLUSTER
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  Namespace: `aegisops-system`                                           │
 │  ├── aegisops-operator (Reconciles CRDs & coordinates agents)           │
 │  ├── aegisops-idp-portal (Serves Web UI on ClusterIP / Ingress :8005)   │
 │  └── aegisops-agent-sa (RBAC least-privilege ClusterRoleBinding)        │
 │                                                                         │
 │  Namespace: `observability`                                             │
 │  ├── Prometheus & Alertmanager (SLO multi-window burn rate alerts)      │
 │  ├── Grafana Loki (LogQL structured container log indexing)             │
 │  └── Grafana Tempo & OpenTelemetry Collector (TraceQL span waterfall)   │
 │                                                                         │
 │  Namespace: `kyverno` & `falco`                                         │
 │  ├── Kyverno Admission Controller & Background Scanner                  │
 │  └── Falco eBPF Driver & FalcoSidekick Webhook Dispatcher               │
 │                                                                         │
 │  Namespace: `production`                                                │
 │  └── payment-service & order-service (Restricted Pod Security)          │
 └─────────────────────────────────────────────────────────────────────────┘
```

#### Step 1: Deploy Operator & IDP Portal into `aegisops-system`
```bash
# 1. Apply CRDs, Namespaces and RBAC
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/crds/
kubectl apply -f k8s/base/rbac.yaml

# 2. Deploy AegisOps Operator & In-Cluster Portal
kubectl apply -f k8s/operator/

# 3. Verify operator running in aegisops-system
kubectl get pods -n aegisops-system
```

#### Step 2: Deploy Production Observability Stack via Helm
```bash
# 1. Add Prometheus Community Helm Repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# 2. Install kube-prometheus-stack configured to webhook AegisOps Operator
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  -f k8s/observability/helm-observability-values.yaml

# 3. Apply AegisOps SLO Burn Rate PrometheusRules
kubectl apply -f k8s/observability/prometheus-slo-alerts.yaml

# 4. Verify observability pods
kubectl get pods -n observability
```

#### Step 3: Deploy Security Stack (Kyverno & Falco)
```bash
# One-click security deployment
./scripts/setup_security_stack.sh
```

#### Step 4: Access the In-Cluster IDP Portal
```bash
kubectl port-forward -n aegisops-system svc/aegisops-idp-portal 8005:8005
```
Open **`http://localhost:8005`** in your browser.

---

## 🔒 DevSecOps: Kyverno & Falco Setup & Rules

### 1. Kyverno Policy Engine Setup
Kyverno acts as the **Admission Controller & Guardrail Policy Gatekeeper** to ensure agent-generated patches and developer manifests comply with Pod Security Standards (Restricted).

#### Installation Commands:
```bash
# 1. Add Kyverno Helm repository
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update kyverno

# 2. Install Kyverno in the 'kyverno' namespace
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  -f k8s/security/helm-kyverno-values.yaml

# 3. Apply AegisOps Guardrail Policies
kubectl apply -f k8s/security/kyverno-policies.yaml
```

#### Policies Enforced by AegisOps ([`kyverno-policies.yaml`](file:///Users/gangadharreddy/projects/ai-labs/aegisops/k8s/security/kyverno-policies.yaml)):
1. **`require-resource-limits`**: Rejects any deployment in `production` that lacks explicit CPU and memory requests/limits (preventing unconstrained memory leaks).
2. **`disallow-root-and-privileged`**: Blocks containers attempting to run as root (`UID 0`) or requesting `allowPrivilegeEscalation: true`.

#### Verification:
```bash
kubectl get clusterpolicy
kubectl describe clusterpolicy aegisops-guardrail-policies
```

---

### 2. Falco Runtime Threat Detection Setup
Falco utilizes **eBPF (Extended Berkeley Packet Filter)** kernel instrumentation to detect anomalous system calls and privilege escalation in real time.

#### Installation Commands:
```bash
# 1. Add Falcosecurity Helm repository
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm repo update falcosecurity

# 2. Install Falco with modern eBPF driver & FalcoSidekick
helm upgrade --install falco falcosecurity/falco \
  --namespace falco \
  --create-namespace \
  -f k8s/security/helm-falco-values.yaml
```

#### Falco Rules Active in AegisOps ([`falco-rules.yaml`](file:///Users/gangadharreddy/projects/ai-labs/aegisops/k8s/security/falco-rules.yaml)):
1. **Terminal Shell Spawned in Production Pod**:
   - **Trigger**: Process `bash`, `sh`, `zsh` spawned inside `production` namespace.
   - **Severity**: `CRITICAL`
2. **Sensitive Credential File Access**:
   - **Trigger**: Process attempts to read `/var/run/secrets/kubernetes.io/serviceaccount/token` or `.key`/`.pem` secrets.
   - **Severity**: `WARNING`

#### Webhook Integration with AegisOps:
FalcoSidekick is configured to automatically dispatch any `CRITICAL` or `WARNING` security alerts directly to the AegisOps IDP Control Plane endpoint (`http://aegisops-idp-portal.aegisops-system.svc.cluster.local:8005/api/incidents/trigger`), immediately spinning up the **Security & Guardrail Agent**.

---

## 🌟 The 7 Core SRE & Platform Pillars

| # | Pillar | Implementation in AegisOps | Key Technologies |
|---|---|---|---|
| **1** | **SRE Operations** | Multi-window burn rate alerts ($1\text{h}>14.4\times$), error budgets, blameless postmortems | Google SRE Workbook, PrometheusRule |
| **2** | **Kubernetes** | Custom CRDs (`SLOPolicy`, `InvestigationRun`, `RemediationPlan`), Kopf Operator | Kubebuilder / Kopf, Kubernetes Go SDK |
| **3** | **Observability** | Correlated M.E.L.T. (PromQL metrics, LogQL logs, Tempo TraceQL waterfall) | OpenTelemetry, Prometheus, Loki, Tempo |
| **4** | **GenAI Multi-Agents** | 4-agent ensemble (Triage, Security, Remediation, Scribe) with confidence scoring | Python, Pydantic, Async State Machine |
| **5** | **Model Context Protocol** | Custom MCP Servers (`k8s-mcp`, `otel-mcp`, `gitops-mcp`) | Model Context Protocol (MCP) Python SDK |
| **6** | **DevSecOps** | Kyverno baseline policies, Falco runtime anomaly detection, blast-radius index | Kyverno, Falco, Deterministic Guardrails |
| **7** | **Platform Engineering** | Self-service developer IDP dashboard, visual diff HITL approval gate, GitOps sync | FastAPI, Tailwind CSS, ArgoCD GitOps |

---

## 🧪 Automated Test Suite

Run the full unit and integration test suite:
```bash
PYTHONPATH=. /Users/gangadharreddy/projects/ai-labs/.venv/bin/python -m pytest agents/tests/ -v
```

```text
============================== test session starts ==============================
agents/tests/test_agents.py::test_guardrail_blocks_dangerous_commands PASSED [ 14%]
agents/tests/test_agents.py::test_guardrail_evaluates_blast_radius PASSED [ 28%]
agents/tests/test_agents.py::test_guardrail_rejects_privileged_escalation PASSED [ 42%]
agents/tests/test_agents.py::test_triage_agent_rca PASSED                [ 57%]
agents/tests/test_agents.py::test_remediation_and_security_flow PASSED   [ 71%]
agents/tests/test_agents.py::test_scribe_agent_generates_valid_postmortem PASSED [ 85%]
agents/tests/test_agents.py::test_full_orchestrator_lifecycle PASSED     [100%]
============================== 7 passed in 0.30s ===============================
```

---

## 📜 License
Apache 2.0 License. Built for cloud-native SRE, Kubernetes, and Agentic Platform Engineering.
