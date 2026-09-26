from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from telethon.tl import types

from checkgram.telegram import TelethonGateway, _button_from_telethon, _event_from_telethon
from checkgram.workflow import Button, Reply


def test_telethon_button_wrapper_uses_inner_button_type() -> None:
    callback = types.KeyboardInlineButton(
        text="📝 立即签到", type=types.InlineButtonTypeCallback(data=b"sign")
    )
    reply = types.KeyboardButton(text="Answer", type=types.ButtonTypeDefault())
    url = types.KeyboardInlineButton(
        text="oixel.net", type=types.InlineButtonTypeUrl(url="https://oixel.net")
    )

    assert _button_from_telethon(SimpleNamespace(text=callback.text, button=callback)).kind == (
        "callback"
    )
    assert _button_from_telethon(SimpleNamespace(text=reply.text, button=reply)).kind == "reply"
    assert _button_from_telethon(SimpleNamespace(text=url.text, button=url)).kind == "url"


def test_live_event_uses_receipt_time_instead_of_second_precision_message_date() -> None:
    old_message = SimpleNamespace(date=datetime(2020, 1, 1, tzinfo=UTC), id=8, buttons=[])
    raw_event = SimpleNamespace(chat_id=123, message=old_message, raw_text="签到成功！")
    started_at = datetime.now(UTC)
    event = _event_from_telethon(raw_event, "@target_bot", 123)
    assert event is not None
    assert event.occurred_at >= started_at


def test_gateway_buffers_reply_arriving_during_send() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.handlers: list[Any] = []

        def add_event_handler(self, handler: Any, _: Any) -> None:
            self.handlers.append(handler)

        def remove_event_handler(self, handler: Any, _: Any) -> None:
            self.handlers.remove(handler)

        async def send_message(self, target: str, text: str) -> Any:
            del target, text
            incoming = SimpleNamespace(
                chat_id=123,
                message=SimpleNamespace(date=datetime.now(UTC), id=8, buttons=[]),
                raw_text="今日未签到",
            )
            for handler in self.handlers[:1]:
                await handler(incoming)
            return SimpleNamespace(id=7, chat_id=123, buttons=[])

    async def run() -> None:
        client = FakeClient()
        gateway = TelethonGateway(client)
        await gateway.send_message("@target_bot", "📅 每日签到")
        assert (await gateway.next_event(0.1)).text == "今日未签到"
        gateway.close()
        assert client.handlers == []

    asyncio.run(run())


def test_gateway_buffers_reply_arriving_during_click() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.handlers: list[Any] = []

        def add_event_handler(self, handler: Any, _: Any) -> None:
            self.handlers.append(handler)

        def remove_event_handler(self, handler: Any, _: Any) -> None:
            self.handlers.remove(handler)

        async def send_message(self, target: str, text: str) -> Any:
            del target, text
            return SimpleNamespace(id=7, chat_id=123, buttons=[])

        async def get_messages(self, target: str, ids: int) -> Any:
            del target, ids

            async def click(*, text: str) -> None:
                assert text == "📝 立即签到"
                incoming = SimpleNamespace(
                    chat_id=123,
                    message=SimpleNamespace(date=datetime.now(UTC), id=8, buttons=[]),
                    raw_text="签到成功！",
                )
                for handler in self.handlers[:1]:
                    await handler(incoming)

            return SimpleNamespace(click=click)

    async def run() -> None:
        client = FakeClient()
        gateway = TelethonGateway(client)
        await gateway.send_message("@target_bot", "📅 每日签到")
        await gateway.click_button(
            Reply(message_id=7, target="@target_bot"),
            Button(text="📝 立即签到", kind="callback"),
        )
        assert (await gateway.next_event(0.1)).text == "签到成功！"
        gateway.close()

    asyncio.run(run())
