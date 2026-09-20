from __future__ import annotations

from pathlib import Path

from checkgram.cli import main


def test_validate_command_accepts_example() -> None:
    example = Path(__file__).parents[1] / "examples" / "config.example.toml"
    assert main(["validate", "--config", str(example)]) == 0


def test_validate_command_returns_nonzero_for_invalid_file(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[app]\ntimezone = 'Mars/Colony'\nstep_timeout = 30\n", encoding="utf-8")
    assert main(["validate", "--config", str(invalid)]) == 1
