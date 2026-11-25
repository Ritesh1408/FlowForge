"""Workflow definition schema: the only step types and configurations FlowForge accepts.

Definitions are untrusted input (AGENTS.md §15). Only predefined, safe step types exist;
nothing in a definition is ever executed as code or as a shell command.
"""

import ipaddress
import re
import socket
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_STEPS = 50
MAX_NAME_LENGTH = 200  # matches workflows.name and execution_steps.name columns
MAX_DELAY_SECONDS = 300
MAX_HTTP_TIMEOUT_SECONDS = 60
DEFAULT_HTTP_TIMEOUT_SECONDS = 10
MAX_URL_LENGTH = 2048
MAX_HEADERS = 20

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]

# Names that resolve to the local machine or to private networks by convention.
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".home.arpa")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")

# Bounded positive seconds; strict so that booleans and numeric strings are rejected.
Seconds = Annotated[float, Field(gt=0, strict=True)]
StepName = Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]


class _Strict(BaseModel):
    # Unknown keys are rejected, so a typo cannot silently change a step's behaviour.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        embedded = address.ipv4_mapped or address.sixtofour
        if embedded is not None:
            return _is_public_ip(embedded)
    return address.is_global and not address.is_multicast


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # Resolvers also accept legacy IPv4 spellings ("127.1", "2130706433", "0x7f000001");
    # inet_aton only parses, it performs no network lookup.
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def check_http_target(url: str) -> str:
    """Validate an HTTP step URL; return it unchanged or raise ``ValueError``.

    Definition-time SSRF guard: only http/https, no embedded credentials, and no target
    that is obviously local or private (loopback, private/link-local/reserved IPs in any
    spelling, localhost-style and single-label host names). A public host name can still
    resolve to a private address, so the executor must re-check resolved addresses.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("URL scheme must be http or https")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL must not contain credentials")
    try:
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        raise ValueError("URL port is invalid") from None
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise ValueError("URL must include a host")

    if ":" in host:  # IPv6 literal (urlsplit strips the brackets and lowercases)
        try:
            address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.IPv6Address(host)
        except ValueError:
            raise ValueError("URL host is not a valid address") from None
    else:
        if not _HOSTNAME_RE.match(host):
            raise ValueError("URL host must be an ASCII host name (use punycode) or an IP address")
        address = _parse_ip(host)

    if address is not None:
        if not _is_public_ip(address):
            raise ValueError("URL must not target a private, loopback or reserved address")
    elif host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES) or "." not in host:
        raise ValueError("URL must target a public host name")
    return url


class HttpStepConfig(_Strict):
    url: str = Field(max_length=MAX_URL_LENGTH)
    method: HttpMethod = "GET"
    headers: dict[str, str] = Field(default_factory=dict, max_length=MAX_HEADERS)
    body: Any = None
    timeout_seconds: Seconds = Field(default=DEFAULT_HTTP_TIMEOUT_SECONDS, le=MAX_HTTP_TIMEOUT_SECONDS)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return check_http_target(value)

    @field_validator("method", mode="before")
    @classmethod
    def _upper_method(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("headers")
    @classmethod
    def _check_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if not name or not re.fullmatch(r"[A-Za-z0-9-]+", name):
                raise ValueError(f"Invalid header name: {name!r}")
            if name.lower() == "host":
                raise ValueError("The Host header cannot be set")
        if any("\r" in v or "\n" in v for v in value.values()):
            raise ValueError("Header values must not contain line breaks")
        return value

    @model_validator(mode="after")
    def _no_body_without_payload_method(self) -> "HttpStepConfig":
        if self.body is not None and self.method in ("GET", "HEAD"):
            raise ValueError(f"A {self.method} request cannot have a body")
        return self


class DelayStepConfig(_Strict):
    seconds: Seconds = Field(le=MAX_DELAY_SECONDS)


class DemoStepConfig(_Strict):
    """Internal demonstration step: performs no I/O."""

    message: str | None = Field(default=None, max_length=500)


class HttpStep(_Strict):
    name: StepName
    type: Literal["http"]
    config: HttpStepConfig


class DelayStep(_Strict):
    name: StepName
    type: Literal["delay"]
    config: DelayStepConfig


class DemoStep(_Strict):
    name: StepName
    type: Literal["demo"]
    config: DemoStepConfig = Field(default_factory=DemoStepConfig)


Step = Annotated[HttpStep | DelayStep | DemoStep, Field(discriminator="type")]
STEP_TYPES = ("http", "delay", "demo")


class WorkflowDefinition(_Strict):
    """Ordered list of steps; executed in this order (AGENTS.md §6)."""

    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS)

    @field_validator("steps")
    @classmethod
    def _unique_step_names(cls, steps: list[Step]) -> list[Step]:
        seen: set[str] = set()
        for step in steps:
            if step.name in seen:
                raise ValueError(f"Duplicate step name: {step.name!r}")
            seen.add(step.name)
        return steps
