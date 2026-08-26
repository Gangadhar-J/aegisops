import os
import time
import uuid
import logging
import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "order-service")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
OTEL_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector.observability.svc.cluster.local:4317")

resource = Resource.create({"service.name": SERVICE_NAME, "service.version": "1.0.0", "environment": os.getenv("ENV", "production")})
provider = TracerProvider(resource=resource)

try:
    otlp_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
except Exception:
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# Structured Logging with Trace Correlation
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [trace_id=%(otelTraceID)s] %(message)s")
logger = logging.getLogger(SERVICE_NAME)

class TraceFilter(logging.Filter):
    def filter(self, record):
        span = trace.get_current_span()
        if span.is_recording():
            ctx = span.get_span_context()
            record.otelTraceID = format(ctx.trace_id, "032x")
        else:
            record.otelTraceID = "00000000000000000000000000000000"
        return True

logger.addFilter(TraceFilter())

# Prometheus Metrics
ORDER_REQUESTS_TOTAL = Counter("order_requests_total", "Total orders processed", ["status"])
ORDER_LATENCY_SECONDS = Histogram("order_processing_latency_seconds", "Order processing latency", buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])

app = FastAPI(title="Order Service", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
HTTPXClientInstrumentor().instrument()

class CreateOrderRequest(BaseModel):
    customer_id: str
    items: list
    amount: float
    currency: str = "USD"

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": "1.0.0"}

@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/orders")
async def create_order(order: CreateOrderRequest):
    start_time = time.time()
    order_id = f"ord_{uuid.uuid4().hex[:8]}"

    with tracer.start_as_current_span("create_order_workflow") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("order.customer_id", order.customer_id)
        span.set_attribute("order.amount", order.amount)

        logger.info(f"Initiating order {order_id} for customer {order.customer_id}, calling payment service at {PAYMENT_SERVICE_URL}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                pay_resp = await client.post(
                    f"{PAYMENT_SERVICE_URL}/process-payment",
                    json={
                        "order_id": order_id,
                        "amount": order.amount,
                        "currency": order.currency,
                        "payment_method": "credit_card"
                    }
                )
                if pay_resp.status_code != 200:
                    ORDER_REQUESTS_TOTAL.labels(status="failure").inc()
                    logger.error(f"Payment service rejected order {order_id} with status {pay_resp.status_code}: {pay_resp.text}")
                    raise HTTPException(status_code=502, detail=f"Downstream payment failed: {pay_resp.text}")

                payment_data = pay_resp.json()
            except httpx.RequestError as exc:
                ORDER_REQUESTS_TOTAL.labels(status="failure").inc()
                logger.error(f"Failed to connect to payment service for order {order_id}: {exc}")
                raise HTTPException(status_code=504, detail=f"Payment service network timeout/unreachable: {str(exc)}")

        ORDER_REQUESTS_TOTAL.labels(status="success").inc()
        duration = time.time() - start_time
        ORDER_LATENCY_SECONDS.observe(duration)

        return {
            "order_id": order_id,
            "status": "CONFIRMED",
            "payment": payment_data,
            "processing_time_ms": round(duration * 1000, 2)
        }
