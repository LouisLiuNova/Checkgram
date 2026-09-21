"""Telegram authentication and short-lived client connections."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from .config import ACCOUNT_ID_RE
from .errors import AuthError
from .logging import register_secrets


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
    """Atomically persist one Telethon StringSession per local account alias."""

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
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.data_dir, 0o700)
        except OSError as exc:
            raise AuthError(f"cannot prepare session directory: {self.data_dir}") from exc
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

    async def get_me(self) -> Any: ...


ClientFactory = Callable[[Any, int, str], ClientLike]
SessionParser = Callable[[str], Any]
Prompt = Callable[[str, bool], str]
IdentitySink = Callable[[str], None]


def default_prompt(label: str, secret: bool) -> str:
    if secret:
        from getpass import getpass

        return getpass(label)
    return input(label)


async def authenticate_account(
    account_id: str,
    credentials: ApiCredentials,
    store: SessionStore,
    *,
    prompt: Prompt = default_prompt,
    client_factory: ClientFactory = TelegramClient,
    identity_sink: IdentitySink | None = None,
) -> Path:
    """Interactively authenticate one account and save its StringSession."""
    store.path_for(account_id)
    if store.read(account_id) is not None:
        confirmation = (
            prompt(
                f"Session for account {account_id!r} exists; overwrite it? Type 'yes' to confirm: ",
                False,
            )
            .strip()
            .lower()
        )
        if confirmation != "yes":
            raise AuthError("authentication cancelled; existing session was not overwritten")

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
        identity = format_telegram_identity(await client.get_me())
        session = client.session.save()
        if not isinstance(session, str) or not session:
            raise AuthError("Telegram returned an empty session")
        path = store.write(account_id, session)
        if identity_sink is not None:
            identity_sink(identity)
        return path
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Telegram authentication failed: {type(exc).__name__}") from exc
    finally:
        await client.disconnect()


@asynccontextmanager
async def connected_client(
    account_id: str,
    credentials: ApiCredentials,
    store: SessionStore,
    *,
    client_factory: ClientFactory = TelegramClient,
    session_parser: SessionParser = StringSession,
) -> AsyncIterator[ClientLike]:
    """Connect only for the duration of a task and always disconnect afterwards."""
    session = store.read(account_id)
    if session is None:
        raise AuthError(f"account {account_id!r} has no saved session; run auth first")
    client = client_factory(session_parser(session), credentials.api_id, credentials.api_hash)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


def format_telegram_identity(user: Any) -> str:
    """Return a confirmation label without exposing a full phone number or ID."""
    if user is None:
        raise AuthError("Telegram returned no identity after authentication")
    username = getattr(user, "username", None)
    user_id = getattr(user, "id", None)
    phone = getattr(user, "phone", None)
    parts: list[str] = []
    if isinstance(username, str) and username:
        parts.append(f"@{username}")
    if phone:
        phone_text = str(phone)
        parts.append(f"phone ending {phone_text[-2:]}")
    if user_id is not None:
        id_text = str(user_id)
        parts.append(f"ID ending {id_text[-4:]}")
    if not parts:
        raise AuthError("Telegram identity has no displayable fields")
    return ", ".join(parts)


def require_sessions(account_ids: list[str] | tuple[str, ...], data_dir: Path) -> None:
    """Fail before execution when any referenced account has no usable session."""
    store = SessionStore(data_dir)
    missing: list[str] = []
    for account_id in dict.fromkeys(account_ids):
        if store.read(account_id) is None:
            missing.append(account_id)
    if missing:
        commands = ", ".join(f"auth {account_id}" for account_id in missing)
        accounts = ", ".join(repr(account_id) for account_id in missing)
        raise AuthError(f"missing session for account(s) {accounts}; run {commands}")
