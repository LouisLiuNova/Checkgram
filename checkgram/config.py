"""Typed TOML configuration and offline validation for Checkgram."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
STEP_TYPES = frozenset({"send", "wait", "click"})
MATCH_TYPES = frozenset({"exact", "contains"})
TERMINAL_TARGETS = frozenset({"success", "failure"})


@dataclass(frozen=True, slots=True)
class AppConfig:
    timezone: str
    step_timeout: int


@dataclass(frozen=True, slots=True)
class CaseConfig:
    id: str
    match: str
    value: str
    next: str


@dataclass(frozen=True, slots=True)
class StepConfig:
    id: str
    type: str
    text: str | None
    button_match: str
    timeout: int
    next: str | None
    timeout_next: str | None
    cases: tuple[CaseConfig, ...]


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    id: str
    account_id: str
    target: str
    times: tuple[time, ...]
    steps: tuple[StepConfig, ...]


@dataclass(frozen=True, slots=True)
class Config:
    app: AppConfig
    workflows: tuple[WorkflowConfig, ...]


def load_config(path: Path) -> Config:
    """Load and validate one TOML file without opening any network connection."""
    try:
        with path.open("rb") as config_file:
            document = tomllib.load(config_file)
    except FileNotFoundError as exc:
        raise ConfigError("config", f"file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("config", f"invalid TOML: {exc}") from exc
    return parse_config(document)


def parse_config(document: Mapping[str, Any]) -> Config:
    """Parse a TOML document and return an immutable, validated model."""
    app_table = _table(document, "app", "app")
    timezone = _string(app_table, "timezone", "app.timezone")
    _validate_timezone(timezone, "app.timezone")
    step_timeout = _positive_int(app_table, "step_timeout", "app.step_timeout")
    app = AppConfig(timezone=timezone, step_timeout=step_timeout)

    if "accounts" in document:
        _fail("accounts", "is no longer supported; run auth ACCOUNT_ID to create an account")

    workflows_raw = _array(document, "workflows", "workflows")
    workflows = tuple(
        _parse_workflow(item, index, app.step_timeout) for index, item in enumerate(workflows_raw)
    )
    _ensure_unique((workflow.id for workflow in workflows), "workflows")
    for index, workflow in enumerate(workflows):
        path = f"workflows[{index}].account"
        if not ACCOUNT_ID_RE.fullmatch(workflow.account_id):
            _fail(path, "must be a safe account ID (letters, numbers, ., _, - only)")
    return Config(app=app, workflows=workflows)


def _parse_workflow(raw: Any, index: int, default_timeout: int) -> WorkflowConfig:
    path = f"workflows[{index}]"
    table = _table_value(raw, path)
    workflow_id = _non_empty_string(table, "id", f"{path}.id")
    account_id = _non_empty_string(table, "account", f"{path}.account")
    target = _non_empty_string(table, "target", f"{path}.target")
    raw_times = _array(table, "times", f"{path}.times")
    times = tuple(
        _parse_time(value, f"{path}.times[{time_index}]")
        for time_index, value in enumerate(raw_times)
    )
    if not times:
        _fail(f"{path}.times", "must contain at least one time")

    raw_steps = _array(table, "steps", f"{path}.steps")
    steps = tuple(
        _parse_step(item, step_index, default_timeout, path)
        for step_index, item in enumerate(raw_steps)
    )
    _validate_workflow_steps(steps, path)
    return WorkflowConfig(
        id=workflow_id,
        account_id=account_id,
        target=target,
        times=times,
        steps=steps,
    )


def _parse_step(raw: Any, index: int, default_timeout: int, workflow_path: str) -> StepConfig:
    path = f"{workflow_path}.steps[{index}]"
    table = _table_value(raw, path)
    step_id = _non_empty_string(table, "id", f"{path}.id")
    step_type = _string(table, "type", f"{path}.type")
    if step_type not in STEP_TYPES:
        _fail(f"{path}.type", f"must be one of {', '.join(sorted(STEP_TYPES))}")
    timeout = (
        _positive_int(table, "timeout", f"{path}.timeout")
        if "timeout" in table
        else default_timeout
    )
    text = None
    if "text" in table:
        text = _non_empty_string(table, "text", f"{path}.text")
    if step_type == "send" and text is None:
        _fail(f"{path}.text", "is required for send steps")
    if step_type == "click" and text is None:
        _fail(f"{path}.text", "is required for click steps")
    button_match = "exact"
    if "button_match" in table:
        if step_type != "click":
            _fail(f"{path}.button_match", "is only supported for click steps")
        button_match = _string(table, "button_match", f"{path}.button_match")
        if button_match not in MATCH_TYPES:
            _fail(f"{path}.button_match", "must be exact or contains")

    next_target = None
    if "next" in table:
        next_target = _non_empty_string(table, "next", f"{path}.next")
    timeout_next = None
    if "timeout_next" in table:
        if step_type != "wait":
            _fail(f"{path}.timeout_next", "is only supported for wait steps")
        timeout_next = _non_empty_string(table, "timeout_next", f"{path}.timeout_next")

    raw_cases = table.get("cases", [])
    cases_raw = _array_value(raw_cases, f"{path}.cases")
    cases = tuple(_parse_case(item, case_index, path) for case_index, item in enumerate(cases_raw))
    if step_type in {"wait", "click"} and not cases:
        _fail(f"{path}.cases", f"must contain at least one case for {step_type} steps")
    if step_type == "send" and cases:
        _fail(f"{path}.cases", "send steps cannot define cases")
    return StepConfig(
        id=step_id,
        type=step_type,
        text=text,
        button_match=button_match,
        timeout=timeout,
        next=next_target,
        timeout_next=timeout_next,
        cases=cases,
    )


def _parse_case(raw: Any, index: int, step_path: str) -> CaseConfig:
    path = f"{step_path}.cases[{index}]"
    table = _table_value(raw, path)
    case_id = _non_empty_string(table, "id", f"{path}.id")
    match = _string(table, "match", f"{path}.match")
    if match not in MATCH_TYPES:
        _fail(f"{path}.match", f"must be one of {', '.join(sorted(MATCH_TYPES))}")
    value = _non_empty_string(table, "value", f"{path}.value")
    next_target = _non_empty_string(table, "next", f"{path}.next")
    return CaseConfig(id=case_id, match=match, value=value, next=next_target)


def _validate_workflow_steps(steps: tuple[StepConfig, ...], workflow_path: str) -> None:
    if not steps:
        _fail(f"{workflow_path}.steps", "must contain at least one step")
    _ensure_unique((step.id for step in steps), f"{workflow_path}.steps")
    step_indexes = {step.id: index for index, step in enumerate(steps)}
    for step_index, step in enumerate(steps):
        step_path = f"{workflow_path}.steps[{step_index}]"
        targets: list[tuple[str, str]] = []
        if step.next is not None:
            targets.append(("next", step.next))
        if step.timeout_next is not None:
            targets.append(("timeout_next", step.timeout_next))
        targets.extend(
            (f"cases[{case_index}].next", case.next) for case_index, case in enumerate(step.cases)
        )
        if not targets:
            _fail(step_path, "must have an exit through next, a case, success, or failure")
        case_ids = [case.id for case in step.cases]
        _ensure_unique(case_ids, f"{step_path}.cases")
        for target_path, target in targets:
            if target in TERMINAL_TARGETS:
                continue
            if target not in step_indexes:
                _fail(f"{step_path}.{target_path}", f"unknown step {target!r}")
            if step_indexes[target] <= step_index:
                _fail(f"{step_path}.{target_path}", "must point only to a later step")
    _assert_acyclic(steps, step_indexes, workflow_path)


def _assert_acyclic(
    steps: tuple[StepConfig, ...], step_indexes: Mapping[str, int], workflow_path: str
) -> None:
    graph: dict[str, tuple[str, ...]] = {}
    for step in steps:
        targets = [
            target
            for target in (step.next, step.timeout_next, *(case.next for case in step.cases))
            if target
        ]
        graph[step.id] = tuple(target for target in targets if target in step_indexes)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            _fail(f"{workflow_path}.steps", f"contains a cycle at {step_id!r}")
        if step_id in visited:
            return
        visiting.add(step_id)
        for target in graph[step_id]:
            visit(target)
        visiting.remove(step_id)
        visited.add(step_id)

    for step in steps:
        visit(step.id)


def _parse_time(value: Any, path: str) -> time:
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        _fail(path, "must use strict HH:MM format")
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


def _validate_timezone(value: str, path: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        _fail(path, "must be a valid IANA timezone")
        raise AssertionError("unreachable") from exc


def _table(document: Mapping[str, Any], key: str, path: str) -> Mapping[str, Any]:
    if key not in document:
        _fail(path, "is required")
    return _table_value(document[key], path)


def _table_value(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be a table")
    return cast(Mapping[str, Any], MappingProxyType(value))


def _array(document: Mapping[str, Any], key: str, path: str) -> list[Any]:
    if key not in document:
        _fail(path, "is required")
    return _array_value(document[key], path)


def _array_value(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    return value


def _string(document: Mapping[str, Any], key: str, path: str) -> str:
    if key not in document or not isinstance(document[key], str):
        _fail(path, "must be a string")
    return cast(str, document[key])


def _non_empty_string(document: Mapping[str, Any], key: str, path: str) -> str:
    value = _string(document, key, path).strip()
    if not value:
        _fail(path, "must not be empty")
    return value


def _positive_int(document: Mapping[str, Any], key: str, path: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(path, "must be a positive integer")
    return value


def _ensure_unique(values: Any, path: str) -> None:
    seen: set[str] = set()
    for index, value in enumerate(values):
        if value in seen:
            _fail(path, f"duplicate id {value!r} at index {index}")
        seen.add(value)


def _fail(path: str, message: str) -> NoReturn:
    raise ConfigError(path, message)
