"""
Chaos Scenario 2: Database Connection Pool Starvation & Latency Spike
"""
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chaos-db-starvation")

PAYMENT_SERVICE_URL = "http://localhost:8000"
IDP_PORTAL_URL = "http://localhost:8005"


def inject_db_starvation():
    logger.info("Configuring DB pool starvation and latency spike in payment-service...")
    with httpx.Client(base_url=PAYMENT_SERVICE_URL, timeout=5.0) as client:
        try:
            resp = client.post("/chaos/configure", json={
                "latency_spike": True,
                "latency_sec": 3.5,
                "error_cascade": True,
                "error_rate": 0.75,
                "db_starvation": True
            })
            logger.info(f"Chaos configured: {resp.json()}")
        except Exception as e:
            logger.error(f"Failed to configure chaos: {e}")

    # Dispatch Alert to AegisOps IDP Control Plane
    logger.info("🚨 Dispatching Latency Spike & DB Pool Alert to AegisOps Control Plane...")
    try:
        with httpx.Client(timeout=5.0) as portal_client:
            resp = portal_client.post(f"{IDP_PORTAL_URL}/api/incidents/trigger", json={
                "scenario": "memory_leak_oom",
                "service": "payment-service"
            })
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"✅ Incident submitted to AegisOps Control Plane! Incident ID: {data.get('incident_id')}")
                logger.info(f"👉 Check live triage on IDP Web UI: {IDP_PORTAL_URL}")
    except Exception as e:
        logger.info(f"Note: IDP portal at {IDP_PORTAL_URL} not reachable ({e}).")


if __name__ == "__main__":
    inject_db_starvation()
