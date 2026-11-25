"""Unit tests for workflow definition validation (no services needed)."""

from typing import Any

import pytest
from pydantic import ValidationError

from flowforge.schemas.workflow_definition import (
    MAX_DELAY_SECONDS,
    MAX_HTTP_TIMEOUT_SECONDS,
    MAX_STEPS,
    WorkflowDefinition,
    check_http_target,
)


def http_step(name: str = "fetch", **config: Any) -> dict[str, Any]:
    return {"name": name, "type": "http", "config": {"url": "https://example.com/api", **config}}


def delay_step(name: str = "wait", seconds: Any = 1) -> dict[str, Any]:
    return {"name": name, "type": "delay", "config": {"seconds": seconds}}


def error_types(definition: Any) -> list[str]:
    with pytest.raises(ValidationError) as excinfo:
        WorkflowDefinition.model_validate(definition)
    return [error["type"] for error in excinfo.value.errors()]


# --- valid definitions ---------------------------------------------------------------


def test_valid_definition_is_normalized_with_defaults() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "steps": [
                http_step(method="post", headers={"X-Request-Id": "abc"}, body={"order": 7}),
                delay_step(seconds=2.5),
                {"name": "note", "type": "demo"},
            ]
        }
    )

    assert definition.model_dump(mode="json") == {
        "steps": [
            {
                "name": "fetch",
                "type": "http",
                "config": {
                    "url": "https://example.com/api",
                    "method": "POST",
                    "headers": {"X-Request-Id": "abc"},
                    "body": {"order": 7},
                    "timeout_seconds": 10.0,
                },
            },
            {"name": "wait", "type": "delay", "config": {"seconds": 2.5}},
            {"name": "note", "type": "demo", "config": {"message": None}},
        ]
    }


def test_step_order_is_preserved() -> None:
    names = [f"s{i}" for i in range(5)]
    definition = WorkflowDefinition.model_validate({"steps": [delay_step(n) for n in names]})
    assert [step.name for step in definition.steps] == names


def test_bounds_are_inclusive() -> None:
    WorkflowDefinition.model_validate(
        {
            "steps": [
                delay_step(seconds=MAX_DELAY_SECONDS),
                http_step("h", timeout_seconds=MAX_HTTP_TIMEOUT_SECONDS),
            ]
        }
    )
    WorkflowDefinition.model_validate({"steps": [delay_step(f"s{i}") for i in range(MAX_STEPS)]})


# --- malformed structure -------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        # Moved from the Phase 2 repository test of executions._step_specs:
        ({}, "missing"),
        ({"steps": []}, "too_short"),
        ({"steps": "nope"}, "list_type"),
        ({"steps": [{"name": "a"}]}, "union_tag_not_found"),
        ({"steps": [{"type": "delay", "config": {"seconds": 1}}]}, "missing"),
        # Further structural errors:
        ("not-an-object", "model_type"),
        ({"steps": ["step"]}, "model_attributes_type"),
        ({"steps": [{"name": "", "type": "demo"}]}, "string_too_short"),
        ({"steps": [{"name": "x" * 201, "type": "demo"}]}, "string_too_long"),
        ({"steps": [delay_step(), delay_step()]}, "value_error"),  # duplicate names
        ({"steps": [delay_step(f"s{i}") for i in range(MAX_STEPS + 1)]}, "too_long"),
        ({"steps": [delay_step()], "on_error": "ignore"}, "extra_forbidden"),
    ],
    ids=[
        "no-steps-key", "empty-steps", "steps-not-list", "step-without-type", "step-without-name",
        "not-object", "step-not-object", "empty-name", "name-too-long", "duplicate-names",
        "too-many-steps", "unknown-top-level-key",
    ],
)
def test_malformed_definitions_rejected(definition: Any, expected: str) -> None:
    assert expected in error_types(definition)


@pytest.mark.parametrize("step_type", ["shell", "python", "script", "exec", "HTTP", ""])
def test_unsupported_step_types_rejected(step_type: str) -> None:
    assert error_types({"steps": [{"name": "s", "type": step_type, "config": {}}]}) == ["union_tag_invalid"]


@pytest.mark.parametrize(
    "step",
    [
        {"name": "h", "type": "http"},
        {"name": "h", "type": "http", "config": {}},
        {"name": "d", "type": "delay"},
        {"name": "d", "type": "delay", "config": {}},
    ],
    ids=["http-no-config", "http-no-url", "delay-no-config", "delay-no-seconds"],
)
def test_required_config_missing(step: dict[str, Any]) -> None:
    assert error_types({"steps": [step]}) == ["missing"]


@pytest.mark.parametrize(
    "step",
    [
        http_step(command="rm -rf /"),
        {"name": "d", "type": "delay", "config": {"seconds": 1, "code": "print(1)"}},
        {"name": "n", "type": "demo", "config": {"script": "x"}},
        {**delay_step(), "retries": 3},
    ],
    ids=["http", "delay", "demo", "step-level"],
)
def test_unknown_config_keys_rejected(step: dict[str, Any]) -> None:
    assert error_types({"steps": [step]}) == ["extra_forbidden"]


# --- bounded numeric config ------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "greater_than"),
        (-1, "greater_than"),
        (MAX_DELAY_SECONDS + 0.001, "less_than_equal"),
        (True, "float_type"),
        ("5", "float_type"),
        (None, "float_type"),
    ],
)
def test_delay_seconds_bounds(seconds: Any, expected: str) -> None:
    assert error_types({"steps": [delay_step(seconds=seconds)]}) == [expected]


@pytest.mark.parametrize(
    ("timeout", "expected"),
    [(0, "greater_than"), (MAX_HTTP_TIMEOUT_SECONDS + 1, "less_than_equal"), ("10", "float_type")],
)
def test_http_timeout_bounds(timeout: Any, expected: str) -> None:
    assert error_types({"steps": [http_step(timeout_seconds=timeout)]}) == [expected]


# --- HTTP step configuration -----------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "post", "Put", "PATCH", "delete", "HEAD"])
def test_allowed_http_methods(method: str) -> None:
    definition = WorkflowDefinition.model_validate({"steps": [http_step(method=method)]})
    assert definition.steps[0].config.method == method.upper()


@pytest.mark.parametrize("method", ["CONNECT", "TRACE", "OPTIONS", "FOO", 1])
def test_disallowed_http_methods(method: Any) -> None:
    assert error_types({"steps": [http_step(method=method)]}) == ["literal_error"]


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_body_not_allowed_for_get_and_head(method: str) -> None:
    assert error_types({"steps": [http_step(method=method, body={"a": 1})]}) == ["value_error"]


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "internal.example"},
        {"host": "x"},
        {"Bad Header": "x"},
        {"": "x"},
        {"X-Injected": "a\r\nSet-Cookie: b"},
        {f"X-H{i}": "v" for i in range(21)},
        {"X-Num": 1},
    ],
    ids=["host", "host-lower", "space-in-name", "empty-name", "crlf-value", "too-many", "non-string-value"],
)
def test_invalid_headers_rejected(headers: dict[str, Any]) -> None:
    assert error_types({"steps": [http_step(headers=headers)]})


# --- HTTP target (SSRF) checks -----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/path?q=1",
        "https://api.example.com:8443/v1/",
        "https://xn--bcher-kva.example/",
        "https://8.8.8.8/",
        "https://[2001:4860:4860::8888]/",
        "https://example.com./",
    ],
)
def test_public_http_targets_allowed(url: str) -> None:
    assert check_http_target(url) == url


@pytest.mark.parametrize(
    "url",
    [
        # Schemes other than http/https.
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://example.com",
        "javascript:alert(1)",
        "example.com/no-scheme",
        # Malformed or credential-bearing URLs.
        "http://",
        "http://user:secret@example.com/",
        "https://example.com:99999/",
        "http://exa%6dple.com/",
        "http://ｌｏｃａｌｈｏｓｔ/",
        "http://under_score.example.com/",
        # Loopback, private, link-local, reserved, multicast (incl. alternative spellings).
        "http://127.0.0.1/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://0.0.0.0/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.1.10/",
        "http://100.64.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://224.0.0.1/",
        "http://255.255.255.255/",
        "http://[::1]/",
        "http://[::]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://[2002:7f00:1::]/",
        # Local or internal host names.
        "http://localhost/",
        "http://LOCALHOST:8000/",
        "http://localhost./",
        "http://app.localhost/",
        "http://printer.local/",
        "http://metadata.google.internal/",
        "http://router.home.arpa/",
        "http://db/",
        "http://redis:6379/",
    ],
)
def test_unsafe_http_targets_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        check_http_target(url)


def test_unsafe_url_rejected_inside_definition() -> None:
    errors = error_types({"steps": [http_step(url="http://169.254.169.254/")]})
    assert errors == ["value_error"]


def test_url_length_bounded() -> None:
    long_url = "https://example.com/" + "a" * 2048
    assert error_types({"steps": [http_step(url=long_url)]}) == ["string_too_long"]
