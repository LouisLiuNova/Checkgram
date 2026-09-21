from __future__ import annotations

from pathlib import Path

import pytest

from checkgram.cli import main


def test_validate_command_accepts_example() -> None:
    example = Path(__file__).parents[1] / "config.toml"
    assert main(["validate", "--config", str(example)]) == 0


def test_validate_command_returns_nonzero_for_invalid_file(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[app]\ntimezone = 'Mars/Colony'\nstep_timeout = 30\n", encoding="utf-8")
    assert main(["validate", "--config", str(invalid)]) == 1


def test_validate_with_data_dir_checks_referenced_sessions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[app]
timezone = "Asia/Shanghai"
step_timeout = 30

[[workflows]]
id = "daily"
account = "primary"
target = "@target_bot"
times = ["08:00"]

[[workflows.steps]]
id = "send"
type = "send"
text = "/start"
next = "success"
""",
        encoding="utf-8",
    )
    assert main(["validate", "--config", str(config), "--data-dir", str(tmp_path)]) == 1
    assert "auth primary" in str(capsys.readouterr().err)
