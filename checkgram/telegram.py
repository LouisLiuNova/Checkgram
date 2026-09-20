"""Telethon adapter for the workflow engine's small gateway interface."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from telethon import events

from .workflow import Button, ButtonKind, Reply, WorkflowEvent


class TelethonGateway:
    """Translate short-lived Telethon client operations into workflow events."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.target: str | None = None
        self.target_chat_id: int | None = None

    async def send_message(self, target: str, text: str) -> Reply:
        message = await self.client.send_message(target, text)
        self.target = target
        self.target_chat_id = getattr(message, "chat_id", None)
        return _reply_from_message(message, target)

    async def next_event(self, timeout: float) -> WorkflowEvent:
        if self.target is None:
            raise RuntimeError("send_message must run before waiting for events")
        current_target = self.target
        loop = asyncio.get_running_loop()
        future: asyncio.Future[WorkflowEvent] = loop.create_future()

        async def handler(event: Any) -> None:
            normalized = _event_from_telethon(event, current_target, self.target_chat_id)
            if normalized is not None and not future.done():
                future.set_result(normalized)

        event_types = (events.NewMessage, events.MessageEdited, events.CallbackQuery)
        for event_type in event_types:
            self.client.add_event_handler(handler, event_type)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            for event_type in event_types:
                self.client.remove_event_handler(handler, event_type)

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
    occurred_at = getattr(message, "date", None) or datetime.now(UTC)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

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
    class_name = type(button).__name__
    kind: ButtonKind
    if "Callback" in class_name:
        kind = "callback"
    elif "Text" in class_name:
        kind = "reply"
    elif "WebView" in class_name or "WebApp" in class_name:
        kind = "web_app"
    elif "Url" in class_name or "SwitchInline" in class_name:
        kind = "url"
    elif "Buy" in class_name or "Game" in class_name:
        kind = "payment"
    elif "RequestPhone" in class_name:
        kind = "request_phone"
    elif "RequestGeo" in class_name:
        kind = "request_location"
    elif "KeyboardButton" in class_name or "ButtonText" in class_name:
        kind = "reply"
    else:
        kind = "captcha"
    return Button(
        text=str(getattr(button, "text", "")), kind=kind, data=getattr(button, "data", None)
    )
