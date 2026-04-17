"""Integration tests for CLI async DB helper functions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anjor.cli import _find_last_session_minutes, _query_diff_windows


async def _setup_db(db_path: str) -> None:
    """Create tables and insert test rows."""
    import aiosqlite

    now = datetime.now(UTC)
    t_recent = (now - timedelta(minutes=5)).isoformat()
    t_old = (now - timedelta(minutes=90)).isoformat()

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY,
                tool_name TEXT, status TEXT, latency_ms REAL,
                timestamp TEXT, session_id TEXT, project TEXT DEFAULT ''
            )"""
        )
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY,
                model TEXT, token_input INTEGER,
                timestamp TEXT, project TEXT DEFAULT ''
            )"""
        )
        await conn.executemany(
            "INSERT INTO tool_calls (tool_name, status, latency_ms, timestamp, session_id, project)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("bash", "success", 100.0, t_recent, "s1", ""),
                ("bash", "failure", 500.0, t_recent, "s1", ""),
                ("read_file", "success", 50.0, t_old, "s0", ""),
            ],
        )
        await conn.executemany(
            "INSERT INTO llm_calls (model, token_input, timestamp, project) VALUES (?, ?, ?, ?)",
            [
                ("claude-sonnet-4-6", 5000, t_recent, ""),
            ],
        )
        await conn.commit()


@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    asyncio.run(_setup_db(db_path))
    return db_path


class TestQueryDiffWindows:
    def test_current_window_contains_recent_rows(self, tmp_db: str) -> None:
        cur, pri, _ct, _pt = asyncio.run(_query_diff_windows(tmp_db, 60, None))
        tool_names = {r["tool_name"] for r in cur}
        assert "bash" in tool_names

    def test_prior_window_contains_old_rows(self, tmp_db: str) -> None:
        cur, pri, _ct, _pt = asyncio.run(_query_diff_windows(tmp_db, 60, None))
        tool_names = {r["tool_name"] for r in pri}
        assert "read_file" in tool_names

    def test_current_window_excludes_old_rows(self, tmp_db: str) -> None:
        cur, _pri, _ct, _pt = asyncio.run(_query_diff_windows(tmp_db, 60, None))
        tool_names = {r["tool_name"] for r in cur}
        assert "read_file" not in tool_names

    def test_avg_token_computed(self, tmp_db: str) -> None:
        _cur, _pri, cur_token, _pt = asyncio.run(_query_diff_windows(tmp_db, 60, None))
        assert cur_token == pytest.approx(5000.0)

    def test_project_filter(self, tmp_db: str) -> None:
        cur, pri, _ct, _pt = asyncio.run(_query_diff_windows(tmp_db, 60, "nonexistent"))
        assert cur == []
        assert pri == []

    def test_bad_db_path_returns_empty(self) -> None:
        cur, pri, ct, pt = asyncio.run(_query_diff_windows("/nonexistent/path/to/db.db", 60, None))
        assert cur == []
        assert pri == []
        assert ct == 0.0
        assert pt == 0.0


class TestFindLastSessionMinutes:
    def test_returns_minutes_since_last_session(self, tmp_db: str) -> None:
        minutes = asyncio.run(_find_last_session_minutes(tmp_db))
        assert 1 <= minutes <= 30  # session started ~5 minutes ago

    def test_bad_db_returns_fallback(self) -> None:
        minutes = asyncio.run(_find_last_session_minutes("/nonexistent/path/db.db"))
        assert minutes == 120

    def test_empty_db_returns_fallback(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "empty.db")

        async def _create_empty(path: str) -> None:
            import aiosqlite

            async with aiosqlite.connect(path) as conn:
                await conn.execute(
                    "CREATE TABLE tool_calls (id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT)"
                )
                await conn.commit()

        asyncio.run(_create_empty(db_path))
        minutes = asyncio.run(_find_last_session_minutes(db_path))
        assert minutes == 120
