"""`read_plan_reply` on its own (independent review of `6b83412`, point 3): each of its two
conditions refuses by itself, and `read_plan` is never reached for such a reply."""

from __future__ import annotations

from uuid import uuid7

import pytest

import harness.mcp.plan as plan_module
from harness.core.contracts import LLMResponse, RequestStatus
from harness.mcp.plan import Plan, Refusal, read_plan_reply
from tests.plan_support import ALPHA, McpList, plan_reply

NONCE = "0123456789abcdef"


@pytest.fixture
def config(tmp_path):
    return McpList(tmp_path / "mcp").load()


def _response(status: RequestStatus, text: str | None, truncated: bool = False) -> LLMResponse:
    return LLMResponse(request_id=uuid7(), session_id=uuid7(), status=status, text=text,
                       duration_ms=1, truncated=truncated)


@pytest.fixture
def never_read(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(plan_module, "read_plan", lambda text, **_: seen.append(text))
    return seen


VALID = plan_reply(ALPHA, nonce=NONCE)


@pytest.mark.parametrize("status", [RequestStatus.UNCERTAIN, RequestStatus.FAILED,
                                    RequestStatus.TIMEOUT])
def test_a_reply_that_did_not_complete_is_refused_even_with_a_valid_text(config, never_read,
                                                                         status):
    reading = read_plan_reply(_response(status, VALID), nonce=NONCE, config=config)
    assert isinstance(reading, Refusal) and reading.reason == "reply_not_completed"
    assert never_read == []


def test_a_completed_reply_with_no_text_is_refused(config, never_read):
    reading = read_plan_reply(_response(RequestStatus.COMPLETED, None), nonce=NONCE,
                              config=config)
    assert isinstance(reading, Refusal) and reading.reason == "reply_not_completed"
    assert never_read == []


def test_a_truncated_reply_is_refused_even_with_a_valid_text(config, never_read):
    reading = read_plan_reply(_response(RequestStatus.COMPLETED, VALID, truncated=True),
                              nonce=NONCE, config=config)
    assert isinstance(reading, Refusal) and reading.reason == "reply_truncated"
    assert never_read == []


def test_control_the_same_text_completed_whole_is_a_plan(config):
    reading = read_plan_reply(_response(RequestStatus.COMPLETED, VALID), nonce=NONCE,
                              config=config)
    assert isinstance(reading, Plan)
