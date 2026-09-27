from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from checkgram.config import WorkflowConfig, parse_config
from checkgram.scheduler import RoundResult, backoff_minutes, next_scheduled_at, run_round, serve
from checkgram.workflow import WorkflowOutcome


def workflow(times: list[str]) -> WorkflowConfig:
    document = {
        "app": {"timezone": "Asia/Shanghai", "step_timeout": 30},
        "workflows": [
            {
                "id": "daily",
                "account": "primary",
                "target": "@bot",
                "times": times,
                "steps": [{"id": "send", "type": "send", "text": "/start", "next": "success"}],
            }
        ],
    }
    return parse_config(document).workflows[0]


def test_next_schedule_is_strictly_future_and_respects_timezone() -> None:
    item = workflow(["08:00", "23:30"])
    assert next_scheduled_at(
        datetime(2026, 9, 19, 23, 0, tzinfo=UTC), item, "Asia/Shanghai"
    ) == datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
    assert next_scheduled_at(
        datetime(2026, 9, 20, 0, 0, tzinfo=UTC), item, "Asia/Shanghai"
    ) == datetime(2026, 9, 20, 15, 30, tzinfo=UTC)
    assert next_scheduled_at(
        datetime(2026, 9, 20, 16, 0, tzinfo=UTC), item, "Asia/Shanghai"
    ) == datetime(2026, 9, 21, 0, 0, tzinfo=UTC)


def test_backoff_sequence_is_fixed() -> None:
    assert [backoff_minutes(index) for index in range(1, 6)] == [2, 4, 8, 16, 32]
    with pytest.raises(ValueError):
        backoff_minutes(0)


def test_round_stops_after_success_and_uses_backoff() -> None:
    now = 0.0
    attempts: list[int] = []
    sleeps: list[float] = []

    def clock() -> float:
        return now

    async def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    async def attempt(number: int, deadline: float) -> WorkflowOutcome:
        del deadline
        attempts.append(number)
        return WorkflowOutcome(
            status="success" if number == 3 else "failure",
            reason="success" if number == 3 else "unmatched",
            step_id="send",
        )

    result = asyncio.run(run_round(attempt, clock=clock, sleep=sleep, budget_seconds=1000))
    assert result.outcome.status == "success"
    assert result.attempts == 3
    assert attempts == [1, 2, 3]
    assert sleeps == [120, 240]


def test_round_stops_before_retry_when_deadline_would_be_reached() -> None:
    async def attempt(number: int, deadline: float) -> WorkflowOutcome:
        del number, deadline
        return WorkflowOutcome(status="failure", reason="timeout", step_id="wait")

    result = asyncio.run(
        run_round(attempt, clock=lambda: 0.0, sleep=lambda _: asyncio.sleep(0), budget_seconds=100)
    )
    assert result.outcome.reason == "budget_exhausted"
    assert result.attempts == 1


def test_serve_runs_the_strictly_future_candidate_once() -> None:
    item = workflow(["08:00"])
    config = parse_config(
        {
            "app": {"timezone": "Asia/Shanghai", "step_timeout": 30},
            "workflows": [
                {
                    "id": item.id,
                    "account": "primary",
                    "target": "@bot",
                    "times": ["08:00"],
                    "steps": [{"id": "send", "type": "send", "text": "/start", "next": "success"}],
                }
            ],
        }
    )
    current = datetime(2026, 9, 19, 23, 0, tzinfo=UTC)
    runs = 0

    def clock() -> datetime:
        return current

    async def sleep(seconds: float) -> None:
        nonlocal current
        current += timedelta(seconds=seconds)

    async def round_runner() -> RoundResult:
        nonlocal runs
        runs += 1
        return RoundResult(
            outcome=WorkflowOutcome(status="success", reason="success", step_id="send"),
            attempts=1,
        )

    asyncio.run(
        serve(
            config,
            lambda _: round_runner,
            clock=clock,
            sleep=sleep,
            stop=lambda: runs > 0,
        )
    )
    assert runs == 1
