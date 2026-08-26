import os
import time
import random
import logging
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# OpenTelemetry Imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Initialize OpenTelemetry
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "payment-service")
OTEL_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector.observability.svc.cluster.local:4317")

resource = Resource.create({"service.name": SERVICE_NAME, "service.version": "1.0.0", "environment": os.getenv("ENV", "production")})
provider = TracerProvider(resource=resource)

try:
    otlp_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
except Exception as e:
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# Structured Logging
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
PAYMENT_REQUESTS_TOTAL = Counter("payment_requests_total", "Total payment requests", ["status", "currency"])
PAYMENT_LATENCY_SECONDS = Histogram("payment_processing_latency_seconds", "Payment processing latency", buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
MEMORY_LEAK_GAUGE = Gauge("service_memory_leak_bytes", "Bytes held in simulated memory leak")
DB_CONNECTIONS_ACTIVE = Gauge("db_connection_pool_active", "Active simulated database connections")

app = FastAPI(title="Payment Service", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

# In-memory leak storage for chaos simulation
LEAKED_BUFFERS: List[bytearray] = []
CHAOS_STATE = {
    "latency_spike_active": False,
    "latency_duration_sec": 3.0,
    "error_cascade_active": False,
    "error_rate_percentage": 0.0,
    "db_pool_starvation": False
}

class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    currency: str = "USD"
    payment_method: str = "credit_card"

class ChaosConfigRequest(BaseModel):
    latency_spike: bool = False
    latency_sec: float = 2.5
    error_cascade: bool = False
    error_rate: float = 0.8
    db_starvation: bool = False

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": "1.0.0"}

@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/process-payment")
async def process_payment(req: PaymentRequest):
    start_time = time.time()
    with tracer.start_as_current_span("process_payment_workflow") as span:
        span.set_attribute("payment.order_id", req.order_id)
        span.set_attribute("payment.amount", req.amount)
        span.set_attribute("payment.currency", req.currency)

        logger.info(f"Processing payment for Order: {req.order_id}, Amount: {req.amount} {req.currency}")

        # Check Chaos: Error Cascade
        if CHAOS_STATE["error_cascade_active"] and random.random() < CHAOS_STATE["error_rate_percentage"]:
            PAYMENT_REQUESTS_TOTAL.labels(status="failure", currency=req.currency).inc()
            span.set_attribute("error", True)
            span.record_exception(Exception("Downstream Payment Gateway Connection Timed Out"))
            logger.error(f"Payment gateway timeout for order {req.order_id} (simulated 500 error cascade)")
            raise HTTPException(status_code=500, detail="Payment gateway timeout - downstream banking partner unresponsive")

        # Check Chaos: DB Connection Starvation / Latency
        if CHAOS_STATE["latency_spike_active"] or CHAOS_STATE["db_pool_starvation"]:
            with tracer.start_as_current_span("db_acquire_connection") as db_span:
                db_span.set_attribute("db.system", "postgresql")
                db_span.set_attribute("db.pool.status", "exhausted")
                DB_CONNECTIONS_ACTIVE.set(100.0) # max capacity
                time.sleep(CHAOS_STATE["latency_duration_sec"])
                logger.warning(f"Database connection pool starvation: waited {CHAOS_STATE['latency_duration_sec']}s for connection")
        else:
            DB_CONNECTIONS_ACTIVE.set(random.uniform(5.0, 25.0))
            time.sleep(random.uniform(0.02, 0.08)) # normal fast processing

        PAYMENT_REQUESTS_TOTAL.labels(status="success", currency=req.currency).inc()
        duration = time.time() - start_time
        PAYMENT_LATENCY_SECONDS.observe(duration)

        return {
            "status": "success",
            "transaction_id": f"txn_{int(time.time()*1000)}_{random.randint(1000, 9999)}",
            "order_id": req.order_id,
            "duration_ms": round(duration * 1000, 2)
        }

@app.post("/chaos/leak-memory")
def chaos_leak_memory(mb_to_leak: int = 50):
    bytes_count = mb_to_leak * 1024 * 1024
    chunk = bytearray(b"X" * bytes_count)
    LEAKED_BUFFERS.append(chunk)
    total_leaked = sum(len(b) for b in LEAKED_BUFFERS)
    MEMORY_LEAK_GAUGE.set(total_leaked)
    logger.warning(f"CHAOS: Injected memory leak of {mb_to_leak} MB. Total leaked: {total_leaked / (1024*1024):.1f} MB")
    return {
        "status": "memory_leak_injected",
        "leaked_mb_this_call": mb_to_leak,
        "total_leaked_mb": total_leaked / (1024 * 1024)
    }

@app.post("/chaos/reset-memory")
def chaos_reset_memory():
    LEAKED_BUFFERS.clear()
    MEMORY_LEAK_GAUGE.set(0)
    logger.info("CHAOS: Memory leak buffers cleared.")
    return {"status": "memory_reset"}

@app.post("/chaos/configure")
def chaos_configure(config: ChaosConfigRequest):
    CHAOS_STATE["latency_spike_active"] = config.latency_spike
    CHAOS_STATE["latency_duration_sec"] = config.latency_sec
    CHAOS_STATE["error_cascade_active"] = config.error_cascade
    CHAOS_STATE["error_rate_percentage"] = config.error_rate
    CHAOS_STATE["db_pool_starvation"] = config.db_starvation
    logger.warning(f"CHAOS: Updated failure profile: {CHAOS_STATE}")
    return {"status": "configured", "chaos_state": CHAOS_STATE}
