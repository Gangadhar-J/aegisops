"""
OpenTelemetry & Observability MCP Server (otel-mcp)
Provides standardized telemetry inspection tools: PromQL metrics, Loki logs, Tempo trace spans, and SLO burn rates.
In production mode (AEGISOPS_ENV=production), makes real API calls with retry/backoff.
In dev mode, falls back to high-fidelity simulated responses.
"""
import os
import sys
import json
import time
import logging
from typing import Dict, Any, List, Optional
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fastmcp_compat import FastMCP

logger = logging.getLogger("otel-mcp-server")

mcp = FastMCP("otel-mcp", dependencies=["httpx", "pydantic"])

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-k8s.observability.svc.cluster.local:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki.observability.svc.cluster.local:3100")
TEMPO_URL = os.getenv("TEMPO_URL", "http://tempo.observability.svc.cluster.local:3200")
AEGISOPS_ENV = os.getenv("AEGISOPS_ENV", "dev")  # "dev" | "staging" | "production"


def _http_get_with_retry(url: str, params: dict = None, timeout: float = 5.0, max_attempts: int = 3) -> Optional[dict]:
    """
    HTTP GET with exponential backoff retry (3 attempts: 1s, 2s, 4s).
    Returns parsed JSON on success, None on failure.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, params=params or {})
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
            if attempt < max_attempts:
                time.sleep(attempt * 1.0)
            else:
                if AEGISOPS_ENV == "production":
                    logger.error(f"Prometheus/Loki/Tempo API unavailable after {max_attempts} retries: {url} -> {e}")
                else:
                    logger.warning(f"Telemetry endpoint unreachable ({url}), using simulated data: {e}")
                return None
        except Exception as e:
            logger.error(f"Unexpected error querying {url}: {e}")
            return None
    return None


@mcp.tool()
def query_promql(query: str, time_range_minutes: int = 30) -> str:
    """
    Execute a PromQL metric query against Prometheus.
    Retries 3 times with exponential backoff before falling back to simulated data (dev only).
    """
    result = _http_get_with_retry(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": query}
    )
    if result is not None:
        return json.dumps(result, indent=2)

    if AEGISOPS_ENV == "production":
        return json.dumps({"status": "error", "error": "Prometheus unavailable after 3 retries"}, indent=2)

    # Dev/staging simulated fallback
    if "payment_requests_total" in query and "failure" in query:
        return json.dumps({
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {"service": "payment-service", "status": "failure"}, "value": [int(time.time()), "14.2"]}]
            }
        }, indent=2)
    elif "memory" in query or "working_set" in query:
        return json.dumps({
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {"container": "payment-service"}, "value": [int(time.time()), "268435456"]}]
            }
        }, indent=2)
    elif "latency" in query:
        return json.dumps({
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {"service": "payment-service", "quantile": "0.99"}, "value": [int(time.time()), "3.45"]}]
            }
        }, indent=2)
    return json.dumps({
        "status": "success",
        "data": {"resultType": "vector", "result": [{"metric": {"query": query}, "value": [int(time.time()), "1.0"]}]}
    }, indent=2)


@mcp.tool()
def query_slo_burn_rate(service_name: str, window: str = "1h") -> str:
    """
    Calculates the multi-window error budget burn rate and remaining 30-day budget for a service.
    In production, queries Prometheus recording rules. In dev, returns high-fidelity simulated data.
    """
    if AEGISOPS_ENV == "production":
        prom_query = f'aegisops:slo_burn_rate:1h{{service="{service_name}"}}'
        result = _http_get_with_retry(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": prom_query}
        )
        if result and result.get("status") == "success" and result["data"]["result"]:
            value = float(result["data"]["result"][0]["value"][1])
            return json.dumps({
                "service": service_name,
                "evaluation_window": window,
                "burn_rate_1h": value,
                "threshold_1h_critical": 14.4,
                "status": "CRITICAL_BURNING" if value > 14.4 else "WARNING" if value > 6.0 else "HEALTHY",
                "alert_fired": value > 14.4,
                "data_source": "prometheus_live"
            }, indent=2)
        return json.dumps({"status": "error", "error": "Prometheus SLO recording rules unavailable"}, indent=2)

    # Dev/staging simulated data
    if service_name == "payment-service":
        return json.dumps({
            "service": service_name,
            "slo_target_availability": "99.9%",
            "evaluation_window": window,
            "current_availability_1h": "94.2%",
            "burn_rate_1h": 16.8,
            "burn_rate_6h": 7.4,
            "threshold_1h_critical": 14.4,
            "error_budget_consumed_last_1h_pct": 2.35,
            "total_error_budget_remaining_pct": 68.4,
            "projected_time_to_exhaustion": "18 hours 20 minutes",
            "status": "CRITICAL_BURNING",
            "alert_fired": True,
            "data_source": "simulated_dev"
        }, indent=2)
    return json.dumps({
        "service": service_name,
        "slo_target_availability": "99.9%",
        "evaluation_window": window,
        "current_availability_1h": "99.98%",
        "burn_rate_1h": 0.2,
        "burn_rate_6h": 0.3,
        "total_error_budget_remaining_pct": 98.1,
        "status": "HEALTHY",
        "alert_fired": False,
        "data_source": "simulated_dev"
    }, indent=2)


@mcp.tool()
def query_loki_logs(logql_query: str, limit: int = 25) -> str:
    """
    Search structured application and container logs in Grafana Loki using LogQL.
    """
    result = _http_get_with_retry(
        f"{LOKI_URL}/loki/api/v1/query_range",
        params={"query": logql_query, "limit": limit}
    )
    if result is not None:
        return json.dumps(result, indent=2)

    if AEGISOPS_ENV == "production":
        return json.dumps({"status": "error", "error": "Loki unavailable after retries"}, indent=2)

    return json.dumps({
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [{
                "stream": {"service": "payment-service", "level": "ERROR", "namespace": "production"},
                "values": [
                    [str(int(time.time() * 1e9) - 60_000_000_000),
                     '{"trace_id":"a1b2c3d4e5f60718","message":"Payment gateway timeout","status_code":500}'],
                    [str(int(time.time() * 1e9) - 45_000_000_000),
                     '{"trace_id":"b2c3d4e5f6071829","message":"Database connection pool exhausted","error":"PoolTimeout"}'],
                    [str(int(time.time() * 1e9) - 20_000_000_000),
                     '{"trace_id":"c3d4e5f607182930","message":"Out of Memory: Container memory usage exceeds limit","signal":"SIGKILL"}']
                ]
            }]
        }
    }, indent=2)


@mcp.tool()
def get_trace_tree(trace_id: str) -> str:
    """
    Retrieve distributed trace spans waterfall from Grafana Tempo / OpenTelemetry Collector.
    """
    result = _http_get_with_retry(f"{TEMPO_URL}/api/traces/{trace_id}")
    if result is not None:
        return json.dumps(result, indent=2)

    if AEGISOPS_ENV == "production":
        return json.dumps({"status": "error", "error": "Tempo unavailable after retries"}, indent=2)

    return json.dumps({
        "trace_id": trace_id,
        "root_service": "order-service",
        "duration_ms": 3120.4,
        "has_errors": True,
        "data_source": "simulated_dev",
        "spans": [
            {"span_id": "span_root_001", "parent_span_id": None, "service": "order-service",
             "operation": "POST /orders", "duration_ms": 3120.4, "status": "ERROR",
             "attributes": {"http.status_code": 502, "error.message": "Downstream payment failed"}},
            {"span_id": "span_payment_002", "parent_span_id": "span_root_001", "service": "payment-service",
             "operation": "POST /process-payment", "duration_ms": 3110.1, "status": "ERROR",
             "attributes": {"http.status_code": 500, "exception.type": "HTTPException",
                            "exception.message": "Payment gateway timeout"}},
            {"span_id": "span_db_003", "parent_span_id": "span_payment_002", "service": "payment-service",
             "operation": "db_acquire_connection", "duration_ms": 3005.2, "status": "WARNING",
             "attributes": {"db.system": "postgresql", "db.pool.status": "exhausted",
                            "db.pool.active_connections": 20, "db.pool.max_connections": 20}}
        ]
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
