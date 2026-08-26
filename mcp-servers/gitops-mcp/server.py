"""
GitOps & Manifest Automation MCP Server (gitops-mcp)
Provides GitOps status, commit diff analysis, rollback PR generation, and ArgoCD synchronization tools for AI agents.
"""
import os
import sys
import json
import logging
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastmcp_compat import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gitops-mcp-server")

mcp = FastMCP("gitops-mcp", dependencies=["pydantic"])


@mcp.tool()
def get_argocd_sync_status(app_name: str = "payment-service") -> str:
    """
    Get ArgoCD application sync status, health status, and active target git revision.
    """
    return json.dumps({
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
    return json.dumps({
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
    pr_number = 42
    pr_url = f"https://github.com/aegisops/{repo}/pull/{pr_number}"
    logger.info(f"Created GitOps Remediation PR #{pr_number} on branch '{branch}': {title}")
    return json.dumps({
        "status": "PR_CREATED",
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
    logger.info(f"Triggering ArgoCD sync for app: {app_name}")
    return json.dumps({
        "status": "SYNC_TRIGGERED",
        "application": app_name,
        "operation_state": "Running",
        "phase": "Syncing",
        "message": f"Successfully initiated synchronization for application {app_name}"
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
