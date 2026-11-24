"""Sessions, questions and recovery of interrupted requests."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

from harness.core.contracts import (
    HistoryEntry,
    LLMRequest,
    LLMResponse,
    RequestStatus,
    Session,
    SessionStatus,
)
from harness.core.errors import InvalidIdentifier, InvalidInput, SessionBusy, SessionNotFound
from harness.providers.base import LLMProvider
from harness.providers.registry import ProviderFactory
from harness.storage import repositories as repo
from harness.storage.database import transaction
from harness.storage.locks import SessionLock


def parse_session_id(raw: str) -> UUID:
    """Accept only a full, canonical UUID: no prefixes, braces or URN forms."""
    try:
        value = UUID(raw)
    except ValueError, AttributeError, TypeError:
        raise InvalidIdentifier(f"{raw!r} is not a valid session identifier") from None
    if str(value) != raw.lower():
        raise InvalidIdentifier(f"{raw!r} is not a valid session identifier")
    return value


class SessionService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_dir: Path,
        provider_factory: ProviderFactory,
        default_provider: str,
        timeout_s: float,
    ) -> None:
        self._conn = conn
        self._data_dir = data_dir
        self._provider_factory = provider_factory
        self._default_provider = default_provider
        self._timeout_s = timeout_s

    # -- recovery ---------------------------------------------------------------------------

    def recover(self) -> list[UUID]:
        """Mark as uncertain the requests whose owner process is gone. Never resends."""
        recovered: list[UUID] = []
        for session_id, request_ids in repo.in_flight_requests(self._conn).items():
            lock = SessionLock(self._data_dir, session_id)
            if not lock.acquire():
                continue  # a live process still owns this session
            try:
                with transaction(self._conn):
                    for request_id in request_ids:
                        repo.set_request_status(
                            self._conn,
                            request_id,
                            RequestStatus.UNCERTAIN,
                            error_code="interrupted",
                        )
                        repo.insert_audit(
                            self._conn,
                            event_type="request.status",
                            outcome=RequestStatus.UNCERTAIN.value,
                            actor="recovery",
                            session_id=session_id,
                            request_id=request_id,
                        )
                    repo.set_session_status(self._conn, session_id, SessionStatus.UNCERTAIN)
                recovered.extend(request_ids)
            finally:
                lock.release()
        return recovered

    # -- sessions ---------------------------------------------------------------------------

    def create_session(self, name: str, project_id: str | None = None) -> Session:
        if not name.strip():
            raise InvalidInput("the session name must not be empty")
        self._provider_factory(self._default_provider)  # must exist before anything is stored
        now = datetime.now(UTC)
        session = Session(
            session_id=uuid7(),
            name=name.strip(),
            project_id=project_id or None,
            provider=self._default_provider,
            status=SessionStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
        with transaction(self._conn):
            repo.insert_session(self._conn, session)
            repo.insert_audit(
                self._conn,
                event_type="session.created",
                outcome="ok",
                actor="cli",
                session_id=session.session_id,
            )
        return session

    def list_sessions(self) -> list[Session]:
        return repo.list_sessions(self._conn)

    def history(self, raw_session_id: str) -> list[HistoryEntry]:
        session = self._require_session(raw_session_id)
        return repo.history(self._conn, session.session_id)

    def _require_session(self, raw_session_id: str) -> Session:
        session_id = parse_session_id(raw_session_id)
        session = repo.get_session(self._conn, session_id)
        if session is None:
            raise SessionNotFound(f"session {session_id} does not exist")
        return session

    # -- asking -----------------------------------------------------------------------------

    async def ask(self, raw_session_id: str, prompt: str) -> LLMResponse:
        session = self._require_session(raw_session_id)
        if not prompt.strip():
            raise InvalidInput("the prompt must not be empty")
        self._provider_factory(self._default_provider)  # a misconfigured provider stops here
        provider = self._provider_factory(session.provider)
        lock = SessionLock(self._data_dir, session.session_id)
        if not lock.acquire():
            raise SessionBusy(f"session {session.session_id} already has a question in progress")
        try:
            return await self._ask_locked(session.session_id, provider, prompt)
        finally:
            lock.release()

    async def _ask_locked(
        self, session_id: UUID, provider: LLMProvider, prompt: str
    ) -> LLMResponse:
        session = repo.get_session(self._conn, session_id)
        assert session is not None
        warnings: tuple[str, ...] = ()
        if session.status is SessionStatus.UNCERTAIN:
            warnings = (
                "this session has an earlier uncertain request; it was not resent "
                "and stays in the history",
            )

        request = LLMRequest(
            request_id=uuid7(), session_id=session_id, prompt=prompt, timeout_s=self._timeout_s
        )
        store_content = provider.synthetic_content
        with transaction(self._conn):
            repo.insert_request(self._conn, request.request_id, session_id)
            repo.insert_message(
                self._conn,
                session_id=session_id,
                request_id=request.request_id,
                role="user",
                content=prompt if store_content else None,
            )
            self._audit(request, RequestStatus.PENDING)

        sent = False

        def on_sent() -> None:
            nonlocal sent
            if sent:
                return
            sent = True
            with transaction(self._conn):
                repo.set_request_status(self._conn, request.request_id, RequestStatus.RUNNING)
                self._audit(request, RequestStatus.RUNNING)

        started = time.monotonic()

        def finish(
            status: RequestStatus,
            *,
            text: str | None = None,
            error_code: str | None = None,
            detail: str | None = None,
        ) -> LLMResponse:
            duration_ms = int((time.monotonic() - started) * 1000)
            with transaction(self._conn):
                if text is not None:
                    repo.insert_message(
                        self._conn,
                        session_id=session_id,
                        request_id=request.request_id,
                        role="assistant",
                        content=text if store_content else None,
                    )
                repo.set_request_status(
                    self._conn,
                    request.request_id,
                    status,
                    error_code=error_code,
                    duration_ms=duration_ms,
                )
                if status is RequestStatus.COMPLETED:
                    repo.set_session_status(self._conn, session_id, SessionStatus.ACTIVE)
                elif status is RequestStatus.UNCERTAIN:
                    repo.set_session_status(self._conn, session_id, SessionStatus.UNCERTAIN)
                self._audit(request, status)
            return LLMResponse(
                request_id=request.request_id,
                session_id=session_id,
                status=status,
                text=text,
                duration_ms=duration_ms,
                detail=detail,
                warnings=warnings,
            )

        try:
            async with asyncio.timeout(self._timeout_s):
                text = await provider.ask(request, on_sent)
        except TimeoutError:
            if sent:
                return finish(
                    RequestStatus.UNCERTAIN,
                    error_code="timeout_after_send",
                    detail="the deadline expired after the prompt was sent; "
                    "it may have reached the provider and was not resent",
                )
            return finish(
                RequestStatus.TIMEOUT,
                error_code="timeout_before_send",
                detail="the deadline expired before the prompt was sent",
            )
        except asyncio.CancelledError:
            # Ctrl+C or cancellation: record what is known, then let the interruption continue.
            if sent:
                finish(RequestStatus.UNCERTAIN, error_code="interrupted")
            else:
                finish(RequestStatus.FAILED, error_code="interrupted_before_send")
            raise
        except Exception as exc:
            return finish(
                RequestStatus.FAILED,
                error_code=type(exc).__name__,
                detail=f"the provider reported an error: {exc}",
            )
        return finish(RequestStatus.COMPLETED, text=text)

    def _audit(self, request: LLMRequest, status: RequestStatus) -> None:
        repo.insert_audit(
            self._conn,
            event_type="request.status",
            outcome=status.value,
            actor="cli",
            session_id=request.session_id,
            request_id=request.request_id,
        )
