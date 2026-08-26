"""
Chaos Scenario 3: Runtime Security Anomaly Simulation (Falco Trigger)
Emits runtime security alerts and automatically submits incident to AegisOps Control Plane.
"""
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chaos-security")

IDP_PORTAL_URL = "http://localhost:8005"


def trigger_security_anomaly():
    logger.info("Simulating unauthorized interactive shell launch inside production pod...")
    logger.warning("Falco Alert Simulated: CRITICAL: Shell spawned in pod (user=root pod=payment-service-78d4c9f96b-x92zk ns=production cmd=/bin/sh)")
    logger.warning("Falco Alert Simulated: WARNING: Sensitive credential file accessed (user=root pod=payment-service-78d4c9f96b-x92zk file=/var/run/secrets/kubernetes.io/serviceaccount/token)")

    # Post event to AegisOps IDP Control Plane
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(f"{IDP_PORTAL_URL}/api/incidents/trigger", json={
                "scenario": "security_threat",
                "service": "payment-service"
            })
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"✅ Incident submitted to AegisOps Control Plane! Incident ID: {data.get('incident_id')}")
                logger.info(f"👉 Check live triage on IDP Web UI: {IDP_PORTAL_URL}")
    except Exception as e:
        logger.info(f"Note: IDP portal at {IDP_PORTAL_URL} not reachable ({e}). If the UI server is running, the incident will appear live.")


if __name__ == "__main__":
    trigger_security_anomaly()
