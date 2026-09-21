from __future__ import annotations

from io import StringIO

from loguru import logger

from checkgram.logging import (
    LOG_FORMAT,
    callback_summary,
    log_event,
    redact_text,
    register_secrets,
    reply_summary,
)


def test_redaction_covers_registered_secrets_phones_and_sensitive_fields() -> None:
    register_secrets(("api-hash-secret", "string-session-secret"))
    value = (
        "api-hash-secret +86138000000000 "
        "api_hash=api-hash-secret StringSession=string-session-secret "
        "callback_data=callback-secret reply=full-sensitive-reply"
    )
    redacted = redact_text(value)
    assert "api-hash-secret" not in redacted
    assert "string-session-secret" not in redacted
    assert "+86138000000000" not in redacted
    assert "callback-secret" not in redacted
    assert "full-sensitive-reply" not in redacted


def test_event_log_has_context_but_not_full_reply_or_callback_data() -> None:
    output = StringIO()
    sink_id = logger.add(output, format=LOG_FORMAT, colorize=False, backtrace=False, diagnose=False)
    try:
        log_event(
            workflow="daily-checkin",
            account="primary",
            attempt="attempt-1",
            step="result",
            action="wait",
            result="unmatched",
            message="step failed",
            reply="this reply must not be logged",
            callback_data=b"callback-secret",
        )
    finally:
        logger.remove(sink_id)
    rendered = output.getvalue()
    assert "workflow=daily-checkin" in rendered
    assert "account=primary" in rendered
    assert "attempt=attempt-1" in rendered
    assert "step=result" in rendered
    assert "action=wait" in rendered
    assert "result=unmatched" in rendered
    assert "this reply must not be logged" not in rendered
    assert "callback-secret" not in rendered
    assert reply_summary("this reply must not be logged") in rendered
    assert callback_summary("callback-secret") in rendered


def test_log_format_forces_color_tags_and_exception_output_is_a_sink() -> None:
    assert "<level>" in LOG_FORMAT
    assert "{exception}" in LOG_FORMAT
