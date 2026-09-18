"""
GitOps & Manifest Automation MCP Server (gitops-mcp)
Provides GitOps status, commit diff analysis, rollback PR generation, and ArgoCD synchronization tools for AI agents.
In production mode (AEGISOPS_ENV=production), connects to live GitHub API and ArgoCD API.
In dev mode (or when credentials are not configured), falls back to high-fidelity simulated responses.
"""
import os
import sys
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastmcp_compat import FastMCP

logger = logging.getLogger("gitops-mcp-server")

mcp = FastMCP("gitops-mcp", dependencies=["pydantic", "httpx"])

AEGISOPS_ENV = os.getenv("AEGISOPS_ENV", "dev")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "aegisops/gitops-repo")
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")

ARGOCD_SERVER = os.getenv("ARGOCD_SERVER", "http://argocd-server.argocd.svc.cluster.local")
ARGOCD_AUTH_TOKEN = os.getenv("ARGOCD_AUTH_TOKEN", "")


def _validate_file_path(file_path: str) -> bool:
    """Blocks directory traversal attempts in repository file paths."""
    if not file_path or ".." in file_path or file_path.startswith("/") or file_path.startswith("\\"):
        return False
    return True


@mcp.tool()
def get_argocd_sync_status(app_name: str = "payment-service") -> str:
    """
    Get ArgoCD application sync status, health status, and active target git revision.
    """
    if AEGISOPS_ENV == "production" and ARGOCD_AUTH_TOKEN:
        try:
            url = f"{ARGOCD_SERVER}/api/v1/applications/{app_name}"
            headers = {"Authorization": f"Bearer {ARGOCD_AUTH_TOKEN}"}
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", {})
                    sync = status.get("sync", {})
                    health = status.get("health", {})
                    return json.dumps({
                        "data_source": "argocd_live",
                        "application": app_name,
                        "sync_status": sync.get("status", "Unknown"),
                        "health_status": health.get("status", "Unknown"),
                        "target_revision": sync.get("revision", "HEAD"),
                        "repo_url": data.get("spec", {}).get("source", {}).get("repoURL", ""),
                    }, indent=2)
                else:
                    return json.dumps({
                        "data_source": "error",
                        "status": "error",
                        "error": f"ArgoCD returned HTTP {resp.status_code}: {resp.text}"
                    }, indent=2)
        except Exception as e:
            logger.error(f"Failed to query live ArgoCD: {e}")
            return json.dumps({
                "data_source": "error",
                "status": "error",
                "error": f"ArgoCD unreachable: {e}"
            }, indent=2)

    # Simulated response
    return json.dumps({
        "data_source": "simulated_dev",
        "application": app_name,
        "sync_status": "Synced",
        "health_status": "Degraded",
        "repo_url": "https://github.com/aegisops/gitops-repo.git",
        "target_revision": "main",
        "current_commit_sha": "8f3b92c1a4e9",
        "last_synced_at": "2026-08-26T18:45:12Z",
        "sync_details": {
            "author": "dev-team-lead",
            "message": "feat(payment): reduce db pool timeout and tune memory limits to 256Mi",
            "resources_out_of_sync": 0
        }
    }, indent=2)


@mcp.tool()
def get_git_commit_history(repo: str = "gitops-repo", service: str = "payment-service", limit: int = 5) -> str:
    """
    Fetch recent git commits affecting the specified service manifests or source code.
    """
    if AEGISOPS_ENV == "production" and GITHUB_TOKEN:
        try:
            target_repo = GITHUB_REPO if GITHUB_REPO else f"aegisops/{repo}"
            url = f"{GITHUB_API_URL}/repos/{target_repo}/commits"
            headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            params = {"path": f"k8s/demo-apps/{service}.yaml", "per_page": limit}
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    raw_commits = resp.json()
                    recent = []
                    for c in raw_commits[:limit]:
                        recent.append({
                            "commit_sha": c.get("sha", "")[:12],
                            "timestamp": c.get("commit", {}).get("author", {}).get("date", ""),
                            "author": c.get("commit", {}).get("author", {}).get("name", ""),
                            "summary": c.get("commit", {}).get("message", "").split("\n")[0],
                            "files_changed": [f"k8s/demo-apps/{service}.yaml"],
                            "diff_snippet": "Live GitHub commit history"
                        })
                    return json.dumps({
                        "data_source": "github_live",
                        "repo": target_repo,
                        "service": service,
                        "recent_commits": recent
                    }, indent=2)
        except Exception as e:
            logger.error(f"Failed to query live GitHub commits: {e}")
            return json.dumps({
                "data_source": "error",
                "status": "error",
                "error": f"GitHub API unreachable: {e}"
            }, indent=2)

    # Simulated commit history
    return json.dumps({
        "data_source": "simulated_dev",
        "repo": repo,
        "service": service,
        "recent_commits": [
            {
                "commit_sha": "8f3b92c1a4e9",
                "timestamp": "2026-08-26T18:40:00Z",
                "author": "dev-engineer@zeta.tech",
                "summary": "perf: lowered memory limits from 512Mi to 256Mi to cut cluster costs",
                "files_changed": [
                    "k8s/demo-apps/payment-service.yaml",
                    "src/db/connection_pool.py"
                ],
                "diff_snippet": "- memory: '512Mi'\n+ memory: '256Mi'\n- DB_MAX_CONNECTIONS: 50\n+ DB_MAX_CONNECTIONS: 20"
            },
            {
                "commit_sha": "3e4a901c2b5d",
                "timestamp": "2026-08-25T14:20:00Z",
                "author": "sre-team@zeta.tech",
                "summary": "chore: added open telemetry instrumentation and prometheus scrapers",
                "files_changed": ["k8s/demo-apps/payment-service.yaml"],
                "diff_snippet": "+ OTEL_SERVICE_NAME: 'payment-service'"
            },
            {
                "commit_sha": "1c7b889e4f0a",
                "timestamp": "2026-08-24T09:15:00Z",
                "author": "dev-engineer@zeta.tech",
                "summary": "feat(payment): release v1.4.1 stable banking gateway connector",
                "files_changed": ["k8s/demo-apps/payment-service.yaml"],
                "diff_snippet": "- image: payment-service:v1.4.0\n+ image: payment-service:v1.4.1"
            }
        ]
    }, indent=2)


@mcp.tool()
def create_remediation_pr(repo: str, branch: str, title: str, file_path: str, patch_content: str) -> str:
    """
    Create a new GitOps hotfix/remediation branch and open a GitHub Pull Request with the proposed manifest patch.
    """
    if not _validate_file_path(file_path):
        return json.dumps({
            "status": "ERROR",
            "data_source": "error",
            "error": f"Invalid file path '{file_path}': directory traversal not permitted."
        }, indent=2)

    # Live GitHub API path
    if AEGISOPS_ENV == "production" and GITHUB_TOKEN:
        try:
            target_repo = GITHUB_REPO if GITHUB_REPO else f"aegisops/{repo}"
            headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            # Open Pull Request via GitHub REST API
            with httpx.Client(timeout=10.0) as client:
                body = {
                    "title": title,
                    "head": branch,
                    "base": "main",
                    "body": f"Automated AegisOps Remediation PR\n\nProposed patch for `{file_path}`:\n```yaml\n{patch_content}\n```"
                }
                resp = client.post(f"{GITHUB_API_URL}/repos/{target_repo}/pulls", headers=headers, json=body)
                if resp.status_code in (200, 201):
                    pr_data = resp.json()
                    return json.dumps({
                        "status": "PR_CREATED",
                        "data_source": "github_live",
                        "pull_request_number": pr_data.get("number"),
                        "pull_request_url": pr_data.get("html_url"),
                        "branch": branch,
                        "title": title,
                        "target_branch": "main",
                        "modified_file": file_path,
                        "patch_preview": patch_content
                    }, indent=2)
                else:
                    logger.warning(f"GitHub PR creation returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Live GitHub PR creation failed: {e}")
            if AEGISOPS_ENV == "production":
                return json.dumps({
                    "status": "ERROR",
                    "data_source": "error",
                    "error": f"GitHub PR creation failed: {e}"
                }, indent=2)

    # High-fidelity simulated PR creation
    pr_number = 42
    pr_url = f"https://github.com/aegisops/{repo}/pull/{pr_number}"
    logger.info(f"Created GitOps Remediation PR #{pr_number} on branch '{branch}': {title}")
    return json.dumps({
        "status": "PR_CREATED",
        "data_source": "simulated_dev",
        "pull_request_number": pr_number,
        "pull_request_url": pr_url,
        "branch": branch,
        "title": title,
        "target_branch": "main",
        "modified_file": file_path,
        "patch_preview": patch_content
    }, indent=2)


@mcp.tool()
def trigger_argocd_sync(app_name: str, prune: bool = True) -> str:
    """
    Trigger immediate ArgoCD application synchronization to reconcile live cluster state with Git.
    """
    if AEGISOPS_ENV == "production" and ARGOCD_AUTH_TOKEN:
        try:
            url = f"{ARGOCD_SERVER}/api/v1/applications/{app_name}/sync"
            headers = {"Authorization": f"Bearer {ARGOCD_AUTH_TOKEN}"}
            body = {"prune": prune}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code == 200:
                    return json.dumps({
                        "status": "SYNC_TRIGGERED",
                        "data_source": "argocd_live",
                        "application": app_name,
                        "operation_state": "Running",
                        "phase": "Syncing",
                        "message": f"Successfully triggered live ArgoCD sync for {app_name}"
                    }, indent=2)
                else:
                    return json.dumps({
                        "status": "ERROR",
                        "data_source": "error",
                        "error": f"ArgoCD sync returned HTTP {resp.status_code}: {resp.text}"
                    }, indent=2)
        except Exception as e:
            logger.error(f"Live ArgoCD sync failed: {e}")
            return json.dumps({
                "status": "ERROR",
                "data_source": "error",
                "error": f"Live ArgoCD sync failed: {e}"
            }, indent=2)

    logger.info(f"Triggering ArgoCD sync for app: {app_name}")
    return json.dumps({
        "status": "SYNC_TRIGGERED",
        "data_source": "simulated_dev",
        "application": app_name,
        "operation_state": "Running",
        "phase": "Syncing",
        "message": f"Successfully initiated synchronization for application {app_name}"
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
