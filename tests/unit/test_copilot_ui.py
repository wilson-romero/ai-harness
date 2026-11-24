"""The measurement schema accepts the synthetic file and rejects anything it cannot trust."""

import json
import shutil
from pathlib import Path

import pytest

from harness.config import Settings
from harness.core.errors import InvalidInput
from harness.providers.copilot_ui import (
    MeasurementError,
    load_measurement,
    measurement_path,
    parse_locators,
)
from tests.conftest import REPO_ROOT

SYNTHETIC = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "ui.json"


def write_measurement(data_dir: Path, data: dict) -> None:
    path = measurement_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def synthetic() -> dict:
    return json.loads(SYNTHETIC.read_text(encoding="utf-8"))


def test_synthetic_measurement_is_accepted(tmp_path):
    path = measurement_path(tmp_path)
    path.parent.mkdir(parents=True)
    shutil.copy(SYNTHETIC, path)
    measurement = load_measurement(tmp_path)
    assert measurement.complete
    assert measurement.end_signal.name == "stop_hidden"
    assert measurement.conversation_ref.index == 1


def test_missing_measurement_is_rejected(tmp_path):
    with pytest.raises(MeasurementError, match="run the probe"):
        load_measurement(tmp_path)


def test_incomplete_measurement_is_rejected_naming_the_missing_part(tmp_path):
    data = synthetic() | {"complete": False, "end_signal": None, "missing": ["end_signal"]}
    write_measurement(tmp_path, data)
    with pytest.raises(MeasurementError, match="incomplete; missing: end_signal"):
        load_measurement(tmp_path)


def test_measurement_marked_complete_with_a_gap_is_rejected(tmp_path):
    data = synthetic() | {"max_prompt_chars": None}
    write_measurement(tmp_path, data)
    with pytest.raises(MeasurementError, match="missing: max_prompt_chars"):
        load_measurement(tmp_path)


def test_other_schema_version_is_rejected(tmp_path):
    write_measurement(tmp_path, synthetic() | {"schema_version": 2})
    with pytest.raises(MeasurementError, match="schema version 2"):
        load_measurement(tmp_path)


def test_unknown_field_is_rejected(tmp_path):
    write_measurement(tmp_path, synthetic() | {"copilot_url": "https://tenant.example.com/"})
    with pytest.raises(MeasurementError, match="copilot_url"):
        load_measurement(tmp_path)


def test_unknown_locator_field_is_rejected():
    raw = json.dumps(synthetic()["locators"] | {"sidebar_title": {"css": "nav a"}})
    with pytest.raises(MeasurementError, match="sidebar_title"):
        parse_locators(raw)


def test_locator_needs_exactly_one_kind():
    locators = synthetic()["locators"]
    locators["composer"] = {"css": "#a", "role": "textbox"}
    with pytest.raises(MeasurementError, match="exactly one"):
        parse_locators(json.dumps(locators))


def test_identity_measured_as_not_recoverable_is_a_value_not_a_gap(tmp_path):
    write_measurement(tmp_path, synthetic() | {"identity_recoverable": False})
    assert load_measurement(tmp_path).identity_recoverable is False


def test_copilot_settings_have_no_real_defaults(tmp_path):
    settings = Settings.from_env({"HARNESS_DATA_DIR": str(tmp_path)})
    assert settings.copilot_url is None
    assert settings.edge_profile == tmp_path / "edge-profile"
    assert settings.copilot_ready_timeout_s == 60.0
    assert settings.copilot_max_prompt_chars is None
    assert settings.browser_headless is False
    with pytest.raises(InvalidInput, match="HARNESS_COPILOT_URL is not set"):
        settings.require_copilot_url()


def test_copilot_settings_are_validated():
    with pytest.raises(InvalidInput, match="HARNESS_COPILOT_MAX_PROMPT_CHARS"):
        Settings.from_env({"HARNESS_COPILOT_MAX_PROMPT_CHARS": "0"})
    with pytest.raises(InvalidInput, match="HARNESS_COPILOT_READY_TIMEOUT_S"):
        Settings.from_env({"HARNESS_COPILOT_READY_TIMEOUT_S": "soon"})
    bad_url = Settings.from_env({"HARNESS_COPILOT_URL": "file:///tmp/x"})
    with pytest.raises(InvalidInput, match="http or https") as error:
        bad_url.require_copilot_url()
    assert "file:///tmp/x" not in str(error.value)  # the configured value is never echoed


def test_env_example_has_no_real_urls():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "http" not in text
    for name in ("HARNESS_COPILOT_READY_TIMEOUT_S", "HARNESS_COPILOT_MAX_PROMPT_CHARS"):
        assert f"{name}=" in text
