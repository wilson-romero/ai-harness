"""Typed contracts shared by storage, providers and the CLI."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class SessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    AUTHENTICATION_REQUIRED = "authentication_required"
    UNCERTAIN = "uncertain"
    CLOSED = "closed"


class RequestStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    AUTHENTICATION_REQUIRED = "authentication_required"
    UNCERTAIN = "uncertain"


IN_FLIGHT = (RequestStatus.PENDING, RequestStatus.RUNNING)


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Session(_Contract):
    session_id: UUID
    name: str
    project_id: str | None = None
    provider: str
    remote_ref: str | None = None
    status: SessionStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the session name must not be empty")
        return value


class LLMRequest(_Contract):
    request_id: UUID
    session_id: UUID
    prompt: str = Field(min_length=1)
    timeout_s: float = Field(gt=0)
    # The session's remote conversation, if a provider bound one, and how many of the
    # session's requests completed (design D5).
    remote_ref: str | None = None
    completed_turns: int = Field(default=0, ge=0)


class LLMResponse(_Contract):
    request_id: UUID
    session_id: UUID
    status: RequestStatus
    text: str | None = None
    duration_ms: int = Field(ge=0)
    detail: str | None = None
    warnings: tuple[str, ...] = ()


class HistoryEntry(_Contract):
    request_id: UUID
    request_status: RequestStatus
    role: str
    content: str | None
    created_at: AwareDatetime
