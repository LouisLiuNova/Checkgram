"""Runtime composition for configured workflows and authenticated accounts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .auth import ApiCredentials, SessionStore, connected_client
from .config import Config, WorkflowConfig
from .locks import AccountLock
from .logging import register_secrets
from .scheduler import RoundResult, run_round
from .telegram import TelethonGateway
from .workflow import WorkflowOutcome, run_workflow


def account_for(config: Config, workflow: WorkflowConfig) -> str:
    del config
    return workflow.account_id


async def run_configured_attempt(
    config: Config,
    workflow: WorkflowConfig,
    data_dir: Path,
    credentials: ApiCredentials,
    attempt_number: int,
    deadline: float,
) -> WorkflowOutcome:
    """Run one authenticated workflow attempt within an existing deadline."""
    del attempt_number
    register_secrets((credentials.api_hash,))
    account_id = account_for(config, workflow)
    store = SessionStore(data_dir)
    attempt_id = uuid4().hex
    async with connected_client(account_id, credentials, store) as client:
        return await run_workflow(
            workflow,
            TelethonGateway(client),
            attempt_id=attempt_id,
            attempt_started_at=datetime.now(UTC),
            deadline=deadline,
            account_alias=account_id,
        )


async def run_configured_round(
    config: Config,
    workflow: WorkflowConfig,
    data_dir: Path,
    credentials: ApiCredentials,
    *,
    monotonic_clock: Callable[[], float] = monotonic,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> RoundResult:
    """Run one workflow round while holding its account lock."""

    async def attempt(attempt_number: int, deadline: float) -> WorkflowOutcome:
        return await run_configured_attempt(
            config, workflow, data_dir, credentials, attempt_number, deadline
        )

    account_id = account_for(config, workflow)
    with AccountLock(data_dir, account_id):
        if sleep is None:
            return await run_round(attempt, clock=monotonic_clock)
        return await run_round(attempt, clock=monotonic_clock, sleep=sleep)
