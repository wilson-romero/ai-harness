"""The guest-page advice: which path shape is kept and what the person is told to set."""

import json

import pytest

from harness.browser.login import login_path, recorded_ready_path
from harness.browser.page_state import guest_page_advice, ready_path


@pytest.mark.parametrize(
    ("url", "shape"),
    [
        ("https://copilot.example/chat", "/chat"),
        ("https://copilot.example/chat/conversation/0f3a9c?x=1", "/chat"),
        ("https://copilot.example/", "/"),
        ("https://copilot.example", "/"),
        ("https://copilot.example/0f3a9c77/chat", None),  # an id is never kept
        ("https://copilot.example/Tenant42", None),
    ],
)
def test_ready_path_keeps_only_a_plain_first_segment(url, shape):
    assert ready_path(url) == shape


def test_advice_names_the_recorded_chat_path():
    text = guest_page_advice("https://copilot.example/?tenant=abc", "/chat")
    assert "set HARNESS_COPILOT_URL=https://copilot.example/chat" in text
    assert "guest page" in text
    assert "tenant" not in text  # the query string is never repeated


def test_advice_without_a_recorded_path_gives_an_example():
    text = guest_page_advice("https://copilot.example/", None)
    assert "for example https://copilot.example/chat" in text


def test_advice_when_the_recorded_path_is_the_configured_one():
    text = guest_page_advice("https://copilot.example/chat", "/chat")
    assert "set HARNESS_COPILOT_URL=" not in text  # nothing to suggest: no false fix
    assert "for example" in text


def test_recorded_ready_path(tmp_path):
    assert recorded_ready_path(tmp_path) is None
    path = login_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ready_path": "/chat"}), encoding="utf-8")
    assert recorded_ready_path(tmp_path) == "/chat"
    path.write_text("not json", encoding="utf-8")
    assert recorded_ready_path(tmp_path) is None
    path.write_text(json.dumps({"ready_path": "https://elsewhere/"}), encoding="utf-8")
    assert recorded_ready_path(tmp_path) is None
