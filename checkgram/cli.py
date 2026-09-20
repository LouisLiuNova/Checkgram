"""Command-line entry point for Checkgram."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .errors import ConfigError


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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
