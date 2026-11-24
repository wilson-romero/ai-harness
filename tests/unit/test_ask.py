import socket

import pytest

from harness.core.contracts import RequestStatus, SessionStatus
from harness.core.errors import InvalidInput, UnknownProvider
from harness.providers.mock import MockProvider
from tests.conftest import query


class RealisticProvider:
    """Stands in for a provider whose content must not be stored."""

    name = "realistic"
    synthetic_content = False

    async def ask(self, request, on_sent):
        on_sent()
        return "confidential answer"


def test_mock_is_the_default_provider(cli):
    cli("session", "create", "Default")
    _, out, _ = cli("session", "list")
    assert out.split("\t")[2] == "mock"


def test_unknown_provider(cli, data_dir):
    session_id = cli("session", "create", "S")[1].strip()
    code, out, err = cli("ask", session_id, "hello", HARNESS_PROVIDER="bogus")
    assert code == 1 and out == ""
    assert "unknown provider 'bogus'" in err
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]

    code, _, err = cli("session", "create", "T", HARNESS_PROVIDER="bogus")
    assert code == 1 and "unknown provider" in err
    assert query(data_dir, "SELECT count(*) FROM sessions") == [(1,)]


def test_question_completed(cli, data_dir):
    session_id = cli("session", "create", "S")[1].strip()
    code, out, err = cli("ask", session_id, "Analiza este requerimiento")
    assert code == 0 and out.startswith("[mock ") and err == ""
    assert query(data_dir, "SELECT status, duration_ms IS NOT NULL FROM requests") == [
        ("completed", 1)
    ]
    assert query(data_dir, "SELECT status FROM sessions") == [("active",)]


async def test_empty_prompt_is_rejected(conn, make_service):
    service = make_service()
    session = service.create_session("S")
    with pytest.raises(InvalidInput):
        await service.ask(str(session.session_id), "   ")
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


async def test_same_question_same_answer(make_service):
    service = make_service()
    one = service.create_session("one")
    two = service.create_session("two")
    first = await service.ask(str(one.session_id), "same prompt")
    second = await service.ask(str(one.session_id), "same prompt")
    other = await service.ask(str(two.session_id), "same prompt")
    assert first.text == second.text
    assert first.text != other.text


async def test_mock_works_without_network(make_service, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the mock provider tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    service = make_service()
    session = service.create_session("offline")
    response = await service.ask(str(session.session_id), "no network needed")
    assert response.status is RequestStatus.COMPLETED


@pytest.mark.parametrize(
    ("behavior", "expected", "session_status"),
    [
        ("fail", RequestStatus.FAILED, SessionStatus.CREATED),
        ("timeout_before_send", RequestStatus.TIMEOUT, SessionStatus.CREATED),
        ("timeout_after_send", RequestStatus.UNCERTAIN, SessionStatus.UNCERTAIN),
    ],
)
async def test_result_depends_on_where_it_failed(
    conn, make_service, behavior, expected, session_status
):
    service = make_service({"mock": MockProvider(behavior)}, timeout_s=0.2)
    session = service.create_session("S")
    response = await service.ask(str(session.session_id), "hello")

    assert response.status is expected and response.text is None
    assert conn.execute("SELECT status FROM requests").fetchone()[0] == expected.value
    assert conn.execute("SELECT status FROM sessions").fetchone()[0] == session_status.value
    # No answer is invented for a request that did not complete.
    entries = service.history(str(session.session_id))
    assert [(e.role, e.request_status) for e in entries] == [("user", expected)]


def test_failure_states_exit_non_zero_and_name_the_state(cli):
    session_id = cli("session", "create", "S")[1].strip()
    for behavior, state in [
        ("fail", "failed"),
        ("timeout_before_send", "timeout"),
        ("timeout_after_send", "uncertain"),
    ]:
        code, out, err = cli(
            "ask",
            session_id,
            "hello",
            HARNESS_MOCK_BEHAVIOR=behavior,
            HARNESS_REQUEST_TIMEOUT_S="0.2",
        )
        assert code == 1 and out == ""
        assert f"ended as {state}" in err and "Traceback" not in err
    assert "may have reached the provider" in err


def test_invalid_mock_behavior_is_a_controlled_error(cli):
    session_id = cli("session", "create", "S")[1].strip()
    code, _, err = cli("ask", session_id, "hello", HARNESS_MOCK_BEHAVIOR="explode")
    assert code == 1 and "unknown mock behavior" in err


async def test_content_is_stored_only_for_synthetic_providers(conn, make_service):
    providers = {"mock": MockProvider(), "realistic": RealisticProvider()}

    realistic = make_service(providers, default="realistic")
    session = realistic.create_session("real")
    response = await realistic.ask(str(session.session_id), "confidential question")
    assert response.status is RequestStatus.COMPLETED
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert conn.execute(
        "SELECT count(*) FROM messages WHERE content IS NOT NULL"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT status FROM requests").fetchone()[0] == "completed"

    # Negative control: the same check does find content when the provider is synthetic.
    synthetic = make_service(providers, default="mock")
    other = synthetic.create_session("synthetic")
    await synthetic.ask(str(other.session_id), "synthetic question")
    assert conn.execute(
        "SELECT count(*) FROM messages WHERE content IS NOT NULL"
    ).fetchone()[0] == 2


def test_history_after_two_questions(cli):
    session_id = cli("session", "create", "S")[1].strip()
    cli("ask", session_id, "first")
    cli("ask", session_id, "second")
    code, out, _ = cli("history", session_id)
    lines = out.strip().splitlines()
    assert code == 0 and len(lines) == 4
    assert [line.split(":")[0] for line in lines] == [
        "[completed] user",
        "[completed] assistant",
        "[completed] user",
        "[completed] assistant",
    ]
    assert lines[0].endswith("first") and lines[2].endswith("second")
