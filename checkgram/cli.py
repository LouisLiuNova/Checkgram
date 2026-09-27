"""Command-line entry point for Checkgram."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from .auth import (
    SessionStore,
    authenticate_account,
    load_api_credentials,
    require_sessions,
)
from .config import load_config
from .errors import AuthError, ConfigError
from .locks import AccountLock, LockBusyError, ServiceLock
from .logging import configure_logging
from .runtime import run_configured_round
from .scheduler import SchedulerError, serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="checkgram", description="Telegram workflow runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate a TOML configuration offline")
    validate.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="configuration path (default: config.toml)",
    )
    validate.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="also verify referenced sessions in this directory",
    )
    auth = subparsers.add_parser("auth", help="authenticate one Telegram account")
    auth.add_argument("account_id", help="local account ID")
    auth.add_argument(
        "--data-dir",
        type=Path,
        default=Path("/data"),
        help="session and lock directory (default: /data)",
    )
    run = subparsers.add_parser("run", help="run one configured workflow now")
    run.add_argument("workflow_id", help="configured workflow ID")
    run.add_argument("--config", type=Path, default=Path("config.toml"))
    run.add_argument("--data-dir", type=Path, default=Path("/data"))
    serve = subparsers.add_parser("serve", help="wait for and run scheduled workflows")
    serve.add_argument("--config", type=Path, default=Path("config.toml"))
    serve.add_argument("--data-dir", type=Path, default=Path("/data"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        try:
            config = load_config(args.config)
            if args.data_dir is not None:
                require_sessions(
                    [workflow.account_id for workflow in config.workflows], args.data_dir
                )
        except (AuthError, ConfigError, OSError) as exc:
            print(f"invalid configuration: {exc}", file=sys.stderr)
            return 1
        suffix = " and referenced sessions are present" if args.data_dir is not None else ""
        print(f"configuration is valid{suffix}: {args.config}")
        return 0
    if args.command == "auth":
        try:
            SessionStore(args.data_dir).path_for(args.account_id)
            credentials = load_api_credentials()
            configure_logging((credentials.api_hash,))
            identity: list[str] = []
            with AccountLock(args.data_dir, args.account_id):
                session_path = asyncio.run(
                    authenticate_account(
                        args.account_id,
                        credentials,
                        SessionStore(args.data_dir),
                        identity_sink=identity.append,
                    )
                )
        except (AuthError, ConfigError, LockBusyError, OSError) as exc:
            print(f"authentication failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"authenticated Telegram identity: {identity[0]}; "
            f"session saved for account {args.account_id!r}: {session_path}"
        )
        return 0
    if args.command in {"run", "serve"}:
        try:
            config = load_config(args.config)
            if args.command == "run":
                workflow = next(
                    (item for item in config.workflows if item.id == args.workflow_id), None
                )
                if workflow is None:
                    raise ConfigError("workflow_id", f"unknown workflow {args.workflow_id!r}")
                selected_workflow = workflow
                require_sessions([selected_workflow.account_id], args.data_dir)
            else:
                require_sessions(
                    [workflow.account_id for workflow in config.workflows], args.data_dir
                )
            credentials = load_api_credentials()
            configure_logging((credentials.api_hash,))
            if args.command == "run":
                round_result = asyncio.run(
                    run_configured_round(config, selected_workflow, args.data_dir, credentials)
                )
                print(
                    f"workflow {selected_workflow.id!r}: {round_result.outcome.status} "
                    f"({round_result.outcome.reason}, attempts={round_result.attempts})"
                )
                return 0 if round_result.outcome.status == "success" else 1

            with ServiceLock(args.data_dir):
                asyncio.run(
                    serve(
                        config,
                        lambda workflow: (
                            lambda: run_configured_round(
                                config, workflow, args.data_dir, credentials
                            )
                        ),
                        clock=lambda: datetime.now(UTC),
                    )
                )
            return 0
        except KeyboardInterrupt:
            return 0
        except (AuthError, ConfigError, LockBusyError, SchedulerError, OSError) as exc:
            print(f"command failed: {exc}", file=sys.stderr)
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
