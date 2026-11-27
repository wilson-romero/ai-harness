"""The response mode of a session: storage, service, Mock and CLI (change response-mode).

The Mock and small synthetic providers stand in for Copilot here; the provider against the
synthetic chat page is tested in tests/browser/test_copilot_mode.py.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from uuid import UUID

import pytest

from harness.config import Settings
from harness.core.contracts import RequestStatus
from harness.core.errors import InvalidInput, UsageError
from harness.core.response_mode import ResponseMode, describe_mode, parse_mode
from harness.providers.base import ModeUnavailable
from harness.providers.mock import MockProvider
from harness.storage import repositories as repo
from harness.storage.database import MIGRATIONS_DIR, connect, migrate, transaction
from tests.conftest import RecordingProvider, query

AUTO, QUICK, DEEP = ResponseMode.AUTO, ResponseMode.QUICK, ResponseMode.DEEP


class FallbackProvider:
    """A synthetic provider that confirms the mode asked for and then reports another, as a
    page that falls back during the answer."""

    name = "mock"
    synthetic_content = True

    def __init__(self, after: ResponseMode | None) -> None:
        self.after = after

    def check_mode(self, mode: ResponseMode) -> None:
        pass

    async def ask(self, request, on_sent, *, on_mode=None) -> str:
        on_mode(request.mode)
        on_sent()
        if self.after is not None:
            on_mode(self.after)
        return "respuesta sintética"


class PickyProvider(MockProvider):
    """The Mock, but it cannot set `deep` (as Copilot without the measured control)."""

    def check_mode(self, mode: ResponseMode) -> None:
        if mode is DEEP:
            raise ModeUnavailable("this synthetic provider cannot set deep; nothing was sent")


def _modes(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT requested_mode, confirmed_mode FROM requests ORDER BY rowid")]


# -- parsing and showing ------------------------------------------------------------------------


def test_the_three_modes_parse_and_anything_else_is_refused():
    assert [parse_mode(word) for word in ("auto", "quick", "deep")] == [AUTO, QUICK, DEEP]
    for word in ("", "Deep", "rapidisimo", "auto ", "deeper"):
        with pytest.raises(UsageError, match="auto, quick or deep"):
            parse_mode(word)


def test_what_is_shown_for_a_request():
    assert describe_mode(None, None) is None  # a request from before migration 008
    assert describe_mode(AUTO, None) is None  # the page's own choice: nothing to say
    assert describe_mode(AUTO, AUTO) is None
    assert describe_mode(DEEP, DEEP) == "mode deep"
    assert describe_mode(DEEP, QUICK) == "mode quick (asked deep)"
    assert describe_mode(AUTO, QUICK) == "mode quick (asked auto)"
    assert describe_mode(QUICK, None) == "mode quick not confirmed"


# -- the measured selector (D3, D7) -------------------------------------------------------------


def _measurement(control: dict) -> dict:
    from tests.conftest import REPO_ROOT

    fixtures = REPO_ROOT / "tests" / "fixtures" / "copilot_ui"
    data = json.loads((fixtures / "ui.json").read_text("utf-8"))
    return data | {"response_mode": control}


def test_the_synthetic_measurements_of_the_selector_are_valid():
    from harness.providers.copilot_ui import UiMeasurement
    from tests.conftest import REPO_ROOT

    for name in ("response-mode-menu.json", "response-mode-listbox.json"):
        raw = (REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / name).read_text("utf-8")
        control = UiMeasurement.model_validate(_measurement(json.loads(raw))).response_mode
        assert control is not None and control.options


@pytest.mark.parametrize("change, why", [
    ({"trigger": {"role": "button", "name": "Send synthetic message", "exact": True}},
     "reuses a locator of another control"),
    ({"options": {"deep": {"css": "#synthetic-new-chat"}}, "readback": "checked_option"},
     "reuses a locator of another control"),
    ({"options": {}}, "at least one option"),
    ({"labels": {"quick": "Synthetic brisk"}}, "label of every option"),
    ({"labels": {"auto": "x", "quick": "x", "deep": "y"}}, "distinct labels"),
    ({"options": {"quick": {"css": ".o"}, "deep": {"css": ".o"}}, "readback": "checked_option"},
     "share one option"),
    ({"readback": "guess"}, "readback"),
])
def test_a_selector_that_could_touch_another_control_is_refused(change, why):
    """Negative controls of the schema: the selector is never the send, stop, new-chat or
    editor control, and its readback is one of the two measured kinds."""
    from harness.providers.copilot_ui import UiMeasurement
    from pydantic import ValidationError

    menu = {
        "trigger": {"css": "#t"},
        "options": {m: {"css": f"#{m}"} for m in ("auto", "quick", "deep")},
        "labels": {"auto": "A", "quick": "Q", "deep": "D"},
        "readback": "trigger_label",
    }
    with pytest.raises(ValidationError, match=why):
        UiMeasurement.model_validate(_measurement(menu | change))
    UiMeasurement.model_validate(_measurement(menu))  # control: the unchanged one is valid


# -- migration 008 ------------------------------------------------------------------------------


def test_a_database_of_migration_007_opens_unchanged(data_dir, tmp_path):
    """Scenario «Una base anterior abre sin cambios»."""
    up_to_7 = tmp_path / "migrations-007"
    up_to_7.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("00[1-7]_*.sql")):
        (up_to_7 / path.name).write_text(path.read_text("utf-8"), "utf-8")
    conn = connect(data_dir)
    assert migrate(conn, up_to_7) == [1, 2, 3, 4, 5, 6, 7]
    conn.execute(
        "INSERT INTO sessions (session_id, name, project_id, provider, remote_ref, status,"
        " created_at, updated_at) VALUES ('0190a000-0000-7000-8000-000000000001', 'Vieja', NULL,"
        " 'mock', 'conv-old', 'active', '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO requests (request_id, session_id, status, started_at) VALUES"
        " ('0190a000-0000-7000-8000-000000000002', '0190a000-0000-7000-8000-000000000001',"
        " 'completed', '2026-11-01T00:00:01+00:00')")
    before = [tuple(r) for r in conn.execute("SELECT * FROM sessions")]
    assert migrate(conn) == [8]
    after = conn.execute("SELECT * FROM sessions").fetchone()
    assert tuple(after)[: len(before[0])] == before[0]  # every old column keeps its value
    assert after["response_mode"] == "auto"
    session = repo.get_session(conn, UUID("0190a000-0000-7000-8000-000000000001"))
    assert session is not None and session.response_mode is AUTO and session.remote_ref == "conv-old"
    assert _modes(conn) == [(None, None)]  # an old request has no mode recorded
    conn.close()


def test_the_new_columns_refuse_an_unknown_mode(conn):
    """Negative control of the CHECK constraints."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions (session_id, name, provider, status, created_at, updated_at,"
            " response_mode) VALUES ('x', 'n', 'mock', 'created', 't', 't', 'turbo')")
    conn.execute(
        "INSERT INTO sessions (session_id, name, provider, status, created_at, updated_at)"
        " VALUES ('s', 'n', 'mock', 'created', 't', 't')")
    for column in ("requested_mode", "confirmed_mode"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"INSERT INTO requests (request_id, session_id, status, started_at, {column})"
                " VALUES ('r', 's', 'pending', 't', 'turbo')")


# -- the session's mode (service) ---------------------------------------------------------------


def test_a_new_session_starts_in_auto(make_service):
    """Scenario «Una sesión nueva empieza en automático»."""
    service = make_service()
    session = service.create_session("S")
    assert service.require_session(str(session.session_id)).response_mode is AUTO


async def test_setting_the_mode_sends_nothing_and_is_audited(conn, make_service):
    """Scenario «Cambiar de modo no envía»."""
    mock = MockProvider()
    service = make_service({"mock": mock})
    session = service.create_session("S")
    assert service.set_mode(session.session_id, mock, "deep") is DEEP
    assert service.require_session(str(session.session_id)).response_mode is DEEP
    assert mock.calls == 0
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    assert [tuple(r) for r in conn.execute(
        "SELECT event_type, outcome FROM audit_events WHERE event_type = 'session.mode'")] == [
        ("session.mode", "deep")]


def test_an_unknown_mode_changes_nothing(conn, make_service):
    """Scenario «Modo desconocido»."""
    mock = MockProvider()
    service = make_service({"mock": mock})
    session = service.create_session("S")
    with pytest.raises(UsageError, match="auto, quick or deep"):
        service.set_mode(session.session_id, mock, "rapidisimo")
    assert service.require_session(str(session.session_id)).response_mode is AUTO
    assert conn.execute(
        "SELECT count(*) FROM audit_events WHERE event_type = 'session.mode'").fetchone()[0] == 0


async def test_a_provider_without_modes_takes_only_auto(conn, make_service):
    recorder = RecordingProvider()
    service = make_service({"mock": recorder})
    session = service.create_session("S")
    assert service.set_mode(session.session_id, recorder, "auto") is AUTO
    for word in ("quick", "deep"):
        with pytest.raises(ModeUnavailable, match="only the automatic mode"):
            service.set_mode(session.session_id, recorder, word)
    assert service.require_session(str(session.session_id)).response_mode is AUTO


async def test_a_mode_the_provider_cannot_set_is_refused_before_anything(conn, make_service):
    """A session left in `deep` (set when the provider could) is refused at question time,
    before anything is recorded, when the provider no longer can."""
    service = make_service({"mock": MockProvider()})
    session = service.create_session("S")
    service.set_mode(session.session_id, MockProvider(), "deep")
    picky = PickyProvider()
    with pytest.raises(ModeUnavailable, match="cannot set deep"):
        await service.ask_taken(session.session_id, picky, "hola")
    assert picky.calls == 0
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    with pytest.raises(ModeUnavailable):
        service.set_mode(session.session_id, picky, "deep")
    service.set_mode(session.session_id, picky, "quick")  # control: the provider can do quick


# -- the mode reaches the provider and is recorded -----------------------------------------------


@pytest.mark.parametrize("mode", [AUTO, QUICK, DEEP])
async def test_the_mock_receives_each_mode_and_answers_by_it(conn, make_service, mode):
    """Scenario «El Mock admite los tres»."""
    mock = MockProvider()
    service = make_service({"mock": mock})
    session = service.create_session("S")
    service.set_mode(session.session_id, mock, mode.value)
    response = await service.ask(str(session.session_id), "pregunta sintética")
    assert response.status is RequestStatus.COMPLETED
    assert mock.modes == [mode]
    assert _modes(conn) == [(mode.value, mode.value)]
    again = await service.ask(str(session.session_id), "pregunta sintética")
    assert again.text == response.text  # deterministic in the same session and mode
    if mode is AUTO:
        assert "in mode" not in response.text  # the answers of the default stay as they were
    else:
        assert response.text.endswith(f"in mode {mode.value}.")


async def test_a_fallback_after_the_answer_is_recorded_and_warned(conn, make_service):
    """Scenario «La página vuelve a otro modo»."""
    provider = FallbackProvider(after=QUICK)
    service = make_service({"mock": provider})
    session = service.create_session("S")
    service.set_mode(session.session_id, provider, "deep")
    response = await service.ask(str(session.session_id), "hola")
    assert response.status is RequestStatus.COMPLETED
    assert _modes(conn) == [("deep", "quick")]
    assert any("quick" in w and "deep" in w for w in response.warnings)
    [entry, _] = service.history(str(session.session_id))
    assert describe_mode(entry.requested_mode, entry.confirmed_mode) == "mode quick (asked deep)"


async def test_no_fallback_no_warning(conn, make_service):
    """Control of the previous test: the same provider without a fallback warns nothing."""
    provider = FallbackProvider(after=None)
    service = make_service({"mock": provider})
    session = service.create_session("S")
    service.set_mode(session.session_id, provider, "deep")
    response = await service.ask(str(session.session_id), "hola")
    assert _modes(conn) == [("deep", "deep")] and response.warnings == ()


async def test_a_mode_of_an_unexpected_shape_is_not_stored(conn, make_service):
    class Odd(FallbackProvider):
        async def ask(self, request, on_sent, *, on_mode=None) -> str:
            on_mode("turbo")
            on_sent()
            return "x"

    provider = Odd(after=None)
    service = make_service({"mock": provider})
    session = service.create_session("S")
    response = await service.ask(str(session.session_id), "hola")
    assert _modes(conn) == [("auto", None)]
    assert any("unexpected" in w for w in response.warnings)


# -- the deadline of deep (SEC-07) --------------------------------------------------------------


async def test_deep_waits_longer_than_quick(conn, data_dir):
    """Scenario «Deep espera más que quick»: the Mock answers after 0.6 s; the normal deadline
    is 0.3 s and the deep one 2 s."""
    from harness.core.service import SessionService

    mock = MockProvider(delay_ms=600)
    service = SessionService(conn, data_dir, lambda name: mock, "mock", 0.3, deep_timeout_s=2.0)
    session = service.create_session("S")
    service.set_mode(session.session_id, mock, "deep")
    deep = await service.ask(str(session.session_id), "uno")
    service.set_mode(session.session_id, mock, "quick")
    quick = await service.ask(str(session.session_id), "dos")
    assert (deep.status, quick.status) == (RequestStatus.COMPLETED, RequestStatus.UNCERTAIN)
    assert mock.calls == 2  # the uncertain one was not resent


async def test_deep_before_sending_is_still_a_timeout(conn, data_dir):
    from harness.core.service import SessionService

    mock = MockProvider("timeout_before_send")
    service = SessionService(conn, data_dir, lambda name: mock, "mock", 0.1, deep_timeout_s=0.3)
    session = service.create_session("S")
    service.set_mode(session.session_id, mock, "deep")
    started = asyncio.get_running_loop().time()
    response = await service.ask(str(session.session_id), "uno")
    assert response.status is RequestStatus.TIMEOUT
    assert asyncio.get_running_loop().time() - started >= 0.25  # the deep deadline, not 0.1 s


def test_the_deep_deadline_defaults_to_three_times_and_cannot_be_lower():
    assert Settings.from_env({}).deep_request_timeout_s == 360.0
    assert Settings.from_env({"HARNESS_REQUEST_TIMEOUT_S": "50"}).deep_request_timeout_s == 150.0
    assert Settings.from_env({"HARNESS_DEEP_REQUEST_TIMEOUT_S": "900"}).deep_request_timeout_s == 900.0
    with pytest.raises(InvalidInput, match="HARNESS_DEEP_REQUEST_TIMEOUT_S.*HARNESS_REQUEST_TIMEOUT_S"):
        Settings.from_env({"HARNESS_REQUEST_TIMEOUT_S": "100", "HARNESS_DEEP_REQUEST_TIMEOUT_S": "50"})


# -- the CLI ------------------------------------------------------------------------------------


def test_ask_with_mode_remembers_it(cli, data_dir):
    """Scenario «La opción de la CLI recuerda el modo»."""
    session_id = cli("session", "create", "S")[1].strip()
    code, out, err = cli("ask", session_id, "uno", "--mode", "quick")
    assert code == 0, err
    assert out.strip().endswith("in mode quick.")
    code, out, _ = cli("ask", session_id, "dos")
    assert code == 0 and out.strip().endswith("in mode quick.")
    assert query(data_dir, "SELECT response_mode FROM sessions") == [("quick",)]
    assert query(data_dir, "SELECT requested_mode, confirmed_mode FROM requests"
                           " ORDER BY started_at") == [("quick", "quick")] * 2


def test_ask_refuses_an_unknown_mode_before_anything(cli, data_dir):
    session_id = cli("session", "create", "S")[1].strip()
    with pytest.raises(SystemExit) as refused:  # argparse refuses it, with its usage line
        cli("ask", session_id, "uno", "--mode", "turbo")
    assert refused.value.code == 2
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]
    assert query(data_dir, "SELECT response_mode FROM sessions") == [("auto",)]


def test_history_shows_the_mode_when_it_is_not_plain_auto(cli, data_dir):
    session_id = cli("session", "create", "S")[1].strip()
    cli("ask", session_id, "uno")
    cli("ask", session_id, "dos", "--mode", "deep")
    _, out, _ = cli("history", session_id)
    lines = out.strip().split("\n")
    assert lines[0] == "[completed] user: uno"  # the default stays as it was
    assert lines[2] == "[completed, mode deep] user: dos"


async def test_history_without_content_shows_the_mode(conn, make_service, capsys):
    """Scenario «Historial con el modo confirmado», for a provider whose content is not kept
    (the shape `history` prints for Copilot)."""
    from harness.cli import _history_without_content

    provider = FallbackProvider(after=QUICK)
    provider.synthetic_content = False
    service = make_service({"mock": provider})
    session = service.create_session("S")
    service.set_mode(session.session_id, provider, "deep")
    await service.ask(str(session.session_id), "hola")
    _history_without_content(service, service.require_session(str(session.session_id)))
    request_line = capsys.readouterr().out.strip().split("\n")[-1]
    assert request_line.startswith("[completed] ") and request_line.endswith(
        " mode quick (asked deep)")
