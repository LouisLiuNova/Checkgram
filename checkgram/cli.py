"""Command-line entry point for Checkgram."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from .auth import SessionStore, authenticate_account, load_api_credentials
from .config import load_config
from .errors import AuthError, ConfigError
from .locks import AccountLock, LockBusyError, ServiceLock
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
    auth = subparsers.add_parser("auth", help="authenticate one configured Telegram account")
    auth.add_argument("account_id", help="configured account ID")
    auth.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="configuration path (default: config.toml)",
    )
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
            load_config(args.config)
        except (ConfigError, OSError) as exc:
            print(f"invalid configuration: {exc}", file=sys.stderr)
            return 1
        print(f"configuration is valid: {args.config}")
        return 0
    if args.command == "auth":
        try:
            config = load_config(args.config)
            account = next(
                (item for item in config.accounts if item.id == args.account_id),
                None,
            )
            if account is None:
                raise AuthError(f"unknown account {args.account_id!r}")
            credentials = load_api_credentials()
            with AccountLock(args.data_dir, account.id):
                path = asyncio.run(
                    authenticate_account(account, credentials, SessionStore(args.data_dir))
                )
        except (AuthError, ConfigError, LockBusyError, OSError) as exc:
            print(f"authentication failed: {exc}", file=sys.stderr)
            return 1
        print(f"session saved for account {account.id!r}: {path}")
        return 0
    if args.command in {"run", "serve"}:
        try:
            config = load_config(args.config)
            credentials = load_api_credentials()
            if args.command == "run":
                workflow = next(
                    (item for item in config.workflows if item.id == args.workflow_id), None
                )
                if workflow is None:
                    raise ConfigError("workflow_id", f"unknown workflow {args.workflow_id!r}")
                result = asyncio.run(
                    run_configured_round(config, workflow, args.data_dir, credentials)
                )
                print(
                    f"workflow {workflow.id!r}: {result.outcome.status} "
                    f"({result.outcome.reason}, attempts={result.attempts})"
                )
                return 0 if result.outcome.status == "success" else 1

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
