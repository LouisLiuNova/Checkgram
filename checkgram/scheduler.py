"""Deterministic scheduling and bounded retry rounds."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from .config import Config, WorkflowConfig
from .workflow import WorkflowOutcome

ROUND_BUDGET_SECONDS = 60 * 60


class SchedulerError(ValueError):
    """An invalid scheduler input that is safe to show to an operator."""


@dataclass(frozen=True, slots=True)
class RoundResult:
    outcome: WorkflowOutcome
    attempts: int


AttemptRunner = Callable[[int, float], Awaitable[WorkflowOutcome]]


RoundRunner = Callable[[], Awaitable[RoundResult]]


def next_scheduled_at(now: datetime, workflow: WorkflowConfig, timezone: str) -> datetime:
    """Return the first configured local time strictly later than ``now``."""
    if now.tzinfo is None:
        raise SchedulerError("scheduler clock must return an aware datetime")
    try:
        zone = ZoneInfo(timezone)
    except Exception as exc:
        raise SchedulerError("invalid scheduler timezone") from exc
    current = now.astimezone(UTC)
    local_date = now.astimezone(zone).date()
    for day_offset in range(367):
        candidate_date = local_date + timedelta(days=day_offset)
        for scheduled_time in sorted(workflow.times):
            candidate_local = datetime.combine(candidate_date, scheduled_time, tzinfo=zone)
            candidate = candidate_local.astimezone(UTC)
            if candidate > current:
                return candidate
    raise SchedulerError("could not find the next schedule time")


def backoff_minutes(failure_number: int) -> int:
    """Return the deterministic 2/4/8/16... minute delay after a failure."""
    if failure_number < 1:
        raise SchedulerError("failure number must be positive")
    return 1 << failure_number


async def run_round(
    attempt_runner: AttemptRunner,
    *,
    clock: Callable[[], float] = monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    budget_seconds: float = ROUND_BUDGET_SECONDS,
) -> RoundResult:
    """Run attempts serially within one fixed, non-persisted time budget."""
    deadline = clock() + budget_seconds
    attempt_number = 1
    last_outcome = WorkflowOutcome(status="failure", reason="budget_exhausted", step_id="unknown")
    while clock() < deadline:
        last_outcome = await attempt_runner(attempt_number, deadline)
        if last_outcome.status == "success":
            return RoundResult(outcome=last_outcome, attempts=attempt_number)
        delay_seconds = backoff_minutes(attempt_number) * 60
        if clock() + delay_seconds >= deadline:
            return RoundResult(
                outcome=WorkflowOutcome(
                    status="failure",
                    reason="budget_exhausted",
                    step_id=last_outcome.step_id,
                    event_kind=last_outcome.event_kind,
                ),
                attempts=attempt_number,
            )
        await sleep(delay_seconds)
        attempt_number += 1
    return RoundResult(
        outcome=WorkflowOutcome(
            status="failure",
            reason="budget_exhausted",
            step_id=last_outcome.step_id,
            event_kind=last_outcome.event_kind,
        ),
        attempts=attempt_number - 1,
    )


async def serve(
    config: Config,
    round_runner_factory: Callable[[WorkflowConfig], RoundRunner],
    *,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    stop: Callable[[], bool] = lambda: False,
) -> None:
    """Wait for strict future schedules and run due workflows globally in order."""
    while not stop():
        now = clock()
        candidates = [
            (next_scheduled_at(now, workflow, config.app.timezone), workflow)
            for workflow in config.workflows
        ]
        if not candidates:
            raise SchedulerError("at least one workflow is required for serve")
        due_at = min(candidate[0] for candidate in candidates)
        wait_seconds = max(0.0, (due_at - now.astimezone(UTC)).total_seconds())
        if wait_seconds > 0:
            await sleep(wait_seconds)
        current = clock()
        due = sorted(
            (candidate, workflow)
            for candidate, workflow in candidates
            if candidate <= current.astimezone(UTC)
        )
        for _, workflow in due:
            if stop():
                return
            await round_runner_factory(workflow)()
