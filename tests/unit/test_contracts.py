from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import ValidationError

from harness.core.contracts import LLMRequest, LLMResponse, RequestStatus, Session, SessionStatus


def _session(**overrides):
    now = datetime.now(UTC)
    fields = {
        "session_id": uuid7(),
        "name": "Synthetic",
        "provider": "mock",
        "status": SessionStatus.CREATED,
        "created_at": now,
        "updated_at": now,
    }
    return Session(**(fields | overrides))


def test_contracts_build_with_valid_data():
    session = _session()
    request = LLMRequest(
        request_id=uuid7(), session_id=session.session_id, prompt="hello", timeout_s=1
    )
    response = LLMResponse(
        request_id=request.request_id,
        session_id=session.session_id,
        status=RequestStatus.COMPLETED,
        text="hi",
        duration_ms=3,
    )
    assert response.status is RequestStatus.COMPLETED


def test_status_outside_the_enumeration_is_rejected():
    with pytest.raises(ValidationError):
        _session(status="paused")
    with pytest.raises(ValidationError):
        LLMResponse(request_id=uuid7(), session_id=uuid7(), status="done", duration_ms=0)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValidationError):
        _session(created_at=datetime(2026, 11, 24, 9, 0))


def test_blank_name_and_empty_prompt_are_rejected():
    with pytest.raises(ValidationError):
        _session(name="   ")
    with pytest.raises(ValidationError):
        LLMRequest(request_id=uuid7(), session_id=uuid7(), prompt="", timeout_s=1)
