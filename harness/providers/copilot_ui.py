"""Schema of the Copilot Web measurement (`ui.json`) and of the probe's locator candidates.

Everything that depends on the real Copilot interface comes from a file the probe writes under
`HARNESS_DATA_DIR/copilot/`, never from this repository. This module only knows its shape.
The measurement holds locators of controls, the shape of a conversation reference (never a
value), login host names, counts, times and booleans: no URL, account, title or response text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness.core.errors import HarnessError

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

SCHEMA_VERSION = 1
MEASUREMENT_DIR = "copilot"
MEASUREMENT_FILE = "ui.json"
CANDIDATES_FILE = "candidates.json"

# What a complete measurement must contain. The names are what an error reports as missing.
REQUIRED_PARTS = (
    "conversation_ref",
    "identity_recoverable",
    "end_signal",
    "stability_window_ms",
    "max_prompt_chars",
    "startup_ms",
    "login",
)
END_SIGNALS = ("stop_hidden", "send_ready", "done_control", "aria_busy", "text_stable")


class MeasurementError(HarnessError):
    """The measurement file is missing, malformed, of another schema or incomplete."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LocatorSpec(_Strict):
    """One Playwright locator, written the way `playwright codegen` prints it.

    Exactly one of `css`, `role`, `test_id`, `label` or `placeholder`; `name` goes with `role`.
    """

    css: str | None = None
    role: str | None = None
    name: str | None = None
    test_id: str | None = None
    label: str | None = None
    placeholder: str | None = None
    exact: bool = False

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        kinds = [k for k in ("css", "role", "test_id", "label", "placeholder") if getattr(self, k)]
        if len(kinds) != 1:
            raise ValueError("a locator needs exactly one of css, role, test_id, label, placeholder")
        if self.name is not None and self.role is None:
            raise ValueError("`name` is only valid together with `role`")
        return self

    def resolve(self, root: Page | Locator) -> Locator:
        if self.css:
            return root.locator(self.css)
        if self.role:
            if self.name is None:
                return root.get_by_role(self.role)  # type: ignore[arg-type]
            return root.get_by_role(self.role, name=self.name, exact=self.exact)  # type: ignore[arg-type]
        if self.test_id:
            return root.get_by_test_id(self.test_id)
        if self.label:
            return root.get_by_label(self.label, exact=self.exact)
        return root.get_by_placeholder(self.placeholder or "", exact=self.exact)


class Locators(_Strict):
    """The controls the provider uses. This is also the shape of `candidates.json`.

    `send_with` says how a prompt is sent: pressing Enter in the composer, or clicking `send`.
    With Enter the send button is optional; when known it still tells when sending is possible
    again. `response_done_control` is looked up inside the assistant turn; `busy_region` is the
    element whose `aria-busy` marks a reply in progress (the last match), when it is not the
    assistant turn itself.
    """

    composer: LocatorSpec
    send_with: Literal["button", "enter"] = "button"
    send: LocatorSpec | None = None
    new_conversation: LocatorSpec
    user_turn: LocatorSpec
    assistant_turn: LocatorSpec
    stop: LocatorSpec | None = None
    response_done_control: LocatorSpec | None = None
    busy_region: LocatorSpec | None = None
    login_indicator: LocatorSpec | None = None

    @model_validator(mode="after")
    def _button_needs_a_locator(self) -> Self:
        if self.send_with == "button" and self.send is None:
            raise ValueError("send_with `button` needs a `send` locator")
        return self


class ConversationRef(_Strict):
    """Where the conversation identifier sits in the URL. Never the identifier itself."""

    kind: Literal["path_segment", "query_param"]
    index: int | None = Field(default=None, ge=0)
    param: str | None = None

    @model_validator(mode="after")
    def _one_place(self) -> Self:
        if (self.kind == "path_segment") != (self.index is not None):
            raise ValueError("path_segment needs `index` and query_param must not have one")
        if (self.kind == "query_param") != (self.param is not None):
            raise ValueError("query_param needs `param` and path_segment must not have one")
        return self


class EndSignal(_Strict):
    name: Literal["stop_hidden", "send_ready", "done_control", "aria_busy", "text_stable"]
    window_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _window_only_for_text(self) -> Self:
        if (self.name == "text_stable") != (self.window_ms is not None):
            raise ValueError("`window_ms` goes with text_stable and only with it")
        return self


class LoginShape(_Strict):
    """How an expired login looks: host names of the login redirection and/or an indicator."""

    hosts: tuple[str, ...] = ()
    indicator_seen: bool = False

    @model_validator(mode="after")
    def _something_to_recognise(self) -> Self:
        if not self.hosts and not self.indicator_seen:
            raise ValueError("a login shape needs login hosts or a login indicator")
        return self


class UiMeasurement(_Strict):
    schema_version: Literal[1]
    complete: bool
    missing: tuple[str, ...] = ()
    measured_at: str
    edge_version: str | None = None
    platform: str | None = None
    locators: Locators
    conversation_ref: ConversationRef | None = None
    identity_recoverable: bool | None = None
    # User turns visible after reopening each probe conversation (P3), and how many were sent.
    turns_visible_after_reopen: tuple[int, ...] = ()
    turns_sent_per_conversation: int | None = Field(default=None, ge=1)
    end_signal: EndSignal | None = None
    stability_window_ms: int | None = Field(default=None, gt=0)
    max_prompt_chars: int | None = Field(default=None, gt=0)
    startup_ms: tuple[int, ...] = ()
    longest_response_ms: int | None = Field(default=None, ge=0)
    recommended_timeout_s: float | None = Field(default=None, gt=0)
    login: LoginShape | None = None

    @model_validator(mode="after")
    def _complete_means_complete(self) -> Self:
        gaps = self.missing_parts()
        if self.complete and gaps:
            raise ValueError(f"marked complete but missing: {', '.join(gaps)}")
        return self

    def missing_parts(self) -> tuple[str, ...]:
        """Parts declared missing plus required parts that are empty. A measured "no"
        (identity not recoverable) is a value, not a gap."""
        empty = [
            part
            for part in REQUIRED_PARTS
            if getattr(self, part) is None or getattr(self, part) == ()
        ]
        return tuple(dict.fromkeys([*self.missing, *empty]))


def measurement_path(data_dir: Path) -> Path:
    return data_dir / MEASUREMENT_DIR / MEASUREMENT_FILE


def parse_measurement(raw: str, source: str = MEASUREMENT_FILE) -> UiMeasurement:
    """Validate a measurement without requiring it to be complete."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MeasurementError(f"{source} is not valid JSON (line {exc.lineno})") from None
    if not isinstance(data, dict):
        raise MeasurementError(f"{source} must contain a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise MeasurementError(
            f"{source} has schema version {version!r}; this harness reads version "
            f"{SCHEMA_VERSION}. Run the probe again"
        )
    try:
        return UiMeasurement.model_validate(data)
    except ValidationError as exc:
        raise MeasurementError(f"{source} is not a valid measurement: {_first_error(exc)}") from None


def load_measurement(data_dir: Path) -> UiMeasurement:
    """The measurement the provider may use: present, of this schema and complete."""
    path = measurement_path(data_dir)
    if not path.is_file():
        raise MeasurementError(
            f"no Copilot measurement at {path}; run the probe first (docs/runbook/copilot.md)"
        )
    measurement = parse_measurement(path.read_text(encoding="utf-8"), path.name)
    missing = measurement.missing_parts()
    if not measurement.complete or missing:
        raise MeasurementError(
            f"the Copilot measurement is incomplete; missing: {', '.join(missing) or 'unknown'}. "
            "Run the probe again"
        )
    return measurement


def parse_locators(raw: str, source: str = CANDIDATES_FILE) -> Locators:
    try:
        return Locators.model_validate_json(raw)
    except ValidationError as exc:
        raise MeasurementError(f"{source} is not valid: {_first_error(exc)}") from None


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"]) or "(root)"
    return f"{where}: {error['msg']}"
