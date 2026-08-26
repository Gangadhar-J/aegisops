"""
Chaos Scenario 1: Progressive Memory Leak -> OOMKill Container Termination
Injects memory leak into live pod and submits alert webhook to AegisOps Control Plane.
"""
import time
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chaos-oomkill")

PAYMENT_SERVICE_URL = "http://localhost:8000"
IDP_PORTAL_URL = "http://localhost:8005"


def inject_memory_leak(iterations: int = 5, mb_per_step: int = 60):
    logger.info("Injecting progressive memory leak chaos into payment-service...")
    oom_occurred = False
    with httpx.Client(base_url=PAYMENT_SERVICE_URL, timeout=5.0) as client:
        for i in range(iterations):
            try:
                resp = client.post("/chaos/leak-memory", params={"mb_to_leak": mb_per_step})
                logger.info(f"Step {i+1}/{iterations}: Injected {mb_per_step}MB. Response: {resp.json()}")
                time.sleep(1.0)
            except Exception as e:
                logger.warning(f"Connection closed at step {i+1} (Pod terminated by Linux kernel OOMKiller): {e}")
                oom_occurred = True
                break

    # Dispatch Alertmanager Webhook to AegisOps IDP Control Plane
    logger.info("🚨 Dispatching Prometheus SLO Burn Rate & OOMKill Alert to AegisOps Control Plane...")
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
    inject_memory_leak()
