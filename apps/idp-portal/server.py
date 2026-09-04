"""
AegisOps Internal Developer Platform (IDP) & SRE Control Plane Portal
Provides real-time SLO monitoring, live multi-agent incident timelines, HITL remediation approval gates, and postmortems.

Production hardening applied:
- File-persisted incident store (JSON) with asyncio.Lock for concurrent safety
- API key authentication via X-AegisOps-Token header (set AEGISOPS_API_KEY env var)
- Live SLO data sourced from otel-mcp (with simulated fallback in dev)
- Relative path import (no hardcoded /Users/... paths)
"""
import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Security, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

# Portable relative path — works on any machine and in containers
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from agents.orchestrator import AegisOpsOrchestrator
from agents.core.state import IncidentState, IncidentPhase
from agents.core.mcp_client import MCPToolClient

app = FastAPI(title="AegisOps IDP Portal", version="1.0.0")
orchestrator = AegisOpsOrchestrator()
mcp_client = MCPToolClient()

# ---------------------------------------------------------
# Persistence: File-backed JSON store with asyncio.Lock
# Survives process restarts. In production replace with Redis.
# ---------------------------------------------------------
DATA_DIR = Path(os.getenv("AEGISOPS_DATA_DIR", "/tmp/aegisops-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
INCIDENTS_FILE = DATA_DIR / "incidents.json"
_incidents_lock = asyncio.Lock()


def _load_incidents() -> Dict[str, Any]:
    if INCIDENTS_FILE.exists():
        try:
            return json.loads(INCIDENTS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_incidents(db: Dict[str, Any]) -> None:
    INCIDENTS_FILE.write_text(json.dumps(db, indent=2, default=str))


async def get_incidents_db() -> Dict[str, Any]:
    async with _incidents_lock:
        return _load_incidents()


async def write_incident(incident_id: str, incident: IncidentState) -> None:
    async with _incidents_lock:
        db = _load_incidents()
        db[incident_id] = json.loads(incident.model_dump_json())
        _save_incidents(db)


async def get_incident_by_id(incident_id: str) -> Optional[Dict[str, Any]]:
    async with _incidents_lock:
        db = _load_incidents()
        return db.get(incident_id)


# ---------------------------------------------------------
# API Key Authentication
# Set AEGISOPS_API_KEY env var to enable. If not set, auth
# is disabled (dev mode only — warn on startup).
# ---------------------------------------------------------
AEGISOPS_API_KEY = os.getenv("AEGISOPS_API_KEY", "")
AEGISOPS_ENV = os.getenv("AEGISOPS_ENV", "dev")

api_key_header = APIKeyHeader(name="X-AegisOps-Token", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    if not AEGISOPS_API_KEY:
        if AEGISOPS_ENV == "production":
            raise HTTPException(
                status_code=500,
                detail="AEGISOPS_API_KEY must be set in production mode"
            )
        return "dev-anonymous"  # Dev mode: no key required
    if api_key != AEGISOPS_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-AegisOps-Token header"
        )
    return api_key


# ---------------------------------------------------------
# Startup warning
# ---------------------------------------------------------
@app.on_event("startup")
async def startup_checks():
    if not AEGISOPS_API_KEY and AEGISOPS_ENV != "dev":
        import logging
        logging.getLogger("aegisops-idp-portal").warning(
            "⚠️  AEGISOPS_API_KEY is not set. API authentication is DISABLED. "
            "Set this env var from a Kubernetes Secret before production deployment."
        )
    # Pre-create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------
class TriggerChaosRequest(BaseModel):
    scenario: str = "memory_leak_oom"  # "memory_leak_oom" | "security_threat"
    service: str = "payment-service"


class ApprovalRequest(BaseModel):
    approver: str
    comment: Optional[str] = "Approved after reviewing telemetry and guardrails."


# ---------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "aegisops-idp-portal",
        "env": AEGISOPS_ENV,
        "auth_enabled": bool(AEGISOPS_API_KEY),
        "data_dir": str(DATA_DIR)
    }


# ---------------------------------------------------------
# Protected Endpoints
# ---------------------------------------------------------
@app.get("/api/slos", dependencies=[Depends(verify_api_key)])
async def get_slos():
    """
    Returns live SLO error budget status across services.
    Calls otel-mcp for real data; falls back to static values if unavailable.
    """
    services = [
        {"name": "payment-service", "tier": "Tier-1 (Critical)", "slo_target": 99.9},
        {"name": "order-service", "tier": "Tier-1 (Critical)", "slo_target": 99.9},
        {"name": "catalog-service", "tier": "Tier-2 (Standard)", "slo_target": 99.5},
    ]
    result = []
    db = await get_incidents_db()
    open_incidents_count = len([v for v in db.values() if v.get("phase") not in ("COMPLETED", "FAILED")])

    for svc in services:
        try:
            from agents.core.mcp_client import MCPToolCallError
            slo_data = mcp_client.call_tool("otel-mcp", "query_slo_burn_rate", {"service_name": svc["name"]})
            result.append({
                "service": svc["name"],
                "tier": svc["tier"],
                "slo_target": svc["slo_target"],
                "current_availability_1h": slo_data.get("current_availability_1h", "N/A"),
                "error_budget_remaining_pct": slo_data.get("total_error_budget_remaining_pct", 100),
                "burn_rate_1h": slo_data.get("burn_rate_1h", 0),
                "burn_rate_6h": slo_data.get("burn_rate_6h", 0),
                "status": slo_data.get("status", "HEALTHY"),
                "p99_latency_ms": slo_data.get("p99_latency_ms", 0),
                "open_incidents": open_incidents_count if svc["name"] == "payment-service" else 0,
                "data_source": slo_data.get("data_source", "unknown")
            })
        except Exception:
            # Hard fallback if MCP is unavailable
            result.append({
                "service": svc["name"],
                "tier": svc["tier"],
                "slo_target": svc["slo_target"],
                "status": "UNKNOWN",
                "error_budget_remaining_pct": 100,
                "burn_rate_1h": 0,
                "burn_rate_6h": 0,
                "open_incidents": 0,
                "data_source": "unavailable"
            })
    return result


@app.get("/api/incidents", dependencies=[Depends(verify_api_key)])
async def list_incidents():
    db = await get_incidents_db()
    return list(db.values())


@app.get("/api/incidents/{incident_id}", dependencies=[Depends(verify_api_key)])
async def get_incident(incident_id: str):
    inc = await get_incident_by_id(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return inc


@app.post("/api/incidents/trigger", dependencies=[Depends(verify_api_key)])
async def trigger_investigation(req: TriggerChaosRequest):
    """Triggers autonomous multi-agent triage loop."""
    if req.scenario == "security_threat":
        alert_name = "FalcoRuntimeThreatDetected"
    else:
        alert_name = "PaymentServiceErrorBudgetFastBurn"

    incident = await orchestrator.create_incident(
        service_name=req.service,
        namespace="production",
        trigger_alert=alert_name
    )
    await write_incident(incident.incident_id, incident)

    # Run Autonomous Investigation (concurrent-safe: each incident has its own object)
    incident = await orchestrator.run_investigation(incident)
    await write_incident(incident.incident_id, incident)

    return json.loads(incident.model_dump_json())


@app.post("/api/incidents/{incident_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_remediation(incident_id: str, approval: ApprovalRequest):
    """Executes the approved remediation plan and generates postmortem."""
    inc_dict = await get_incident_by_id(incident_id)
    if inc_dict is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident = IncidentState(**inc_dict)
    if incident.phase != IncidentPhase.WAITING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Incident not in WAITING_APPROVAL phase (current: {incident.phase})"
        )

    resolved_incident = await orchestrator.approve_and_resolve(incident, approver=approval.approver)
    await write_incident(incident_id, resolved_incident)
    return json.loads(resolved_incident.model_dump_json())


@app.get("/", response_class=HTMLResponse)
def index_portal():
    return """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AegisOps — Autonomous SRE & Platform Control Plane</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        brand: { 50: '#eef2ff', 500: '#6366f1', 600: '#4f46e5', 700: '#4338ca', 900: '#312e81' },
                        surface: { 800: '#1e293b', 900: '#0f172a', 950: '#020617' }
                    }
                }
            }
        }
    </script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-surface-950 text-slate-100 min-h-screen font-sans antialiased">
    <!-- Navbar -->
    <header class="border-b border-slate-800 bg-surface-900/80 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-cyan-500 flex items-center justify-center text-white font-bold text-xl shadow-lg shadow-brand-500/20">
                    <i class="fa-solid fa-shield-halved"></i>
                </div>
                <div>
                    <h1 class="text-lg font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">AegisOps</h1>
                    <p class="text-xs text-slate-400">Autonomous SRE & Self-Healing Control Plane</p>
                </div>
            </div>
            <div class="flex items-center space-x-3">
                <span id="env-badge" class="px-2 py-0.5 rounded text-xs font-mono font-semibold bg-slate-800 text-slate-400">ENV: dev</span>
                <button onclick="triggerIncident('memory_leak_oom')" class="px-3 py-1.5 rounded-lg bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-500/30 text-xs font-semibold transition flex items-center shadow-sm">
                    <i class="fa-solid fa-bolt mr-1.5"></i> Simulate OOMKill
                </button>
                <button onclick="triggerIncident('security_threat')" class="px-3 py-1.5 rounded-lg bg-amber-600/20 hover:bg-amber-600/30 text-amber-400 border border-amber-500/30 text-xs font-semibold transition flex items-center shadow-sm">
                    <i class="fa-solid fa-user-ninja mr-1.5"></i> Simulate Falco Threat
                </button>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <!-- Live SLO Overview Section -->
        <div>
            <h2 class="text-xl font-semibold text-white mb-4 flex items-center">
                <i class="fa-solid fa-chart-line text-brand-500 mr-2.5"></i> Service Level Objectives (SLOs) & Error Budget Burn
            </h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-5" id="slo-container"></div>
        </div>

        <!-- Multi-Agent Active Incidents & HITL Section -->
        <div>
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-semibold text-white flex items-center">
                    <i class="fa-solid fa-robot text-cyan-400 mr-2.5"></i> Active Incident Swarm & HITL Approval Queue
                </h2>
                <button onclick="loadIncidents()" class="text-xs text-slate-400 hover:text-slate-200 transition">
                    <i class="fa-solid fa-rotate-right mr-1"></i> Refresh
                </button>
            </div>
            <div id="incident-container" class="space-y-4"></div>
        </div>
    </main>

    <!-- HITL Remediation Modal -->
    <div id="hitl-modal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center hidden p-4">
        <div class="bg-surface-900 border border-slate-700 rounded-2xl max-w-2xl w-full shadow-2xl overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-800/40">
                <h3 class="font-bold text-lg text-white flex items-center">
                    <i class="fa-solid fa-user-shield text-amber-400 mr-2"></i> Authorize Remediation Plan
                </h3>
                <button onclick="closeModal()" class="text-slate-400 hover:text-white">&times;</button>
            </div>
            <div class="p-6 space-y-4">
                <div id="modal-guardrail-note" class="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4 text-sm text-amber-300"></div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Proposed GitOps Patch</label>
                    <pre id="modal-patch-code" class="bg-slate-950 p-4 rounded-xl text-xs font-mono text-emerald-400 overflow-x-auto border border-slate-800"></pre>
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Safety Rollback Command</label>
                    <code id="modal-rollback-cmd" class="block bg-slate-950 p-3 rounded-xl text-xs font-mono text-cyan-300 border border-slate-800"></code>
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Approver Name</label>
                    <input id="approver-input" type="text" placeholder="your-name.sre" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand-500" />
                </div>
            </div>
            <div class="px-6 py-4 border-t border-slate-800 bg-slate-950/60 flex justify-end space-x-3">
                <button onclick="closeModal()" class="px-4 py-2 rounded-xl text-sm font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition">Cancel</button>
                <button onclick="submitApproval()" class="px-5 py-2 rounded-xl text-sm font-medium bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/30 transition flex items-center">
                    <i class="fa-solid fa-check mr-2"></i> Approve & Reconcile (ArgoCD)
                </button>
            </div>
        </div>
    </div>

    <!-- Postmortem Modal -->
    <div id="postmortem-modal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center hidden p-4">
        <div class="bg-surface-900 border border-slate-700 rounded-2xl max-w-4xl w-full shadow-2xl max-h-[85vh] flex flex-col">
            <div class="px-6 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-800/40">
                <h3 class="font-bold text-lg text-white flex items-center">
                    <i class="fa-solid fa-file-lines text-cyan-400 mr-2"></i> Blameless Incident Postmortem
                </h3>
                <button onclick="closePostmortemModal()" class="text-slate-400 hover:text-white">&times;</button>
            </div>
            <div class="p-6 overflow-y-auto prose prose-invert max-w-none text-slate-300 space-y-4" id="postmortem-content"></div>
        </div>
    </div>

    <script>
        let currentIncidentId = null;

        // Check health endpoint to display env badge
        fetch('/health').then(r => r.json()).then(h => {
            const badge = document.getElementById('env-badge');
            badge.textContent = `ENV: ${h.env || 'dev'}`;
            badge.className = `px-2 py-0.5 rounded text-xs font-mono font-semibold ${
                h.env === 'production' ? 'bg-emerald-900 text-emerald-300' : 'bg-slate-800 text-slate-400'
            }`;
        }).catch(() => {});

        async function loadSLOs() {
            try {
                const res = await fetch('/api/slos');
                if (!res.ok) return;
                const slos = await res.json();
                const container = document.getElementById('slo-container');
                container.innerHTML = slos.map(slo => {
                    const isCritical = slo.status === 'CRITICAL_BURNING';
                    const isWarning = slo.status === 'WARNING';
                    const badgeColor = isCritical ? 'bg-red-500/20 text-red-400 border-red-500/30' : isWarning ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
                    const dataSourceTag = slo.data_source === 'simulated_dev' ? '<span class="text-slate-600 text-[10px]"> (sim)</span>' : '';
                    return `
                        <div class="bg-surface-900 border ${isCritical ? 'border-red-500/40' : 'border-slate-800'} rounded-2xl p-5 shadow-lg relative overflow-hidden">
                            ${isCritical ? '<div class="absolute top-0 left-0 right-0 h-1 bg-red-500 animate-pulse"></div>' : ''}
                            <div class="flex justify-between items-start mb-3">
                                <div>
                                    <h3 class="font-semibold text-white">${slo.service}${dataSourceTag}</h3>
                                    <p class="text-xs text-slate-400">${slo.tier}</p>
                                </div>
                                <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold border ${badgeColor}">${slo.status}</span>
                            </div>
                            <div class="space-y-3">
                                <div>
                                    <div class="flex justify-between text-xs mb-1">
                                        <span class="text-slate-400">Error Budget Remaining</span>
                                        <span class="font-bold ${slo.error_budget_remaining_pct < 70 ? 'text-red-400' : 'text-emerald-400'}">${slo.error_budget_remaining_pct}%</span>
                                    </div>
                                    <div class="w-full bg-slate-800 rounded-full h-2">
                                        <div class="h-2 rounded-full ${slo.error_budget_remaining_pct < 70 ? 'bg-red-500' : 'bg-emerald-500'}" style="width: ${Math.min(slo.error_budget_remaining_pct, 100)}%"></div>
                                    </div>
                                </div>
                                <div class="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-slate-800/80">
                                    <div>
                                        <span class="text-slate-500 block">1h Burn Rate</span>
                                        <span class="font-semibold ${slo.burn_rate_1h > 14.4 ? 'text-red-400 font-bold' : 'text-slate-200'}">${slo.burn_rate_1h}x</span>
                                    </div>
                                    <div>
                                        <span class="text-slate-500 block">Open Incidents</span>
                                        <span class="font-semibold ${slo.open_incidents > 0 ? 'text-amber-400' : 'text-slate-200'}">${slo.open_incidents}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (e) { console.error('SLO load error:', e); }
        }

        async function loadIncidents() {
            try {
                const res = await fetch('/api/incidents');
                if (!res.ok) return;
                const incidents = await res.json();
                const container = document.getElementById('incident-container');
                if (incidents.length === 0) {
                    container.innerHTML = `
                        <div class="bg-surface-900 border border-dashed border-slate-800 rounded-2xl p-8 text-center text-slate-500">
                            <i class="fa-solid fa-circle-check text-3xl mb-2 text-emerald-500/50"></i>
                            <p>No active incidents. Telemetry healthy and within error budget limits.</p>
                            <div class="mt-3 flex justify-center space-x-3">
                                <button onclick="triggerIncident('memory_leak_oom')" class="px-4 py-1.5 rounded-lg bg-brand-600/20 hover:bg-brand-600/30 text-brand-400 text-xs font-semibold border border-brand-500/30 transition">Simulate OOMKill</button>
                                <button onclick="triggerIncident('security_threat')" class="px-4 py-1.5 rounded-lg bg-amber-600/20 hover:bg-amber-600/30 text-amber-400 text-xs font-semibold border border-amber-500/30 transition">Simulate Falco Threat</button>
                            </div>
                        </div>
                    `;
                    return;
                }
                container.innerHTML = incidents.map(inc => {
                    const isWaiting = inc.phase === 'WAITING_APPROVAL';
                    const isCompleted = inc.phase === 'COMPLETED';
                    const isSecurity = inc.trigger_alert && (inc.trigger_alert.includes('Falco') || inc.trigger_alert.includes('Security'));
                    const alertBadge = isSecurity ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30';
                    return `
                        <div class="bg-surface-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
                            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-slate-800">
                                <div>
                                    <div class="flex items-center space-x-3">
                                        <span class="font-mono font-bold text-white text-base">${inc.incident_id}</span>
                                        <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold ${isWaiting ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : isCompleted ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-brand-500/20 text-brand-300'}">${inc.phase}</span>
                                        <span class="px-2 py-0.5 rounded text-xs font-mono font-semibold ${alertBadge}">${inc.trigger_alert}</span>
                                    </div>
                                    <p class="text-xs text-slate-400 mt-1">Service: <strong class="text-slate-200">${inc.service_name}</strong> (${inc.namespace})</p>
                                </div>
                                <div class="flex items-center space-x-2">
                                    ${isWaiting ? `
                                        <button onclick="openApprovalModal('${inc.incident_id}')" class="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs shadow-lg shadow-amber-500/20 transition flex items-center">
                                            <i class="fa-solid fa-signature mr-1.5"></i> Review & Approve Remediation
                                        </button>
                                    ` : ''}
                                    ${isCompleted ? `
                                        <button onclick="viewPostmortem('${inc.incident_id}')" class="px-4 py-2 rounded-xl bg-cyan-600/20 hover:bg-cyan-600/30 text-cyan-300 border border-cyan-500/30 font-semibold text-xs transition flex items-center">
                                            <i class="fa-solid fa-file-lines mr-1.5"></i> View Postmortem
                                        </button>
                                    ` : ''}
                                </div>
                            </div>
                            ${inc.selected_root_cause ? `
                                <div class="bg-slate-950 border border-slate-800/80 rounded-xl p-4 space-y-2">
                                    <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                                        <span><i class="fa-solid fa-brain text-brand-400 mr-1.5"></i> Diagnosed Root Cause</span>
                                        <span class="text-emerald-400 font-bold">Confidence: ${(inc.selected_root_cause.confidence * 100).toFixed(0)}%</span>
                                    </div>
                                    <p class="text-sm text-slate-200 font-medium">${inc.selected_root_cause.statement}</p>
                                    <div class="text-xs text-slate-400">Culprit Artifact: <code class="text-cyan-300">${inc.selected_root_cause.culprit_artifact || 'N/A'}</code></div>
                                </div>
                            ` : ''}
                            <div>
                                <h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Multi-Agent Chronology</h4>
                                <div class="space-y-1.5 text-xs">
                                    ${(inc.timeline || []).map(t => `
                                        <div class="flex items-start space-x-2 text-slate-300">
                                            <span class="font-mono text-slate-500 text-[11px]">${(t.timestamp || '').substring(11, 19)}</span>
                                            <span class="px-1.5 py-0.2 rounded bg-slate-800 text-brand-300 font-medium">${t.agent_name}</span>
                                            <span class="text-slate-400">${t.message}</span>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (e) { console.error('Incidents load error:', e); }
        }

        async function triggerIncident(scenario = 'memory_leak_oom') {
            try {
                const res = await fetch('/api/incidents/trigger', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scenario: scenario, service: 'payment-service' })
                });
                if (!res.ok) {
                    const err = await res.json();
                    alert(`Error: ${err.detail || 'Unknown error'}`);
                    return;
                }
                await loadIncidents();
                await loadSLOs();
            } catch (e) { console.error('Trigger error:', e); }
        }

        async function openApprovalModal(incidentId) {
            currentIncidentId = incidentId;
            const res = await fetch(`/api/incidents/${incidentId}`);
            const inc = await res.json();
            document.getElementById('modal-patch-code').innerText = JSON.stringify(inc.remediation_plan?.proposed_patch || {}, null, 2);
            document.getElementById('modal-rollback-cmd').innerText = inc.remediation_plan?.rollback_command || 'N/A';
            document.getElementById('modal-guardrail-note').innerHTML = `
                <strong>Guardrail Assessment:</strong> Blast radius is bounded to <code class="text-amber-200">${inc.service_name}</code>.
                Risk Score: <strong>${inc.security_audit?.risk_score ?? 'N/A'}/10</strong>.
                Kyverno Baseline Compliance: <strong>${inc.security_audit?.is_compliant ? 'PASSED' : 'VIOLATION DETECTED'}</strong>.
            `;
            document.getElementById('approver-input').value = '';
            document.getElementById('hitl-modal').classList.remove('hidden');
        }

        function closeModal() { document.getElementById('hitl-modal').classList.add('hidden'); }

        async function submitApproval() {
            if (!currentIncidentId) return;
            const approver = document.getElementById('approver-input').value.trim();
            if (!approver) { alert('Please enter your name as the approver before authorizing.'); return; }
            try {
                const res = await fetch(`/api/incidents/${currentIncidentId}/approve`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ approver: approver, comment: 'Approved via IDP Portal' })
                });
                if (!res.ok) { const err = await res.json(); alert(`Approval failed: ${err.detail}`); return; }
                closeModal();
                await loadIncidents();
                await loadSLOs();
            } catch (e) { console.error('Approval error:', e); }
        }

        async function viewPostmortem(incidentId) {
            const res = await fetch(`/api/incidents/${incidentId}`);
            const inc = await res.json();
            document.getElementById('postmortem-content').innerText = inc.postmortem_markdown || 'Postmortem not yet generated.';
            document.getElementById('postmortem-modal').classList.remove('hidden');
        }

        function closePostmortemModal() { document.getElementById('postmortem-modal').classList.add('hidden'); }

        // Initialize — smart polling: every 8s when idle, 4s when incidents exist
        let pollInterval = 8000;
        async function smartPoll() {
            await loadSLOs();
            const res = await fetch('/api/incidents').then(r => r.json()).catch(() => []);
            const hasActive = Array.isArray(res) && res.some(i => i.phase === 'WAITING_APPROVAL' || i.phase === 'TRIAGING');
            pollInterval = hasActive ? 4000 : 8000;
            setTimeout(smartPoll, pollInterval);
        }

        loadSLOs();
        loadIncidents();
        smartPoll();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
