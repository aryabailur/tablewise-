"""Custom Prometheus metrics (exposed on /metrics alongside the HTTP metrics from the instrumentator)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

BOOKINGS_CREATED = Counter("tablewise_bookings_created_total", "Bookings created", ["restaurant", "source"])
BOOKINGS_CANCELLED = Counter("tablewise_bookings_cancelled_total", "Bookings cancelled", ["restaurant"])
CHAT_REQUESTS = Counter("tablewise_chat_requests_total", "Concierge chat turns by routed intent", ["intent"])
CHAT_LATENCY = Histogram("tablewise_chat_latency_seconds", "End-to-end concierge chat turn latency",
                         buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 60))
RAG_RETRIEVAL = Histogram("tablewise_rag_retrieval_seconds", "RAG retrieval latency (embed + vector query)",
                          buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
LLM_ERRORS = Counter("tablewise_llm_errors_total", "LLM call failures (router fallbacks and failed turns)")
