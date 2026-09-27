"""Filesystem locks used to serialize Checkgram processes and accounts."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType

from .errors import AuthError


class LockBusyError(RuntimeError):
    """Raised when a non-blocking lock is already held."""


class FileLock:
    """A process-wide advisory lock backed by a mode-0600 file."""

    def __init__(self, path: Path, *, blocking: bool) -> None:
        self.path = path
        self.blocking = blocking
        self._file: object | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        file = self.path.open("a+")
        os.fchmod(file.fileno(), 0o600)
        flags = fcntl.LOCK_EX
        if not self.blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(file.fileno(), flags)
        except BlockingIOError as exc:
            file.close()
            raise LockBusyError(f"lock is already held: {self.path.name}") from exc
        self._file = file
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        file = self._file
        if file is None:
            return
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            file.close()  # type: ignore[attr-defined]
            self._file = None


class ServiceLock(FileLock):
    """A non-blocking lock allowing only one scheduler process."""

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir / "service.lock", blocking=False)


class AccountLock(FileLock):
    """A blocking lock that serializes work for one configured account."""

    def __init__(self, data_dir: Path, account_id: str) -> None:
        if not account_id or account_id in {".", ".."} or Path(account_id).name != account_id:
            raise AuthError("account id cannot be used as a lock filename")
        super().__init__(data_dir / f"account-{account_id}.lock", blocking=True)
