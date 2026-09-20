"""Command-line entry point for Checkgram."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .auth import SessionStore, authenticate_account, load_api_credentials
from .config import load_config
from .errors import AuthError, ConfigError
from .locks import AccountLock


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
        except (AuthError, ConfigError, OSError) as exc:
            print(f"authentication failed: {exc}", file=sys.stderr)
            return 1
        print(f"session saved for account {account.id!r}: {path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
