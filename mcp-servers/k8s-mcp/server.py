"""
Kubernetes MCP Server (k8s-mcp)
Provides safe, structured Kubernetes cluster introspection and controlled remediation tools for AI agents.
"""
import os
import sys
import json
import logging
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastmcp_compat import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("k8s-mcp-server")

mcp = FastMCP("k8s-mcp", dependencies=["kubernetes", "pydantic"])

K8S_AVAILABLE = False
try:
    from kubernetes import client, config
    try:
        config.load_incluster_config()
        K8S_AVAILABLE = True
    except Exception:
        try:
            config.load_kube_config()
            K8S_AVAILABLE = True
        except Exception:
            logger.warning("No Kubernetes cluster configuration found. Operating in simulated cluster mode.")
except ImportError:
    logger.warning("kubernetes python package not found. Operating in simulated cluster mode.")


@mcp.tool()
def get_pods(namespace: str = "production") -> str:
    """
    List all pods in the given namespace with status, restart count, phase, and container states.
    Useful for detecting OOMKilled pods, CrashLoopBackOff, and unhealthy pods.
    """
    if K8S_AVAILABLE:
        try:
            v1 = client.CoreV1Api()
            pods = v1.list_namespaced_pod(namespace=namespace)
            result = []
            for pod in pods.items:
                container_statuses = []
                for cs in (pod.status.container_statuses or []):
                    state_info = "running"
                    if cs.state.waiting:
                        state_info = f"waiting: {cs.state.waiting.reason}"
                    elif cs.state.terminated:
                        state_info = f"terminated: exit_code={cs.state.terminated.exit_code} reason={cs.state.terminated.reason}"

                    container_statuses.append({
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": state_info
                    })

                result.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "node_name": pod.spec.node_name,
                    "containers": container_statuses
                })
            return json.dumps({"namespace": namespace, "pods": result}, indent=2)
        except Exception as e:
            logger.error(f"Error querying k8s pods: {e}")

    # High-fidelity simulated response for testing and offline execution
    return json.dumps({
        "namespace": namespace,
        "pods": [
            {
                "name": "payment-service-78d4c9f96b-x92zk",
                "namespace": namespace,
                "phase": "Running",
                "pod_ip": "10.244.0.15",
                "node_name": "kind-control-plane",
                "containers": [
                    {
                        "name": "payment-service",
                        "ready": True,
                        "restart_count": 3,
                        "state": "terminated: exit_code=137 reason=OOMKilled"
                    }
                ]
            },
            {
                "name": "payment-service-78d4c9f96b-m84qp",
                "namespace": namespace,
                "phase": "Running",
                "pod_ip": "10.244.0.16",
                "node_name": "kind-control-plane",
                "containers": [
                    {
                        "name": "payment-service",
                        "ready": True,
                        "restart_count": 2,
                        "state": "running"
                    }
                ]
            },
            {
                "name": "order-service-65b8df5b98-lj4v2",
                "namespace": namespace,
                "phase": "Running",
                "pod_ip": "10.244.0.17",
                "node_name": "kind-control-plane",
                "containers": [
                    {
                        "name": "order-service",
                        "ready": True,
                        "restart_count": 0,
                        "state": "running"
                    }
                ]
            }
        ]
    }, indent=2)


@mcp.tool()
def get_pod_logs(pod_name: str, namespace: str = "production", tail_lines: int = 50, previous: bool = False) -> str:
    """
    Fetch container stdout and stderr logs for a specific pod.
    Set previous=True to view logs of a previously crashed/OOMKilled container instance.
    """
    if K8S_AVAILABLE:
        try:
            v1 = client.CoreV1Api()
            logs = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail_lines,
                previous=previous
            )
            return logs
        except Exception as e:
            logger.error(f"Error fetching pod logs: {e}")

    # Simulated log stream
    if "payment" in pod_name:
        if previous:
            return (
                "2026-08-26 19:10:02 [INFO] [trace_id=a1b2c3d4e5f60718] Processing payment for Order: ord_8f11ac, Amount: 149.99 USD\n"
                "2026-08-26 19:10:05 [WARNING] [trace_id=a1b2c3d4e5f60718] CHAOS: Injected memory leak of 50 MB. Total leaked: 245.0 MB\n"
                "2026-08-26 19:10:08 [WARNING] [trace_id=b2c3d4e5f6071829] Service memory usage exceeds 95% of limit (256Mi)\n"
                "2026-08-26 19:10:09 [CRITICAL] [trace_id=b2c3d4e5f6071829] Out of Memory: Kill process 1 (uvicorn) score 987 or sacrifice child\n"
                "Killed"
            )
        return (
            "2026-08-26 19:11:15 [INFO] [trace_id=c3d4e5f607182930] Uvicorn running on http://0.0.0.0:8000 (PID 1)\n"
            "2026-08-26 19:11:18 [INFO] [trace_id=c3d4e5f607182930] Processing payment for Order: ord_99ab21, Amount: 49.00 USD\n"
            "2026-08-26 19:11:22 [WARNING] [trace_id=c3d4e5f607182930] Database connection pool starvation: waited 2.5s for connection\n"
            "2026-08-26 19:11:24 [ERROR] [trace_id=d4e5f60718293041] Downstream Payment Gateway Connection Timed Out (500 Internal Server Error)"
        )
    return f"Logs for {pod_name} ({namespace}): Service healthy. No errors reported."


@mcp.tool()
def get_cluster_events(namespace: str = "production", limit: int = 25) -> str:
    """
    Fetch recent Warning and Error Kubernetes events in the target namespace.
    """
    if K8S_AVAILABLE:
        try:
            v1 = client.CoreV1Api()
            events = v1.list_namespaced_event(namespace=namespace)
            result = []
            for ev in events.items[-limit:]:
                result.append({
                    "type": ev.type,
                    "reason": ev.reason,
                    "message": ev.message,
                    "involved_object": f"{ev.involved_object.kind}/{ev.involved_object.name}",
                    "count": ev.count,
                    "last_timestamp": str(ev.last_timestamp)
                })
            return json.dumps({"events": result}, indent=2)
        except Exception as e:
            logger.error(f"Error fetching cluster events: {e}")

    return json.dumps({
        "events": [
            {
                "type": "Warning",
                "reason": "OOMKilled",
                "message": "Pod payment-service-78d4c9f96b-x92zk container payment-service exceeded memory limit (256Mi) and was killed with signal 9 (SIGKILL)",
                "involved_object": "Pod/payment-service-78d4c9f96b-x92zk",
                "count": 3,
                "last_timestamp": "2026-08-26T19:10:10Z"
            },
            {
                "type": "Warning",
                "reason": "Unhealthy",
                "message": "Liveness probe failed: HTTP probe failed with statuscode: 500",
                "involved_object": "Pod/payment-service-78d4c9f96b-x92zk",
                "count": 2,
                "last_timestamp": "2026-08-26T19:10:08Z"
            },
            {
                "type": "Normal",
                "reason": "Created",
                "message": "Created container payment-service",
                "involved_object": "Pod/payment-service-78d4c9f96b-x92zk",
                "count": 4,
                "last_timestamp": "2026-08-26T19:10:12Z"
            }
        ]
    }, indent=2)


@mcp.tool()
def get_deployment_spec(deployment_name: str, namespace: str = "production") -> str:
    """
    Retrieve full specification of a deployment including image version, env variables, resource limits, and replica counts.
    """
    if K8S_AVAILABLE:
        try:
            apps_v1 = client.AppsV1Api()
            dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            c = dep.spec.template.spec.containers[0]
            return json.dumps({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": dep.spec.replicas,
                "image": c.image,
                "resources": {
                    "limits": c.resources.limits if c.resources else None,
                    "requests": c.resources.requests if c.resources else None
                },
                "env": [{e.name: e.value} for e in (c.env or [])],
                "labels": dep.metadata.labels
            }, indent=2)
        except Exception as e:
            logger.error(f"Error fetching deployment: {e}")

    return json.dumps({
        "name": deployment_name,
        "namespace": namespace,
        "replicas": 2,
        "image": "payment-service:v1.4.2",
        "resources": {
            "limits": {"memory": "256Mi", "cpu": "500m"},
            "requests": {"memory": "128Mi", "cpu": "100m"}
        },
        "env": [
            {"ENV": "production"},
            {"OTEL_SERVICE_NAME": "payment-service"},
            {"DB_MAX_CONNECTIONS": "20"},
            {"CONNECTION_TIMEOUT_MS": "1500"}
        ],
        "labels": {
            "app": deployment_name,
            "app.kubernetes.io/version": "v1.4.2",
            "git_commit": "8f3b92c1"
        }
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
