"""Single-line, colored and secret-safe operational logging."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from hashlib import sha256
from typing import Any, TextIO

from loguru import logger

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | "
    "workflow={extra[workflow]} account={extra[account]} "
    "attempt={extra[attempt]} step={extra[step]} action={extra[action]} "
    "result={extra[result]} | {message}\n{exception}"
)
REDACTED = "[REDACTED]"
_PHONE_RE = re.compile(r"(?<!\w)\+?[0-9][0-9 ()-]{7,}[0-9](?!\w)")
_KEY_VALUE_RE = re.compile(
    r"(?i)(\b(?:api[_ -]?hash|string[_ -]?session|callback[_ -]?data|phone|reply)\b\s*[:=]\s*)"
    r"([^,;\s]+)"
)

_registered_secrets: set[str] = set()


def register_secrets(values: Iterable[str]) -> None:
    """Register non-empty runtime secrets for redaction in every configured sink."""
    _registered_secrets.update(value for value in values if value)


def redact_text(value: str) -> str:
    """Redact registered secrets, phone-like values and sensitive key/value fields."""
    redacted = value
    for secret in sorted(_registered_secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED)
    redacted = _PHONE_RE.sub(REDACTED, redacted)
    return _KEY_VALUE_RE.sub(rf"\1{REDACTED}", redacted)


def reply_summary(reply: str) -> str:
    """Return metadata for a reply without retaining any reply text."""
    digest = sha256(reply.encode("utf-8")).hexdigest()[:12]
    return f"<reply length={len(reply)} sha256={digest}>"


def callback_summary(data: bytes | str) -> str:
    """Return metadata for callback data without exposing its content."""
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    digest = sha256(raw).hexdigest()[:12]
    return f"<callback length={len(raw)} sha256={digest}>"


def _sink(message: Any, output: TextIO = sys.stdout) -> None:
    output.write(redact_text(str(message)))
    output.flush()


def _patch_record(record: Any) -> None:
    defaults = {
        "workflow": "-",
        "account": "-",
        "attempt": "-",
        "step": "-",
        "action": "-",
        "result": "-",
    }
    for key, value in defaults.items():
        record["extra"].setdefault(key, value)
    record["message"] = redact_text(record["message"])


def configure_logging(secret_values: Iterable[str] = ()) -> None:
    """Configure one forced-color stdout sink; file sinks are intentionally absent."""
    register_secrets(secret_values)
    logger.configure(patcher=_patch_record)
    logger.remove()
    logger.add(
        _sink,
        format=LOG_FORMAT,
        colorize=True,
        backtrace=False,
        diagnose=False,
    )


def log_event(
    *,
    level: str = "INFO",
    workflow: str,
    account: str,
    attempt: str,
    step: str,
    action: str,
    result: str,
    message: str,
    reply: str | None = None,
    callback_data: bytes | str | None = None,
) -> None:
    """Emit structured context while reducing sensitive values to metadata."""
    details: list[str] = [message]
    if reply is not None:
        details.append(reply_summary(reply))
    if callback_data is not None:
        details.append(callback_summary(callback_data))
    logger.bind(
        workflow=workflow,
        account=account,
        attempt=attempt,
        step=step,
        action=action,
        result=result,
    ).log(level, " ".join(details))
