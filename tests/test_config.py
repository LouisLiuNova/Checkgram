from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from checkgram.config import Config, load_config, parse_config
from checkgram.errors import ConfigError

EXAMPLE = Path(__file__).parents[1] / "config.toml"


def valid_document() -> dict[str, Any]:
    return {
        "app": {"timezone": "Asia/Shanghai", "step_timeout": 30},
        "workflows": [
            {
                "id": "daily-checkin",
                "account": "primary",
                "target": "@target_bot",
                "times": ["08:00"],
                "steps": [
                    {"id": "start", "type": "send", "text": "/start", "next": "result"},
                    {
                        "id": "result",
                        "type": "wait",
                        "cases": [
                            {
                                "id": "ok",
                                "match": "contains",
                                "value": "success",
                                "next": "success",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def assert_invalid(document: dict[str, Any], path: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(path)):
        parse_config(document)


def test_example_config_is_valid() -> None:
    config = load_config(EXAMPLE)
    assert isinstance(config, Config)
    assert config.app.timezone == "Asia/Shanghai"
    assert config.workflows[0].steps[1].cases[0].next == "success"


def test_config_is_typed_and_step_timeout_defaults_from_app() -> None:
    config = parse_config(valid_document())
    assert config.workflows[0].times[0].hour == 8
    assert config.workflows[0].steps[0].timeout == 30


@pytest.mark.parametrize(
    ("mutation", "path"),
    [
        (lambda data: data.update(accounts=[]), "accounts"),
        (lambda data: data["workflows"].append(deepcopy(data["workflows"][0])), "workflows"),
        (lambda data: data["workflows"][0].update(account=""), "workflows[0].account"),
        (lambda data: data["app"].update(timezone="Mars/Colony"), "app.timezone"),
        (lambda data: data["workflows"][0].update(times=["8:00"]), "workflows[0].times[0]"),
        (lambda data: data["app"].update(step_timeout=0), "app.step_timeout"),
        (
            lambda data: data["workflows"][0]["steps"][0].update(type="unknown"),
            "steps[0].type",
        ),
        (
            lambda data: data["workflows"][0]["steps"][0].update(next="missing"),
            "workflows[0].steps[0].next",
        ),
        (
            lambda data: data["workflows"][0]["steps"][0].update(next="start"),
            "workflows[0].steps[0].next",
        ),
        (
            lambda data: data["workflows"][0]["steps"][1]["cases"][0].update(value=""),
            "workflows[0].steps[1].cases[0].value",
        ),
        (
            lambda data: data["workflows"][0]["steps"][1].update(cases=[]),
            "workflows[0].steps[1].cases",
        ),
        (
            lambda data: data["workflows"][0]["steps"][1]["cases"][0].update(match="regex"),
            "workflows[0].steps[1].cases[0].match",
        ),
        (
            lambda data: data["workflows"][0]["steps"][1]["cases"][0].update(next="result"),
            "workflows[0].steps[1].cases[0].next",
        ),
        (
            lambda data: data["workflows"][0]["steps"][0].update(text=""),
            "workflows[0].steps[0].text",
        ),
        (
            lambda data: data["workflows"][0]["steps"][0].update(next=None),
            "workflows[0].steps[0].next",
        ),
        (
            lambda data: data["workflows"][0]["steps"][0].update(button_match="contains"),
            "workflows[0].steps[0].button_match",
        ),
        (
            lambda data: data["workflows"][0]["steps"][0].update(timeout_next="success"),
            "workflows[0].steps[0].timeout_next",
        ),
    ],
)
def test_invalid_documents_are_rejected(
    mutation: Callable[[dict[str, Any]], None], path: str
) -> None:
    document = valid_document()
    mutation(document)
    assert_invalid(document, path)


def test_duplicate_step_and_case_ids_are_rejected() -> None:
    document = valid_document()
    document["workflows"][0]["steps"].append(
        {
            "id": "result",
            "type": "wait",
            "cases": [{"id": "ok", "match": "exact", "value": "x", "next": "success"}],
        }
    )
    assert_invalid(document, "workflows[0].steps")


def test_empty_workflow_and_empty_cases_are_rejected() -> None:
    document = valid_document()
    document["workflows"][0]["steps"] = []
    assert_invalid(document, "workflows[0].steps")


def test_duplicate_case_ids_and_steps_without_exit_are_rejected() -> None:
    duplicate_cases = valid_document()
    duplicate_cases["workflows"][0]["steps"][1]["cases"].append(
        {"id": "ok", "match": "exact", "value": "again", "next": "success"}
    )
    assert_invalid(duplicate_cases, "workflows[0].steps[1].cases")

    no_exit = valid_document()
    no_exit["workflows"][0]["steps"][0].pop("next")
    assert_invalid(no_exit, "workflows[0].steps[0]")


def test_parse_config_does_not_import_or_connect_telethon() -> None:
    import checkgram.config as config_module

    config = parse_config(valid_document())
    assert config.workflows[0].id == "daily-checkin"
    assert not hasattr(config_module, "TelegramClient")


def test_click_button_match_and_wait_timeout_next_are_validated() -> None:
    document = valid_document()
    steps = document["workflows"][0]["steps"]
    steps[1]["timeout_next"] = "success"
    steps.append(
        {
            "id": "click",
            "type": "click",
            "text": "立即签到",
            "button_match": "contains",
            "cases": [{"id": "done", "match": "contains", "value": "成功", "next": "success"}],
        }
    )
    config = parse_config(document)
    assert config.workflows[0].steps[1].timeout_next == "success"
    assert config.workflows[0].steps[2].button_match == "contains"

    steps[2]["button_match"] = "prefix"
    assert_invalid(document, "workflows[0].steps[2].button_match")
