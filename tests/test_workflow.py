from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest

from checkgram.config import WorkflowConfig, parse_config
from checkgram.workflow import Button, Reply, WorkflowEvent, WorkflowOutcome, run_workflow


class FakeGateway:
    def __init__(self, events: list[WorkflowEvent]) -> None:
        self.events = deque(events)
        self.sent: list[tuple[str, str]] = []
        self.clicked: list[tuple[int, str]] = []

    async def send_message(self, target: str, text: str) -> Reply:
        self.sent.append((target, text))
        return Reply(message_id=1, target=target)

    async def next_event(self, timeout: float) -> WorkflowEvent:
        if not self.events:
            await asyncio.sleep(min(timeout, 0.001))
            raise TimeoutError
        return self.events.popleft()

    async def click_button(self, reply: Reply, button: Button) -> None:
        self.clicked.append((reply.message_id, button.text))


def workflow_document(*steps: dict[str, object]) -> dict[str, object]:
    return {
        "app": {"timezone": "Asia/Shanghai", "step_timeout": 1},
        "workflows": [
            {
                "id": "test",
                "account": "primary",
                "target": "@target_bot",
                "times": ["08:00"],
                "steps": list(steps),
            }
        ],
    }


def parse_workflow(*steps: dict[str, object]) -> WorkflowConfig:
    return parse_config(workflow_document(*steps)).workflows[0]


def event(
    text: str,
    *,
    target: str = "@target_bot",
    kind: str = "new_message",
    age: int = 0,
    attempt_id: str | None = "attempt-1",
    reply: Reply | None = None,
) -> WorkflowEvent:
    return WorkflowEvent(
        kind=kind,  # type: ignore[arg-type]
        target=target,
        occurred_at=datetime.now(UTC) + timedelta(seconds=age),
        text=text,
        attempt_id=attempt_id,
        reply=reply,
    )


def run(workflow: WorkflowConfig, gateway: FakeGateway) -> WorkflowOutcome:
    return asyncio.run(
        run_workflow(
            workflow,
            gateway,
            attempt_id="attempt-1",
            attempt_started_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )


def test_send_wait_supports_exact_and_contains_matches() -> None:
    workflow = parse_workflow(
        {"id": "send", "type": "send", "text": "/start", "next": "wait"},
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "ok", "match": "contains", "value": "success", "next": "success"}],
        },
    )
    gateway = FakeGateway([event("  SIGN-IN SUCCESS  ")])
    outcome = run(workflow, gateway)
    assert outcome.status == "success"
    assert gateway.sent == [("@target_bot", "/start")]


@pytest.mark.parametrize("kind", ["new_message", "edited_message", "callback_answer"])
def test_all_supported_event_sources_can_advance(kind: str) -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "ok", "match": "exact", "value": "OK", "next": "success"}],
        }
    )
    outcome = run(workflow, FakeGateway([event("ok", kind=kind)]))
    assert outcome.status == "success"
    assert outcome.event_kind == kind


def test_stale_other_target_and_other_attempt_events_do_not_advance() -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "ok", "match": "exact", "value": "OK", "next": "success"}],
        }
    )
    gateway = FakeGateway(
        [
            event("OK", age=-2),
            event("OK", target="@other_bot"),
            event("OK", attempt_id="attempt-0"),
            event("OK"),
        ]
    )
    outcome = run(workflow, gateway)
    assert outcome.status == "success"


def test_timeout_and_unmatched_result_in_failure() -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "timeout": 1,
            "cases": [{"id": "ok", "match": "exact", "value": "OK", "next": "success"}],
        }
    )
    outcome = run(workflow, FakeGateway([event("not-ok")]))
    assert outcome.status == "failure"
    assert outcome.reason == "unmatched"


def test_explicit_failure_case_stops_with_failure_outcome() -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "failed", "match": "contains", "value": "denied", "next": "failure"}],
        }
    )
    outcome = run(workflow, FakeGateway([event("access denied")]))
    assert outcome.status == "failure"
    assert outcome.reason == "failure"


def test_click_selects_one_supported_visible_button() -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "buttons", "match": "contains", "value": "choose", "next": "click"}],
        },
        {
            "id": "click",
            "type": "click",
            "text": "Confirm",
            "cases": [{"id": "ok", "match": "exact", "value": "done", "next": "success"}],
        },
    )
    reply = Reply(
        message_id=7,
        target="@target_bot",
        buttons=(Button(text="Confirm", kind="callback"),),
    )
    gateway = FakeGateway([event("choose", reply=reply), event("done")])
    outcome = run(workflow, gateway)
    assert outcome.status == "success"
    assert gateway.clicked == [(7, "Confirm")]


def test_click_contains_selects_one_button_and_rejects_ambiguous_matches() -> None:
    workflow = parse_workflow(
        {"id": "send", "type": "send", "text": "/start", "next": "wait"},
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "page", "match": "contains", "value": "未签到", "next": "click"}],
        },
        {
            "id": "click",
            "type": "click",
            "text": "立即签到",
            "button_match": "contains",
            "cases": [{"id": "ok", "match": "contains", "value": "签到成功", "next": "success"}],
        },
    )
    reply = Reply(
        message_id=7,
        target="@target_bot",
        buttons=(Button(text="📝 立即签到", kind="callback"),),
    )
    gateway = FakeGateway([event("今日未签到", reply=reply), event("签到成功！")])
    assert run(workflow, gateway).status == "success"
    assert gateway.clicked == [(7, "📝 立即签到")]

    ambiguous = Reply(
        message_id=8,
        target="@target_bot",
        buttons=(
            Button(text="📝 立即签到", kind="callback"),
            Button(text="立即签到（备用）", kind="callback"),
        ),
    )
    outcome = run(workflow, FakeGateway([event("今日未签到", reply=ambiguous)]))
    assert outcome.reason == "button_ambiguous"


def test_optional_quiz_after_success_and_timeout_success() -> None:
    workflow = parse_workflow(
        {"id": "send", "type": "send", "text": "📅 每日签到", "next": "page"},
        {
            "id": "page",
            "type": "wait",
            "cases": [{"id": "open", "match": "contains", "value": "今日未签到", "next": "sign"}],
        },
        {
            "id": "sign",
            "type": "click",
            "text": "立即签到",
            "button_match": "contains",
            "cases": [
                {"id": "success", "match": "contains", "value": "签到成功！", "next": "maybe-quiz"},
                {"id": "quiz", "match": "contains", "value": "记忆小测", "next": "answer"},
            ],
        },
        {
            "id": "maybe-quiz",
            "type": "wait",
            "timeout_next": "success",
            "cases": [{"id": "quiz", "match": "contains", "value": "记忆小测", "next": "answer"}],
        },
        {
            "id": "answer",
            "type": "click",
            "text": "oixel.net",
            "button_match": "contains",
            "cases": [
                {"id": "correct", "match": "contains", "value": "答对了！", "next": "success"}
            ],
        },
    )
    sign_reply = Reply(
        message_id=7,
        target="@target_bot",
        buttons=(Button(text="📝 立即签到", kind="callback"),),
    )
    quiz_reply = Reply(
        message_id=8,
        target="@target_bot",
        buttons=(Button(text="oixel.net ✅", kind="callback"),),
    )
    gateway = FakeGateway(
        [
            event("今日未签到", reply=sign_reply),
            event("签到成功！"),
            event("记忆小测", reply=quiz_reply),
            event("答对了！"),
        ]
    )
    assert run(workflow, gateway).status == "success"
    assert gateway.clicked == [(7, "📝 立即签到"), (8, "oixel.net ✅")]

    no_quiz = FakeGateway([event("今日未签到", reply=sign_reply), event("签到成功！")])
    assert run(workflow, no_quiz).status == "success"
    assert no_quiz.clicked == [(7, "📝 立即签到")]

    unexpected = FakeGateway(
        [event("今日未签到", reply=sign_reply), event("签到成功！"), event("未知提示")]
    )
    assert run(workflow, unexpected).reason == "unmatched"


@pytest.mark.parametrize(
    ("buttons", "reason"),
    [
        ((), "button_missing"),
        (
            (Button(text="Confirm", kind="callback"), Button(text="Confirm", kind="reply")),
            "button_ambiguous",
        ),
        ((Button(text="Confirm", kind="url"),), "unsupported_button"),
        ((Button(text="Confirm", kind="web_app"),), "unsupported_button"),
        ((Button(text="Confirm", kind="payment"),), "unsupported_button"),
        ((Button(text="Confirm", kind="request_phone"),), "unsupported_button"),
        ((Button(text="Confirm", kind="request_location"),), "unsupported_button"),
        ((Button(text="Confirm", kind="captcha"),), "unsupported_button"),
    ],
)
def test_click_rejects_missing_ambiguous_and_unsupported_buttons(
    buttons: tuple[Button, ...], reason: str
) -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "cases": [{"id": "buttons", "match": "exact", "value": "choose", "next": "click"}],
        },
        {
            "id": "click",
            "type": "click",
            "text": "Confirm",
            "cases": [{"id": "ok", "match": "exact", "value": "done", "next": "success"}],
        },
    )
    reply = Reply(message_id=7, target="@target_bot", buttons=buttons)
    outcome = run(workflow, FakeGateway([event("choose", reply=reply)]))
    assert outcome.status == "failure"
    assert outcome.reason == reason


def test_click_without_a_previous_reply_is_rejected() -> None:
    workflow = parse_workflow(
        {
            "id": "click",
            "type": "click",
            "text": "Confirm",
            "cases": [{"id": "ok", "match": "exact", "value": "done", "next": "success"}],
        }
    )
    outcome = run(workflow, FakeGateway([]))
    assert outcome.status == "failure"
    assert outcome.reason == "button_missing"


def test_step_timeout_is_capped_by_attempt_deadline() -> None:
    workflow = parse_workflow(
        {
            "id": "wait",
            "type": "wait",
            "timeout": 60,
            "cases": [{"id": "ok", "match": "exact", "value": "OK", "next": "success"}],
        }
    )
    gateway = FakeGateway([])
    outcome = asyncio.run(
        run_workflow(
            workflow,
            gateway,
            attempt_id="attempt-1",
            attempt_started_at=datetime.now(UTC),
            deadline=monotonic() + 0.01,
        )
    )
    assert outcome.reason == "timeout"
