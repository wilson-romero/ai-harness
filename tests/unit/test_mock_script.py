"""Scripted answers of the Mock and the skill settings (skill-engine D12, D15)."""

import asyncio
import json
from uuid import uuid7

import pytest

from harness.core.contracts import LLMRequest
from harness.core.errors import InvalidInput
from harness.providers.mock import MockProvider, load_responses
from harness.skills.config import DEFAULT_APPROVAL_TTL_S, load_skill_settings


def _ask(provider: MockProvider, prompt: str) -> str:
    request = LLMRequest(request_id=uuid7(), session_id=uuid7(), prompt=prompt, timeout_s=5)
    return asyncio.run(provider.ask(request, lambda: None))


def _write(tmp_path, content) -> str:
    path = tmp_path / "responses.json"
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_answer_chosen_by_the_text_of_the_prompt(tmp_path):
    path = _write(tmp_path, {"tarea: demo-echo/draft": "## Resumen\nok"})
    provider = MockProvider(responses=load_responses(path))
    assert _ask(provider, "intro\ntarea: demo-echo/draft\nresto") == "## Resumen\nok"
    assert _ask(provider, "otra cosa").startswith("[mock ")


def test_first_key_in_alphabetical_order_wins(tmp_path):
    path = _write(tmp_path, {"zeta": "Z", "alfa": "A"})
    provider = MockProvider(responses=load_responses(path))
    assert _ask(provider, "zeta y alfa") == "A"


def test_failure_behaviours_still_win(tmp_path):
    path = _write(tmp_path, {"x": "y"})
    provider = MockProvider("fail", responses=load_responses(path))
    request = LLMRequest(request_id=uuid7(), session_id=uuid7(), prompt="x", timeout_s=5)
    with pytest.raises(Exception, match="configured to fail"):
        asyncio.run(provider.ask(request, lambda: None))


@pytest.mark.parametrize(
    "content",
    [
        ["no", "es", "objeto"],
        {"clave": 3},
        '{"a": "1", "a": "2"}',
        '{"a": NaN}',
        "no es json",
    ],
)
def test_invalid_responses_file(tmp_path, content):
    with pytest.raises(InvalidInput):
        load_responses(_write(tmp_path, content))


def test_responses_file_too_large(tmp_path):
    path = tmp_path / "big.json"
    path.write_text('{"a": "' + "x" * (1024 * 1024) + '"}', encoding="utf-8")
    with pytest.raises(InvalidInput, match="larger than"):
        load_responses(str(path))


def test_responses_file_must_be_absolute_and_exist(tmp_path):
    with pytest.raises(InvalidInput, match="absolute"):
        load_responses("relativo.json")
    with pytest.raises(InvalidInput, match="cannot be read"):
        load_responses(str(tmp_path / "no-existe.json"))


def test_invalid_responses_file_is_a_controlled_cli_error(cli, tmp_path):
    path = _write(tmp_path, ["x"])
    code, _, err = cli("session", "create", "Demo", HARNESS_MOCK_RESPONSES=path)
    assert code == 1 and "HARNESS_MOCK_RESPONSES" in err and "Traceback" not in err


@pytest.mark.parametrize("raw", ["30", "59", "3601", "7200", "abc", "-5", "1.5"])
def test_ttl_out_of_range(raw):
    with pytest.raises(InvalidInput, match="HARNESS_APPROVAL_TTL_S"):
        load_skill_settings({"HARNESS_APPROVAL_TTL_S": raw})


@pytest.mark.parametrize(
    "raw, expected", [("", DEFAULT_APPROVAL_TTL_S), ("60", 60), ("3600", 3600)]
)
def test_ttl_accepted(raw, expected):
    assert DEFAULT_APPROVAL_TTL_S == 900
    assert load_skill_settings({"HARNESS_APPROVAL_TTL_S": raw}).approval_ttl_s == expected


def test_skills_dir_must_be_absolute(tmp_path):
    with pytest.raises(InvalidInput, match="HARNESS_SKILLS_DIR"):
        load_skill_settings({"HARNESS_SKILLS_DIR": "skills"})
    assert load_skill_settings({"HARNESS_SKILLS_DIR": str(tmp_path)}).skills_dir == tmp_path
    default = load_skill_settings({}).skills_dir
    assert default.name == "skills" and (default.parent / "harness").is_dir()


def test_a_responses_file_written_by_windows_powershell_loads(tmp_path):
    """`Set-Content -Encoding utf8` in Windows PowerShell 5.1 writes a BOM, and CRLF line
    ends: the file loads like every UTF-8 file the harness reads (read_text_limited drops a
    BOM). What 5.1's ConvertTo-Json makes of `(Get-Content -Raw)`, an object, is refused."""
    path = tmp_path / "respuestas.json"
    path.write_bytes('\ufeff{\r\n  "tarea: x": "línea\\nsegunda"\r\n}\r\n'.encode())
    assert load_responses(str(path)) == {"tarea: x": "línea\nsegunda"}
    path.write_text('{"tarea: x": {"value": "texto", "PSPath": "C:\\\\x"}}', encoding="utf-8")
    with pytest.raises(InvalidInput, match="non-empty texts to texts"):
        load_responses(str(path))
