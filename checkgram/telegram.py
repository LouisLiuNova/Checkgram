"""Telethon adapter for the workflow engine's small gateway interface."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from telethon import events
from telethon.tl import types

from .workflow import Button, ButtonKind, Reply, WorkflowEvent


class TelethonGateway:
    """Translate short-lived Telethon client operations into workflow events."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.target: str | None = None
        self.target_chat_id: int | None = None
        self._events: asyncio.Queue[Any] = asyncio.Queue(maxsize=128)
        self._listening = False

    async def send_message(self, target: str, text: str) -> Reply:
        self.target = target
        self._start_listening()
        message = await self.client.send_message(target, text)
        self.target_chat_id = getattr(message, "chat_id", None)
        return _reply_from_message(message, target)

    async def next_event(self, timeout: float) -> WorkflowEvent:
        if self.target is None:
            raise RuntimeError("send_message must run before waiting for events")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            raw_event = await asyncio.wait_for(self._events.get(), timeout=remaining)
            normalized = _event_from_telethon(raw_event, self.target, self.target_chat_id)
            if normalized is not None:
                return normalized
        raise TimeoutError

    def close(self) -> None:
        if not self._listening:
            return
        for event_type in (events.NewMessage, events.MessageEdited, events.CallbackQuery):
            self.client.remove_event_handler(self._on_event, event_type)
        self._listening = False

    def _start_listening(self) -> None:
        if self._listening:
            return
        for event_type in (events.NewMessage, events.MessageEdited, events.CallbackQuery):
            self.client.add_event_handler(self._on_event, event_type)
        self._listening = True

    async def _on_event(self, event: Any) -> None:
        if (
            self.target_chat_id is not None
            and getattr(event, "chat_id", None) != self.target_chat_id
        ):
            return
        if self._events.full():
            self._events.get_nowait()
        self._events.put_nowait(event)

    async def click_button(self, reply: Reply, button: Button) -> None:
        if button.kind == "callback":
            message = await self.client.get_messages(reply.target, ids=reply.message_id)
            await message.click(text=button.text)
        else:
            await self.client.send_message(reply.target, button.text)


def _event_from_telethon(
    event: Any, target: str, target_chat_id: int | None
) -> WorkflowEvent | None:
    message = getattr(event, "message", None)
    chat_id = getattr(event, "chat_id", None)
    event_target = target if chat_id == target_chat_id else str(chat_id)
    # The handler only receives live events. Telegram message dates have second
    # precision (and edits can retain the original date), so use receipt time.
    occurred_at = datetime.now(UTC)

    class_name = type(event).__name__
    is_callback = isinstance(event, events.CallbackQuery.Event)
    is_edited = isinstance(event, events.MessageEdited.Event)
    if is_callback or "CallbackQuery" in class_name:
        raw_data = getattr(event, "data", b"")
        text = raw_data.decode(errors="replace") if isinstance(raw_data, bytes) else str(raw_data)
        return WorkflowEvent(
            kind="callback_answer",
            target=event_target,
            occurred_at=occurred_at,
            text=text,
            reply=_reply_from_message(message, event_target) if message is not None else None,
        )

    raw_text = getattr(event, "raw_text", None)
    if raw_text is None and message is not None:
        raw_text = getattr(message, "message", "")
    if raw_text is None:
        return None
    kind: Literal["new_message", "edited_message"] = (
        "edited_message" if is_edited else "new_message"
    )
    return WorkflowEvent(
        kind=kind,
        target=event_target,
        occurred_at=occurred_at,
        text=str(raw_text),
        reply=_reply_from_message(message, event_target) if message is not None else None,
    )


def _reply_from_message(message: Any, target: str) -> Reply:
    return Reply(
        message_id=int(message.id),
        target=target,
        buttons=tuple(
            _button_from_telethon(button) for row in (message.buttons or []) for button in row
        ),
    )


def _button_from_telethon(button: Any) -> Button:
    wrapped = getattr(button, "button", button)
    button_type = getattr(wrapped, "type", None)
    kind: ButtonKind
    if isinstance(button_type, types.InlineButtonTypeCallback):
        kind = "callback"
    elif isinstance(button_type, types.ButtonTypeDefault):
        kind = "reply"
    elif isinstance(button_type, (types.InlineButtonTypeWebView, types.ButtonTypeSimpleWebView)):
        kind = "web_app"
    elif isinstance(
        button_type,
        (
            types.InlineButtonTypeUrl,
            types.InlineButtonTypeUrlAuth,
            types.InlineButtonTypeSwitchInline,
        ),
    ):
        kind = "url"
    elif isinstance(button_type, (types.InlineButtonTypeBuy, types.InlineButtonTypeGame)):
        kind = "payment"
    elif isinstance(button_type, types.ButtonTypeRequestPhone):
        kind = "request_phone"
    elif isinstance(button_type, types.ButtonTypeRequestGeoLocation):
        kind = "request_location"
    else:
        kind = "captcha"
    return Button(
        text=str(getattr(button, "text", "")),
        kind=kind,
        data=getattr(button_type, "data", None) if kind == "callback" else None,
    )
