"""Restricted, event-isolated execution of configured Telegram workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Literal, Protocol, cast

from .config import CaseConfig, StepConfig, WorkflowConfig

ButtonKind = Literal[
    "callback",
    "reply",
    "url",
    "web_app",
    "payment",
    "request_phone",
    "request_location",
    "captcha",
]
EventKind = Literal["new_message", "edited_message", "callback_answer"]
FailureReason = Literal[
    "timeout",
    "unmatched",
    "send_failed",
    "button_missing",
    "button_ambiguous",
    "unsupported_button",
    "budget_exhausted",
]


@dataclass(frozen=True, slots=True)
class Button:
    """A visible button extracted from a Telegram reply."""

    text: str
    kind: ButtonKind
    data: bytes | None = None


@dataclass(frozen=True, slots=True)
class Reply:
    """The message that can provide buttons for a later click step."""

    message_id: int
    target: str
    buttons: tuple[Button, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    """An inbound event normalized across new, edited and callback answers."""

    kind: EventKind
    target: str
    occurred_at: datetime
    text: str
    reply: Reply | None = None
    attempt_id: str | None = None


class WorkflowGateway(Protocol):
    """The minimal Telegram surface required by the workflow engine."""

    async def send_message(self, target: str, text: str) -> Reply: ...

    async def next_event(self, timeout: float) -> WorkflowEvent: ...

    async def click_button(self, reply: Reply, button: Button) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkflowOutcome:
    status: Literal["success", "failure"]
    reason: str
    step_id: str
    event_kind: EventKind | None = None


class StepFailure(Exception):
    """An expected, user-actionable failure while executing one step."""

    def __init__(self, reason: FailureReason, event_kind: EventKind | None = None) -> None:
        self.reason = reason
        self.event_kind = event_kind
        super().__init__(reason)


async def run_workflow(
    workflow: WorkflowConfig,
    gateway: WorkflowGateway,
    *,
    attempt_id: str,
    attempt_started_at: datetime | None = None,
    deadline: float | None = None,
) -> WorkflowOutcome:
    """Execute one attempt and stop at a terminal target or the supplied deadline."""
    started_at = attempt_started_at or datetime.now(UTC)
    step_indexes = {step.id: index for index, step in enumerate(workflow.steps)}
    current_step_id = workflow.steps[0].id
    last_reply: Reply | None = None
    while True:
        step = workflow.steps[step_indexes[current_step_id]]
        try:
            if deadline is not None and monotonic() >= deadline:
                raise StepFailure("budget_exhausted")
            next_target, last_reply, event_kind = await _run_step(
                workflow.target,
                step,
                gateway,
                last_reply,
                attempt_id,
                started_at,
                deadline,
            )
        except StepFailure as exc:
            return WorkflowOutcome(
                status="failure",
                reason=exc.reason,
                step_id=step.id,
                event_kind=exc.event_kind,
            )
        if next_target in {"success", "failure"}:
            return WorkflowOutcome(
                status=cast(Literal["success", "failure"], next_target),
                reason=next_target,
                step_id=step.id,
                event_kind=event_kind,
            )
        current_step_id = next_target


async def _run_step(
    target: str,
    step: StepConfig,
    gateway: WorkflowGateway,
    last_reply: Reply | None,
    attempt_id: str,
    started_at: datetime,
    deadline: float | None,
) -> tuple[str, Reply | None, EventKind | None]:
    if step.type == "send":
        assert step.text is not None and step.next is not None
        try:
            reply = await _with_step_timeout(
                gateway.send_message(target, step.text), step.timeout, deadline
            )
        except StepFailure:
            raise
        except Exception as exc:
            raise StepFailure("send_failed") from exc
        return step.next, reply, None

    if step.type == "click":
        assert step.text is not None
        if last_reply is None:
            raise StepFailure("button_missing")
        matches = tuple(button for button in last_reply.buttons if button.text == step.text)
        if not matches:
            raise StepFailure("button_missing")
        if len(matches) != 1:
            raise StepFailure("button_ambiguous")
        button = matches[0]
        if button.kind not in {"callback", "reply"}:
            raise StepFailure("unsupported_button")
        try:
            await _with_step_timeout(
                gateway.click_button(last_reply, button), step.timeout, deadline
            )
        except StepFailure:
            raise
        except Exception as exc:
            raise StepFailure("send_failed") from exc

    event = await _wait_for_case(
        target,
        step,
        gateway,
        attempt_id,
        started_at,
        deadline,
    )
    return event[0].next, event[1].reply, event[1].kind


async def _wait_for_case(
    target: str,
    step: StepConfig,
    gateway: WorkflowGateway,
    attempt_id: str,
    started_at: datetime,
    deadline: float | None,
) -> tuple[CaseConfig, WorkflowEvent]:
    step_deadline = monotonic() + _step_timeout(step.timeout, deadline)
    remaining = max(0.0, step_deadline - monotonic())
    saw_relevant_event = False
    while remaining > 0:
        try:
            event = await gateway.next_event(remaining)
        except TimeoutError as exc:
            raise StepFailure("unmatched" if saw_relevant_event else "timeout") from exc
        remaining = max(0.0, step_deadline - monotonic())
        if event.target != target:
            continue
        if event.occurred_at < started_at:
            continue
        if event.attempt_id is not None and event.attempt_id != attempt_id:
            continue
        saw_relevant_event = True
        for case in step.cases:
            if _matches(case, event.text):
                return case, event
    raise StepFailure("unmatched" if saw_relevant_event else "timeout")


async def _with_step_timeout[T](
    operation: Awaitable[T], configured_timeout: int, deadline: float | None
) -> T:
    timeout = _step_timeout(configured_timeout, deadline)
    if timeout <= 0:
        close = getattr(operation, "close", None)
        if callable(close):
            close()
        raise StepFailure("budget_exhausted")
    try:
        return await asyncio.wait_for(operation, timeout=timeout)
    except TimeoutError as exc:
        raise StepFailure("timeout") from exc


def _step_timeout(configured_timeout: int, deadline: float | None) -> float:
    if deadline is None:
        return float(configured_timeout)
    return min(float(configured_timeout), max(0.0, deadline - monotonic()))


def _matches(case: CaseConfig, text: str) -> bool:
    actual = text.strip().casefold()
    expected = case.value.strip().casefold()
    if case.match == "exact":
        return actual == expected
    return expected in actual
