"""Telegram authentication and short-lived client connections."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from .config import AccountConfig
from .errors import AuthError
from .logging import register_secrets

ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True, slots=True)
class ApiCredentials:
    api_id: int
    api_hash: str


def load_api_credentials(environment: Mapping[str, str] | None = None) -> ApiCredentials:
    """Read Telegram API credentials without ever returning them in an error message."""
    values = os.environ if environment is None else environment
    raw_api_id = values.get("TELEGRAM_API_ID", "")
    api_hash = values.get("TELEGRAM_API_HASH", "").strip()
    try:
        api_id = int(raw_api_id)
    except ValueError as exc:
        raise AuthError("TELEGRAM_API_ID must be a positive integer") from exc
    if api_id <= 0:
        raise AuthError("TELEGRAM_API_ID must be a positive integer")
    if not api_hash:
        raise AuthError("TELEGRAM_API_HASH must not be empty")
    return ApiCredentials(api_id=api_id, api_hash=api_hash)


class SessionStore:
    """Atomically persist one Telethon StringSession per configured account."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def path_for(self, account_id: str) -> Path:
        if not ACCOUNT_ID_RE.fullmatch(account_id):
            raise AuthError("account id must be a safe filename component")
        return self.data_dir / f"{account_id}.session"

    def read(self, account_id: str) -> str | None:
        path = self.path_for(account_id)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not value:
            raise AuthError(f"session file is empty for account {account_id!r}")
        register_secrets((value,))
        return value

    def write(self, account_id: str, session: str) -> Path:
        if not session:
            raise AuthError("refusing to save an empty Telegram session")
        register_secrets((session,))
        path = self.path_for(account_id)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.data_dir,
                prefix=f".{account_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(session)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            os.chmod(path, 0o600)
        except OSError as exc:
            raise AuthError(f"cannot save session for account {account_id!r}") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return path


class ClientLike(Protocol):
    session: Any

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_code_request(self, phone: str) -> Any: ...

    async def sign_in(
        self, phone: str | None = None, code: str | None = None, *, password: str | None = None
    ) -> Any: ...

    async def is_user_authorized(self) -> bool: ...


ClientFactory = Callable[[Any, int, str], ClientLike]
SessionParser = Callable[[str], Any]
Prompt = Callable[[str, bool], str]


def default_prompt(label: str, secret: bool) -> str:
    if secret:
        from getpass import getpass

        return getpass(label)
    return input(label)


async def authenticate_account(
    account: AccountConfig,
    credentials: ApiCredentials,
    store: SessionStore,
    *,
    prompt: Prompt = default_prompt,
    client_factory: ClientFactory = TelegramClient,
) -> Path:
    """Interactively authenticate an account and save its StringSession."""
    client = client_factory(StringSession(), credentials.api_id, credentials.api_hash)
    try:
        await client.connect()
        phone = prompt("Telegram phone number: ", False).strip()
        if not phone:
            raise AuthError("phone number must not be empty")
        await client.send_code_request(phone)
        code = prompt("Telegram login code: ", True).strip()
        if not code:
            raise AuthError("Telegram login code must not be empty")
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError as exc:
            password = prompt("Telegram 2FA password: ", True)
            if not password:
                raise AuthError("Telegram 2FA password must not be empty") from exc
            await client.sign_in(password=password)
        if not await client.is_user_authorized():
            raise AuthError("Telegram did not authorize this account")
        session = client.session.save()
        if not isinstance(session, str) or not session:
            raise AuthError("Telegram returned an empty session")
        return store.write(account.id, session)
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Telegram authentication failed: {type(exc).__name__}") from exc
    finally:
        await client.disconnect()


@asynccontextmanager
async def connected_client(
    account: AccountConfig,
    credentials: ApiCredentials,
    store: SessionStore,
    *,
    client_factory: ClientFactory = TelegramClient,
    session_parser: SessionParser = StringSession,
) -> AsyncIterator[ClientLike]:
    """Connect only for the duration of a task and always disconnect afterwards."""
    session = store.read(account.id)
    if session is None:
        raise AuthError(f"account {account.id!r} has no saved session; run auth first")
    client = client_factory(session_parser(session), credentials.api_id, credentials.api_hash)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
