"""Schema of the Copilot Web measurement (`ui.json`) and of the probe's locator candidates.

Everything that depends on the real Copilot interface comes from a file the probe writes under
`HARNESS_DATA_DIR/copilot/`, never from this repository. This module only knows its shape.
The measurement holds locators of controls, the shape of a conversation reference (never a
value), login host names, counts, times and booleans: no URL, account, title or response text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self
from urllib.parse import parse_qsl, quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness.core.errors import HarnessError

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

_PLAIN_SEGMENT = re.compile(r"[a-z][a-z-]{0,30}")

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

    def css_selector(self) -> str | None:
        """The same element as a CSS selector, for a read inside the page: only `css` and
        `test_id` have one."""
        if self.css:
            return self.css
        if self.test_id:
            return f"[data-testid={json.dumps(self.test_id)}]"
        return None

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
    # The element of a code block that holds its language label, looked up inside the block:
    # the language of a fenced block comes only from it (css or test_id).
    code_language: LocatorSpec | None = None

    @model_validator(mode="after")
    def _button_needs_a_locator(self) -> Self:
        if self.send_with == "button" and self.send is None:
            raise ValueError("send_with `button` needs a `send` locator")
        if self.code_language is not None and self.code_language.css_selector() is None:
            raise ValueError("`code_language` needs a css or test_id locator")
        return self


class ConversationRef(_Strict):
    """Where the conversation identifier sits in the URL. Never the identifier itself."""

    kind: Literal["path_segment", "query_param"]
    index: int | None = Field(default=None, ge=0)
    param: str | None = None
    # The fixed path segments before the identifier (`["chat", "conversation"]`): plain
    # words only, so that a conversation can be reopened from its identifier alone.
    prefix: list[str] | None = None

    @model_validator(mode="after")
    def _one_place(self) -> Self:
        if (self.kind == "path_segment") != (self.index is not None):
            raise ValueError("path_segment needs `index` and query_param must not have one")
        if (self.kind == "query_param") != (self.param is not None):
            raise ValueError("query_param needs `param` and path_segment must not have one")
        if self.prefix is not None:
            if self.kind != "path_segment" or len(self.prefix) != self.index:
                raise ValueError("`prefix` holds the path segments before the identifier")
            if not all(_PLAIN_SEGMENT.fullmatch(part) for part in self.prefix):
                raise ValueError("`prefix` holds plain words only")
        return self

    def identifier_in(self, url: str) -> str | None:
        """The identifier at the measured place of `url`, ignoring any query string when the
        place is a path segment."""
        parts = urlsplit(url)
        if self.kind == "query_param":
            return dict(parse_qsl(parts.query)).get(self.param or "") or None
        segments = parts.path.split("/")[1:]
        if self.index is None or self.index >= len(segments):
            return None
        if self.prefix is not None and segments[: self.index] != self.prefix:
            return None
        return segments[self.index] or None

    def url_for(self, configured_url: str, identifier: str) -> str | None:
        """The address that reopens a conversation: the configured scheme and host, the
        measured fixed segments and the identifier, plus the configured address's own query if
        it has one (configuration, not conversation data; a conversation URL's query is never
        read). None when the shape cannot build one."""
        if self.kind != "path_segment" or self.prefix is None:
            return None
        parts = urlsplit(configured_url)
        path = "/".join(["", *self.prefix, quote(identifier, safe="")])
        query = f"?{parts.query}" if parts.query else ""
        return f"{parts.scheme}://{parts.netloc}{path}{query}"


ModeName = Literal["auto", "quick", "deep"]
MODE_LABEL_MAX = 60  # an option's accessible name, as the probe keeps it


class ResponseModeControl(_Strict):
    """The response-mode selector of the page (response-mode D3, D7), measured by the probe's
    `response-mode` step: the control that opens the list, the option of each mode the person
    mapped, and how the current mode is read back.

    `checked_option`: with the list open, the one option marked `aria-checked`,
    `aria-selected` or `aria-current`. `trigger_label`: the opening control's label holds the
    label (`labels`) of exactly one option (the longest, if one holds another).
    """

    trigger: LocatorSpec
    options: dict[ModeName, LocatorSpec]
    labels: dict[ModeName, str] = Field(default_factory=dict)
    readback: Literal["checked_option", "trigger_label"]

    @model_validator(mode="after")
    def _usable(self) -> Self:
        if not self.options:
            raise ValueError("a response-mode control needs at least one option")
        if self.trigger in self.options.values():
            raise ValueError("the control that opens the list cannot also be an option")
        if len(set(map(_spec_key, self.options.values()))) != len(self.options):
            raise ValueError("two modes cannot share one option")
        for label in self.labels.values():
            if not label.strip() or len(label) > MODE_LABEL_MAX or not label.isprintable():
                raise ValueError("an option label is a short printable text")
        if self.readback == "trigger_label":
            if set(self.labels) != set(self.options):
                raise ValueError("trigger_label needs the label of every option")
            if len(set(self.labels.values())) != len(self.labels):
                raise ValueError("trigger_label needs distinct labels")
        return self


def _spec_key(spec: LocatorSpec) -> str:
    return spec.model_dump_json()


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
    # Optional: without it only the automatic mode exists (response-mode D2).
    response_mode: ResponseModeControl | None = None

    @model_validator(mode="after")
    def _complete_means_complete(self) -> Self:
        gaps = self.missing_parts()
        if self.complete and gaps:
            raise ValueError(f"marked complete but missing: {', '.join(gaps)}")
        return self

    @model_validator(mode="after")
    def _mode_control_is_no_other_control(self) -> Self:
        """The selector is never the editor, the send, stop or new-chat button (response-mode
        D3): a click meant for the mode must not send or start another conversation."""
        control = self.response_mode
        if control is None:
            return self
        loc = self.locators
        others = {_spec_key(s) for s in (loc.composer, loc.send, loc.stop, loc.new_conversation)
                  if s is not None}
        mine = [control.trigger, *control.options.values()]
        if any(_spec_key(spec) in others for spec in mine):
            raise ValueError("the response-mode control reuses a locator of another control")
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
