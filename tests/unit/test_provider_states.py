"""The states a provider can produce through the service (design D5), without a browser."""

from __future__ import annotations

import pytest

from harness.core.errors import SessionClosed
from harness.providers.base import (
    AuthenticationRequired,
    ProviderError,
    ProviderTimeout,
    ProviderUncertain,
    RemoteConversationLost,
)


class ScriptedProvider:
    """Raises or answers as told, before or after `on_sent`, and can report events."""

    name = "scripted"
    synthetic_content = False

    def __init__(self, *, raise_before=None, raise_after=None, bind=None, warn=None, check=None):
        self.raise_before = raise_before
        self.raise_after = raise_after
        self.bind = bind
        self.warn = warn
        self.check_error = check
        self.requests = []
        self.checked = []

    def check(self, prompt):
        self.checked.append(len(prompt))
        if self.check_error is not None:
            raise self.check_error

    async def ask(self, request, on_sent, *, events=None):
        self.requests.append(request)
        if self.raise_before is not None:
            raise self.raise_before
        on_sent()
        if self.bind is not None:
            events.bound(self.bind)
        if self.warn is not None:
            events.warn(self.warn)
        if self.raise_after is not None:
            raise self.raise_after
        return "answer"


def scripted(make_service, **kwargs):
    provider = ScriptedProvider(**kwargs)
    service = make_service({"scripted": provider}, default="scripted")
    session = service.create_session("S")
    return service, provider, str(session.session_id)


def states(conn):
    requests = [row[0] for row in conn.execute("SELECT status FROM requests ORDER BY started_at")]
    session = tuple(conn.execute("SELECT status, remote_ref FROM sessions").fetchone())
    return requests, session


async def test_authentication_required_before_sending(conn, make_service):
    service, _, sid = scripted(make_service, raise_before=AuthenticationRequired("sign in"))
    response = await service.ask(sid, "q")
    assert response.status == "authentication_required"
    assert states(conn) == (["authentication_required"], ("authentication_required", None))


async def test_authentication_required_after_sending_is_uncertain(conn, make_service):
    """Negative control of D5: once the prompt may have left, nothing else wins."""
    service, _, sid = scripted(make_service, raise_after=AuthenticationRequired("sign in"))
    response = await service.ask(sid, "q")
    assert response.status == "uncertain"
    assert states(conn) == (["uncertain"], ("uncertain", None))


async def test_lost_conversation_fails_and_closes_the_session(conn, make_service):
    service, _, sid = scripted(make_service, raise_before=RemoteConversationLost("gone"))
    response = await service.ask(sid, "q")
    assert response.status == "failed"
    assert states(conn) == (["failed"], ("closed", None))


async def test_lost_conversation_after_sending_is_uncertain(conn, make_service):
    service, _, sid = scripted(make_service, raise_after=RemoteConversationLost("gone"))
    assert (await service.ask(sid, "q")).status == "uncertain"
    assert states(conn) == (["uncertain"], ("uncertain", None))


async def test_provider_uncertain(conn, make_service):
    service, _, sid = scripted(make_service, raise_after=ProviderUncertain("window closed"))
    response = await service.ask(sid, "q")
    assert response.status == "uncertain" and "was not resent" in response.detail
    assert states(conn) == (["uncertain"], ("uncertain", None))


async def test_plain_provider_error_after_sending_stays_failed(conn, make_service):
    """As for the Mock (`llm-provider`, «Error del proveedor»): only the new kinds are uncertain."""
    service, _, sid = scripted(make_service, raise_after=ProviderError("boom"))
    assert (await service.ask(sid, "q")).status == "failed"
    assert states(conn) == (["failed"], ("created", None))


async def test_provider_timeout_before_sending(conn, make_service):
    service, _, sid = scripted(make_service, raise_before=ProviderTimeout("page not ready"))
    response = await service.ask(sid, "q")
    assert response.status == "timeout" and response.detail == "page not ready"
    assert states(conn) == (["timeout"], ("created", None))


async def test_bound_reference_is_stored_and_never_replaced(conn, make_service):
    service, provider, sid = scripted(make_service, bind="conv-0001")
    assert (await service.ask(sid, "q")).status == "completed"
    assert states(conn) == (["completed"], ("active", "conv-0001"))
    provider.bind = "conv-0002"
    await service.ask(sid, "q2")
    assert states(conn)[1] == ("active", "conv-0001")
    second = provider.requests[1]
    assert second.remote_ref == "conv-0001" and second.completed_turns == 1


async def test_reference_survives_a_deadline_after_binding(conn, make_service):
    """`bound` is stored at once: a failure after it keeps the reference (D5)."""
    service, _, sid = scripted(make_service, bind="conv-0003", raise_after=ProviderUncertain("x"))
    assert (await service.ask(sid, "q")).status == "uncertain"
    assert states(conn) == (["uncertain"], ("uncertain", "conv-0003"))


@pytest.mark.parametrize("ref", ["a/b", "x" * 129, "id?q=1", "\x1b[2J", ""])
async def test_reference_of_an_unexpected_shape_is_not_stored(conn, make_service, ref):
    service, _, sid = scripted(make_service, bind=ref)
    response = await service.ask(sid, "q")
    assert response.status == "completed"
    assert states(conn)[1] == ("active", None)
    assert any("unexpected shape" in w for w in response.warnings)


async def test_warnings_reach_the_response_cleaned(make_service):
    service, _, sid = scripted(make_service, warn="turn\x1b[31m count‮")
    response = await service.ask(sid, "q")
    assert response.warnings == ("turn count",)  # the whole escape sequence goes


async def test_question_in_a_closed_session_is_refused_without_a_request(conn, make_service):
    service, provider, sid = scripted(make_service, raise_before=RemoteConversationLost("gone"))
    await service.ask(sid, "q")
    before = conn.execute("SELECT count(*) FROM requests").fetchone()[0]
    with pytest.raises(SessionClosed, match="Create a new session"):
        await service.ask(sid, "again")
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == before == 1
    assert len(provider.requests) == 1


async def test_check_refuses_before_anything_is_recorded(conn, make_service):
    from harness.core.errors import InvalidInput

    service, provider, sid = scripted(make_service, check=InvalidInput("too long"))
    with pytest.raises(InvalidInput):
        await service.ask(sid, "q")
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert provider.requests == [] and provider.checked == [1]


async def test_authentication_then_a_completed_question_makes_the_session_active(conn, make_service):
    service, provider, sid = scripted(make_service, raise_before=AuthenticationRequired("x"))
    await service.ask(sid, "q")
    provider.raise_before = None
    assert (await service.ask(sid, "q")).status == "completed"
    assert states(conn) == (["authentication_required", "completed"], ("active", None))


async def test_uncertain_without_reference_warns_of_an_orphan(conn, make_service):
    service, provider, sid = scripted(make_service, raise_after=ProviderUncertain("x"))
    await service.ask(sid, "q")
    provider.raise_after = None
    response = await service.ask(sid, "q2")
    assert response.status == "completed"
    assert any("orphaned" in w for w in response.warnings)
    assert states(conn)[0] == ["uncertain", "completed"]


async def test_providers_without_events_are_called_as_before(make_service):
    """The Mock and the session-core test providers take no `events` argument."""

    class Plain:
        name = "plain"
        synthetic_content = True

        async def ask(self, request, on_sent):
            on_sent()
            return "ok"

    service = make_service({"plain": Plain()}, default="plain")
    session = service.create_session("S")
    assert (await service.ask(str(session.session_id), "q")).status == "completed"

