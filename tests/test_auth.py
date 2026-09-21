from __future__ import annotations

import asyncio
import stat
import threading
import time
from pathlib import Path

import pytest
from telethon.errors import SessionPasswordNeededError

from checkgram.auth import (
    ApiCredentials,
    SessionStore,
    authenticate_account,
    connected_client,
    load_api_credentials,
    require_sessions,
)
from checkgram.errors import AuthError
from checkgram.locks import AccountLock, LockBusyError, ServiceLock


class FakeSession:
    def __init__(self, value: str = "saved-session") -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class FakeClient:
    def __init__(self, *, require_password: bool = False) -> None:
        self.session = FakeSession()
        self.require_password = require_password
        self.connected = False
        self.disconnected = False
        self.sign_ins: list[tuple[object, ...]] = []

    async def get_me(self) -> object:
        return type(
            "User", (), {"username": "primary_user", "phone": "13800000000", "id": 123456}
        )()

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send_code_request(self, phone: str) -> None:
        assert phone == "+86138000000000"

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        password: str | None = None,
    ) -> None:
        self.sign_ins.append((phone, code, password))
        if self.require_password and password is None:
            raise SessionPasswordNeededError(None)

    async def is_user_authorized(self) -> bool:
        return True


def test_session_store_writes_atomically_with_restricted_permissions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "data")
    path = store.write("primary", "secret-session")
    assert store.read("primary") == "secret-session"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_session_store_rejects_path_traversal_and_empty_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    with pytest.raises(AuthError):
        store.path_for("../escape")
    with pytest.raises(AuthError):
        store.write("primary", "")


def test_credentials_are_validated_without_echoing_secrets() -> None:
    credentials = load_api_credentials(
        {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "api-secret"}
    )
    assert credentials == ApiCredentials(api_id=12345, api_hash="api-secret")
    with pytest.raises(AuthError, match="positive integer"):
        load_api_credentials({"TELEGRAM_API_ID": "not-an-id", "TELEGRAM_API_HASH": "secret"})


def test_service_lock_is_non_blocking_and_account_lock_waits(tmp_path: Path) -> None:
    with ServiceLock(tmp_path):
        with pytest.raises(LockBusyError):
            with ServiceLock(tmp_path):
                pass

    acquired = threading.Event()
    release = threading.Event()

    def wait_for_account_lock() -> None:
        with AccountLock(tmp_path, "primary"):
            acquired.set()
            release.wait(timeout=2)

    with AccountLock(tmp_path, "primary"):
        thread = threading.Thread(target=wait_for_account_lock)
        thread.start()
        time.sleep(0.05)
        assert not acquired.is_set()
        release.set()
    thread.join(timeout=2)
    assert acquired.is_set()


def test_authentication_reads_interactive_values_and_disconnects(tmp_path: Path) -> None:
    client = FakeClient(require_password=True)
    prompts = iter(["+86138000000000", "123456", "two-factor-secret"])
    identity: list[str] = []

    def prompt(_: str, __: bool) -> str:
        return next(prompts)

    async def run() -> Path:
        return await authenticate_account(
            "primary",
            ApiCredentials(api_id=12345, api_hash="api-secret"),
            SessionStore(tmp_path),
            prompt=prompt,
            client_factory=lambda *_: client,
            identity_sink=identity.append,
        )

    path = asyncio.run(run())
    assert path.name == "primary.session"
    assert identity == ["@primary_user, phone ending 00, ID ending 3456"]
    assert client.connected and client.disconnected
    assert SessionStore(tmp_path).read("primary") == "saved-session"
    assert client.sign_ins[-1] == (None, None, "two-factor-secret")


def test_connected_client_always_disconnects(tmp_path: Path) -> None:
    client = FakeClient()
    SessionStore(tmp_path).write("primary", "saved-session")

    async def run() -> None:
        async with connected_client(
            "primary",
            ApiCredentials(api_id=12345, api_hash="api-secret"),
            SessionStore(tmp_path),
            client_factory=lambda *_: client,
            session_parser=lambda _: object(),
        ) as connected:
            assert connected is client
            assert client.connected

    asyncio.run(run())
    assert client.disconnected


def test_authentication_requires_explicit_confirmation_before_overwrite(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.write("primary", "old-session")
    prompts = iter(["no"])

    def prompt(_: str, __: bool) -> str:
        return next(prompts)

    async def run() -> None:
        await authenticate_account(
            "primary",
            ApiCredentials(api_id=12345, api_hash="api-secret"),
            store,
            prompt=prompt,
            client_factory=lambda *_: FakeClient(),
        )

    with pytest.raises(AuthError, match="not overwritten"):
        asyncio.run(run())
    assert store.read("primary") == "old-session"


def test_require_sessions_reports_each_missing_account(tmp_path: Path) -> None:
    SessionStore(tmp_path).write("primary", "saved-session")
    with pytest.raises(AuthError, match="auth secondary"):
        require_sessions(["primary", "secondary"], tmp_path)
