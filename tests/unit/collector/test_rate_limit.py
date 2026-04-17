"""Tests for EventsRateLimitMiddleware and _TokenBucket."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from anjor.collector.api.app import create_app
from anjor.collector.api.middleware import EventsRateLimitMiddleware, _TokenBucket
from anjor.collector.service import CollectorService
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


def _make_client(rps: float = 500, burst: int = 1000) -> TestClient:
    cfg = AnjorConfig(  # type: ignore[call-arg]
        db_path=":memory:",
        batch_size=1,
        batch_interval_ms=9999,
        rate_limit_rps=rps,
        rate_limit_burst=burst,
    )
    svc = CollectorService(
        config=cfg,
        storage=SQLiteBackend(db_path=":memory:", batch_size=1),
        pipeline=EventPipeline(),
    )
    return TestClient(create_app(config=cfg, service=svc))


def _event() -> dict:
    return {
        "event_type": "tool_call",
        "tool_name": "bash",
        "trace_id": "t1",
        "session_id": "s1",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "status": "success",
        "failure_type": None,
        "latency_ms": 50.0,
        "input_payload": {},
        "output_payload": {},
        "input_schema_hash": "",
        "output_schema_hash": "",
    }


# ---------------------------------------------------------------------------
# _TokenBucket unit tests
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_allows_up_to_burst(self) -> None:
        bucket = _TokenBucket(rps=1.0, burst=5)
        for _ in range(5):
            assert bucket.consume("ip") is True

    def test_rejects_when_empty(self) -> None:
        bucket = _TokenBucket(rps=0.0001, burst=1)
        assert bucket.consume("ip") is True  # drain
        assert bucket.consume("ip") is False  # empty

    def test_separate_keys_tracked_independently(self) -> None:
        bucket = _TokenBucket(rps=0.0001, burst=1)
        assert bucket.consume("a") is True
        assert bucket.consume("b") is True  # different IP
        assert bucket.consume("a") is False
        assert bucket.consume("b") is False

    def test_refills_over_time(self) -> None:
        import time

        bucket = _TokenBucket(rps=1000.0, burst=1)
        bucket.consume("ip")  # drain
        time.sleep(0.002)  # 2ms → ~2 tokens at 1000 rps
        assert bucket.consume("ip") is True

    def test_burst_caps_accumulation(self) -> None:
        import time

        bucket = _TokenBucket(rps=1000.0, burst=3)
        time.sleep(0.010)  # would produce 10 tokens, capped at 3
        results = [bucket.consume("ip") for _ in range(4)]
        assert results[:3] == [True, True, True]
        assert results[3] is False

    def test_new_key_starts_at_full_burst(self) -> None:
        bucket = _TokenBucket(rps=1.0, burst=10)
        for _ in range(10):
            assert bucket.consume("fresh") is True
        assert bucket.consume("fresh") is False


# ---------------------------------------------------------------------------
# Middleware integration tests (via TestClient)
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    def test_normal_request_allowed(self) -> None:
        with _make_client(rps=500, burst=1000) as client:
            resp = client.post("/events", json=_event())
        assert resp.status_code == 202

    def test_burst_exhausted_returns_429(self) -> None:
        # rps=0.001 (negligible refill), burst=2 — 3rd immediate request hits limit
        with _make_client(rps=0.001, burst=2) as client:
            client.post("/events", json=_event())
            client.post("/events", json=_event())
            resp = client.post("/events", json=_event())
        assert resp.status_code == 429

    def test_429_has_retry_after_header(self) -> None:
        with _make_client(rps=0.001, burst=1) as client:
            client.post("/events", json=_event())
            resp = client.post("/events", json=_event())
        assert resp.headers.get("retry-after") == "1"

    def test_429_body_has_detail(self) -> None:
        with _make_client(rps=0.001, burst=1) as client:
            client.post("/events", json=_event())
            resp = client.post("/events", json=_event())
        assert "detail" in resp.json()

    def test_get_requests_not_rate_limited(self) -> None:
        # GET /health should never be touched by the rate limiter
        with _make_client(rps=0.001, burst=1) as client:
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_flush_endpoint_not_rate_limited(self) -> None:
        with _make_client(rps=0.001, burst=1) as client:
            resp = client.post("/flush")
        assert resp.status_code == 200

    def test_rate_limit_disabled_when_rps_zero(self) -> None:
        cfg = AnjorConfig(  # type: ignore[call-arg]
            db_path=":memory:",
            batch_size=1,
            batch_interval_ms=9999,
            rate_limit_rps=0,
            rate_limit_burst=1,
        )
        svc = CollectorService(
            config=cfg,
            storage=SQLiteBackend(db_path=":memory:", batch_size=1),
            pipeline=EventPipeline(),
        )
        with TestClient(create_app(service=svc)) as client:
            for _ in range(10):
                resp = client.post("/events", json=_event())
                assert resp.status_code == 202

    def test_middleware_not_added_when_disabled(self) -> None:
        cfg = AnjorConfig(db_path=":memory:", rate_limit_rps=0)  # type: ignore[call-arg]
        svc = CollectorService(
            config=cfg,
            storage=SQLiteBackend(db_path=":memory:"),
            pipeline=EventPipeline(),
        )
        app = create_app(service=svc)
        mw_types = [type(m) for m in app.user_middleware]
        assert EventsRateLimitMiddleware not in mw_types

    def test_middleware_added_when_enabled(self) -> None:
        cfg = AnjorConfig(db_path=":memory:", rate_limit_rps=100)  # type: ignore[call-arg]
        svc = CollectorService(
            config=cfg,
            storage=SQLiteBackend(db_path=":memory:"),
            pipeline=EventPipeline(),
        )
        app = create_app(service=svc)
        mw_types = [m.cls for m in app.user_middleware]
        assert EventsRateLimitMiddleware in mw_types
