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
from harness.core.errors import (
    InvalidIdentifier,
    InvalidInput,
    InvalidProject,
    ProjectMismatch,
    SessionBusy,
    SessionNotFound,
)
from harness.memory.context import ProjectContext, compose_prompt
from harness.memory.paths import validate_project_slug
from harness.providers.base import LLMProvider
from harness.providers.registry import ProviderFactory
from harness.storage import repositories as repo
from harness.storage.database import transaction
from harness.storage.locks import SessionLock


def is_valid_unicode(text: str) -> bool:
    """False when the text holds a lone surrogate (for example, invalid bytes in argv), which
    cannot be encoded as UTF-8, stored in SQLite or sent (skill-engine review 8.6)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


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
        if not is_valid_unicode(name):
            raise InvalidInput("the session name is not valid Unicode text")
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

    def check_project_question(self, raw_session_id: str, prompt: str, project: str) -> None:
        """Refuse a question with project memory before the vault is read (D7).

        The session and the prompt are checked first, as for any question (nothing is
        recorded if they fail). Then the project: a valid identifier, and exactly the one the
        session was created with, because a remote conversation remembers what it was sent and
        two projects must never meet in one session. A refused project leaves a
        `memory.context denied` audit event, without paths or text.
        """
        session = self._require_session(raw_session_id)
        if not prompt.strip():
            raise InvalidInput("the prompt must not be empty")
        try:
            validate_project_slug(project)
        except InvalidProject:
            self._deny(session.session_id)
            raise
        self._check_project(session, project)

    def deny_project_question(self, raw_session_id: str) -> None:
        """Record the refusal of a question with project memory refused after the checks."""
        self._deny(self._require_session(raw_session_id).session_id)

    def _deny(self, session_id: UUID) -> None:
        with transaction(self._conn):
            repo.insert_audit(
                self._conn,
                event_type="memory.context",
                outcome="denied",
                actor="cli",
                session_id=session_id,
            )

    def _check_project(self, session: Session, project: str) -> None:
        if session.project_id == project:
            return
        self._deny(session.session_id)
        if session.project_id is None:
            raise ProjectMismatch(
                f"session {session.session_id} has no project; "
                "create a session with --project to ask with project memory"
            )
        raise ProjectMismatch(
            f"session {session.session_id} belongs to another project; "
            "use the project it was created with, or another session"
        )

    async def ask(
        self, raw_session_id: str, prompt: str, context: ProjectContext | None = None
    ) -> LLMResponse:
        """Ask a question. With `context`, the memory block goes before it but is never stored."""
        session = self._require_session(raw_session_id)
        if not prompt.strip():
            raise InvalidInput("the prompt must not be empty")
        if not is_valid_unicode(prompt):
            raise InvalidInput("the prompt is not valid Unicode text (it has a lone surrogate)")
        if context is not None:
            self._check_project(session, context.project)
        self._provider_factory(self._default_provider)  # a misconfigured provider stops here
        provider = self._provider_factory(session.provider)
        lock = SessionLock(self._data_dir, session.session_id)
        if not lock.acquire():
            raise SessionBusy(f"session {session.session_id} already has a question in progress")
        try:
            return await self._ask_locked(session.session_id, provider, prompt, context)
        finally:
            lock.release()

    def require_session(self, raw_session_id: str) -> Session:
        return self._require_session(raw_session_id)

    def provider_for(self, session: Session) -> LLMProvider:
        """The provider of a session, after checking the configured one exists."""
        self._provider_factory(self._default_provider)
        return self._provider_factory(session.provider)

    async def ask_with_lock_held(
        self,
        session_id: UUID,
        provider: LLMProvider,
        prompt: str,
        context: ProjectContext | None = None,
        *,
        stored_text: str,
        timeout_s: float,
    ) -> LLMResponse:
        """A question from a caller that already holds the session lock (skill-engine D7).

        Same states, deadline and no-resend rules as `ask`. `stored_text` is what the history
        keeps as the question (when the provider is synthetic) instead of `prompt`.
        """
        return await self._ask_locked(
            session_id, provider, prompt, context, stored_text=stored_text, timeout_s=timeout_s
        )

    async def _ask_locked(
        self,
        session_id: UUID,
        provider: LLMProvider,
        prompt: str,
        context: ProjectContext | None = None,
        *,
        stored_text: str | None = None,
        timeout_s: float | None = None,
    ) -> LLMResponse:
        deadline_s = self._timeout_s if timeout_s is None else timeout_s
        session = repo.get_session(self._conn, session_id)
        assert session is not None
        warnings: tuple[str, ...] = ()
        if session.status is SessionStatus.UNCERTAIN:
            warnings = (
                "this session has an earlier uncertain request; it was not resent "
                "and stays in the history",
            )

        # The provider receives the memory block and the question; only the question is ever
        # stored, and only when the provider's content is synthetic (D7).
        sent_text = compose_prompt(context, prompt) if context is not None else prompt
        request = LLMRequest(
            request_id=uuid7(), session_id=session_id, prompt=sent_text, timeout_s=deadline_s
        )
        store_content = provider.synthetic_content
        question = prompt if stored_text is None else stored_text
        with transaction(self._conn):
            repo.insert_request(self._conn, request.request_id, session_id)
            repo.insert_message(
                self._conn,
                session_id=session_id,
                request_id=request.request_id,
                role="user",
                content=question if store_content else None,
            )
            if context is not None:
                for note in context.included:
                    repo.insert_request_context(
                        self._conn,
                        request_id=request.request_id,
                        note_path=note.relative,
                        sha256=note.sha256,
                        size_bytes=note.size,
                        truncated=note.truncated,
                    )
                repo.insert_audit(
                    self._conn,
                    event_type="memory.context",
                    outcome="ok",
                    actor="cli",
                    session_id=session_id,
                    request_id=request.request_id,
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
            async with asyncio.timeout(deadline_s):
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
        if not is_valid_unicode(text):
            # The answer arrived but cannot be stored or shown: a controlled failure (8.6).
            return finish(
                RequestStatus.FAILED,
                error_code="invalid_text",
                detail="the provider's answer is not valid Unicode text; it was not kept",
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
