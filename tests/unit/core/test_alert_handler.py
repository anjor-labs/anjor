"""Unit tests for AlertHandler and AlertConfig."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from anjor.core.config import AlertConfig, AnjorConfig
from anjor.core.pipeline.handlers import AlertHandler, _compare, _event_cost_usd


def _make_alert(**kwargs) -> AlertConfig:  # type: ignore[return]
    defaults = {
        "name": "test_alert",
        "condition": "failure_rate > 0.20",
        "window_calls": 3,
        "webhook": "https://example.com/hook",
    }
    defaults.update(kwargs)
    return AlertConfig(**defaults)


class TestAlertConfig:
    def test_defaults(self) -> None:
        a = AlertConfig(name="x", condition="failure_rate > 0.5", webhook="https://x.com")
        assert a.window_calls == 10

    def test_custom_window(self) -> None:
        a = AlertConfig(
            name="x", condition="failure_rate > 0.5", window_calls=5, webhook="https://x.com"
        )
        assert a.window_calls == 5

    def test_alerts_field_on_config(self) -> None:
        cfg = AnjorConfig()
        assert cfg.alerts == []

    def test_alerts_loaded_from_init(self) -> None:
        alert = AlertConfig(name="x", condition="failure_rate > 0.1", webhook="https://x.com")
        cfg = AnjorConfig(alerts=[alert])  # type: ignore[call-arg]
        assert len(cfg.alerts) == 1
        assert cfg.alerts[0].name == "x"


class TestCompare:
    def test_gt(self) -> None:
        assert _compare(0.3, ">", 0.2)
        assert not _compare(0.1, ">", 0.2)

    def test_ge(self) -> None:
        assert _compare(0.2, ">=", 0.2)
        assert not _compare(0.1, ">=", 0.2)

    def test_lt(self) -> None:
        assert _compare(0.1, "<", 0.2)
        assert not _compare(0.3, "<", 0.2)

    def test_le(self) -> None:
        assert _compare(0.2, "<=", 0.2)

    def test_eq(self) -> None:
        assert _compare(1.0, "==", 1.0)
        assert not _compare(0.5, "==", 1.0)


class TestEventCostUsd:
    def test_known_model(self) -> None:
        event = {
            "event_type": "llm_call",
            "model": "claude-sonnet-4-6",
            "token_usage": {"input": 1_000_000, "output": 0, "cache_creation": 0, "cache_read": 0},
        }
        cost = _event_cost_usd(event)
        assert abs(cost - 3.00) < 0.001

    def test_no_usage(self) -> None:
        event = {"event_type": "llm_call", "model": "claude-sonnet-4-6", "token_usage": None}
        assert _event_cost_usd(event) == 0.0

    def test_no_model(self) -> None:
        event = {"event_type": "llm_call", "token_usage": {"input": 0, "output": 0}}
        assert _event_cost_usd(event) == 0.0


class TestAlertHandlerFailureRate:
    def _tool_event(self, status: str = "failure") -> dict:  # type: ignore[return]
        return {"event_type": "tool_call", "status": status, "latency_ms": 100.0}

    def test_no_fire_before_window_full(self) -> None:
        h = AlertHandler([_make_alert(condition="failure_rate > 0.20", window_calls=3)])
        fires = h._evaluate(self._tool_event("failure"))
        assert fires == []

    def test_fires_when_rate_exceeded(self) -> None:
        h = AlertHandler([_make_alert(condition="failure_rate > 0.20", window_calls=3)])
        h._evaluate(self._tool_event("failure"))
        h._evaluate(self._tool_event("failure"))
        fires = h._evaluate(self._tool_event("failure"))
        assert len(fires) == 1
        assert fires[0]["name"] == "test_alert"
        assert fires[0]["metric"] == "failure_rate"
        assert fires[0]["value"] == pytest.approx(1.0)
        assert fires[0]["threshold"] == pytest.approx(0.20)

    def test_no_fire_when_rate_below_threshold(self) -> None:
        h = AlertHandler([_make_alert(condition="failure_rate > 0.20", window_calls=3)])
        h._evaluate(self._tool_event("success"))
        h._evaluate(self._tool_event("success"))
        fires = h._evaluate(self._tool_event("success"))
        assert fires == []

    def test_ignores_llm_events(self) -> None:
        h = AlertHandler([_make_alert(condition="failure_rate > 0.20", window_calls=3)])
        fires = h._evaluate({"event_type": "llm_call", "context_utilisation": 0.9})
        assert fires == []


class TestAlertHandlerP95Latency:
    def _tool_event(self, latency: float) -> dict:  # type: ignore[return]
        return {"event_type": "tool_call", "status": "success", "latency_ms": latency}

    def test_fires_when_p95_exceeded(self) -> None:
        h = AlertHandler([_make_alert(condition="p95_latency > 500", window_calls=10)])
        for _ in range(20):
            h._evaluate(self._tool_event(1000.0))
        fires = h._evaluate(self._tool_event(1000.0))
        assert len(fires) == 1
        assert fires[0]["metric"] == "p95_latency"
        assert fires[0]["value"] > 500

    def test_no_fire_with_one_event(self) -> None:
        h = AlertHandler([_make_alert(condition="p95_latency > 500", window_calls=10)])
        fires = h._evaluate(self._tool_event(1000.0))
        assert fires == []


class TestAlertHandlerContextUtil:
    def _llm_event(self, ctx: float) -> dict:  # type: ignore[return]
        return {
            "event_type": "llm_call",
            "context_utilisation": ctx,
            "model": "claude-sonnet-4-6",
            "token_usage": {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0},
        }

    def test_fires_above_threshold(self) -> None:
        h = AlertHandler([_make_alert(condition="context_utilisation > 0.80")])
        fires = h._evaluate(self._llm_event(0.85))
        assert len(fires) == 1
        assert fires[0]["value"] == pytest.approx(0.85)

    def test_no_fire_at_threshold(self) -> None:
        h = AlertHandler([_make_alert(condition="context_utilisation > 0.80")])
        fires = h._evaluate(self._llm_event(0.80))
        assert fires == []

    def test_no_fire_below_threshold(self) -> None:
        h = AlertHandler([_make_alert(condition="context_utilisation > 0.80")])
        fires = h._evaluate(self._llm_event(0.75))
        assert fires == []


class TestAlertHandlerDailyCost:
    def _llm_event(self, input_tokens: int) -> dict:  # type: ignore[return]
        return {
            "event_type": "llm_call",
            "model": "claude-sonnet-4-6",
            "context_utilisation": 0.1,
            "token_usage": {
                "input": input_tokens,
                "output": 0,
                "cache_creation": 0,
                "cache_read": 0,
            },
        }

    def test_accumulates_and_fires(self) -> None:
        h = AlertHandler([_make_alert(condition="daily_cost_usd > 0.001")])
        # 1M input tokens at $3/M = $3.00 — well over 0.001
        fires = h._evaluate(self._llm_event(1_000_000))
        assert len(fires) == 1
        assert fires[0]["metric"] == "daily_cost_usd"
        assert fires[0]["value"] > 0.001

    def test_day_rollover_resets(self) -> None:
        h = AlertHandler([_make_alert(condition="daily_cost_usd > 0.001")])
        h._evaluate(self._llm_event(1_000_000))
        h._today = "1970-01-01"  # force reset on next call
        h._evaluate(self._llm_event(1))  # tiny call after reset
        assert h._daily_cost.get("test_alert", 0) < 0.001

    def test_session_cost_accumulates(self) -> None:
        h = AlertHandler([_make_alert(condition="session_cost_usd > 0.001")])
        fires = h._evaluate(self._llm_event(1_000_000))
        assert len(fires) == 1
        assert fires[0]["metric"] == "session_cost_usd"

    def test_session_cost_not_reset_on_day_change(self) -> None:
        h = AlertHandler([_make_alert(condition="session_cost_usd > 0.001")])
        h._evaluate(self._llm_event(1_000_000))
        h._today = "1970-01-01"
        h._evaluate(self._llm_event(1))
        # session cost persists across days (not reset)
        assert h._session_cost.get("test_alert", 0) > 3.0


class TestAlertHandlerErrorType:
    def _tool_event(self, failure_type: str = "timeout") -> dict:  # type: ignore[return]
        return {
            "event_type": "tool_call",
            "status": "failure",
            "failure_type": failure_type,
            "latency_ms": 5000.0,
        }

    def test_fires_on_matching_error_type(self) -> None:
        h = AlertHandler([_make_alert(condition='error_type == "timeout"')])
        fires = h._evaluate(self._tool_event("timeout"))
        assert len(fires) == 1
        assert fires[0]["metric"] == "error_type"

    def test_no_fire_on_different_error_type(self) -> None:
        h = AlertHandler([_make_alert(condition='error_type == "timeout"')])
        fires = h._evaluate(self._tool_event("api_error"))
        assert fires == []

    def test_no_fire_on_success(self) -> None:
        h = AlertHandler([_make_alert(condition='error_type == "timeout"')])
        fires = h._evaluate({"event_type": "tool_call", "status": "success", "failure_type": None})
        assert fires == []

    def test_unquoted_value(self) -> None:
        h = AlertHandler([_make_alert(condition="error_type == timeout")])
        fires = h._evaluate(self._tool_event("timeout"))
        assert len(fires) == 1


class TestAlertHandlerWebhook:
    def _mock_client(self) -> tuple[AsyncMock, AsyncMock]:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        return mock_client, mock_client.post

    @pytest.mark.asyncio
    async def test_slack_payload_format(self) -> None:
        h = AlertHandler([_make_alert()])
        mock_client, mock_post = self._mock_client()
        with patch("httpx.AsyncClient", return_value=mock_client):
            await h._fire_all(
                [
                    {
                        "name": "test_alert",
                        "webhook": "https://hooks.slack.com/services/abc",
                        "metric": "failure_rate",
                        "value": 1.0,
                        "threshold": 0.2,
                    }
                ]
            )
        mock_post.assert_awaited_once()
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
        assert "text" in payload
        assert "test_alert" in payload["text"]

    @pytest.mark.asyncio
    async def test_generic_payload_format(self) -> None:
        h = AlertHandler([_make_alert()])
        mock_client, mock_post = self._mock_client()
        with patch("httpx.AsyncClient", return_value=mock_client):
            await h._fire_all(
                [
                    {
                        "name": "test_alert",
                        "webhook": "https://example.com/hook",
                        "metric": "failure_rate",
                        "value": 0.5,
                        "threshold": 0.2,
                    }
                ]
            )
        mock_post.assert_awaited_once()
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
        assert payload["alert"] == "test_alert"
        assert payload["metric"] == "failure_rate"
        assert payload["value"] == pytest.approx(0.5)
        assert payload["threshold"] == pytest.approx(0.2)
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_webhook_failure_is_swallowed(self) -> None:
        h = AlertHandler([_make_alert()])
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=Exception("conn refused"))
        with patch("httpx.AsyncClient", return_value=mock_client):
            # Must not raise
            await h._fire_all(
                [
                    {
                        "name": "x",
                        "webhook": "https://example.com",
                        "metric": "m",
                        "value": 1.0,
                        "threshold": 0.0,
                    }
                ]
            )


class TestAlertHandlerHandleDict:
    @pytest.mark.asyncio
    async def test_empty_alerts_is_noop(self) -> None:
        h = AlertHandler([])
        with patch.object(h, "_evaluate") as mock_eval:
            await h.handle_dict({"event_type": "tool_call"})
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_task_on_fire(self) -> None:
        h = AlertHandler([_make_alert(condition="failure_rate > 0.20", window_calls=1)])
        event = {"event_type": "tool_call", "status": "failure", "latency_ms": 100.0}

        tasks_created: list[str] = []

        async def fake_fire_all(fires: list) -> None:
            tasks_created.append("fired")

        h._fire_all = fake_fire_all  # type: ignore[method-assign]

        with patch("asyncio.create_task") as mock_create:
            mock_create.side_effect = lambda coro: asyncio.get_event_loop().create_task(coro)
            await h.handle_dict(event)
            mock_create.assert_called_once()


class TestAlertHandlerBadCondition:
    def test_bad_condition_logged_not_raised(self) -> None:
        h = AlertHandler([_make_alert(condition="this is not valid!!!")])
        fires = h._evaluate({"event_type": "tool_call", "status": "failure"})
        assert fires == []

    def test_multiple_alerts_partial_bad(self) -> None:
        alerts = [
            _make_alert(name="bad", condition="!!!"),
            _make_alert(name="good", condition="failure_rate > 0.20", window_calls=1),
        ]
        h = AlertHandler(alerts)
        fires = h._evaluate({"event_type": "tool_call", "status": "failure", "latency_ms": 100.0})
        assert len(fires) == 1
        assert fires[0]["name"] == "good"
