"""The grammar of a conversation line (interactive-shell D3): `/` is a command, the rest a question."""

import time

import pytest

from harness.shell.parser import COMMANDS, Command, Empty, LineError, Question, parse_line


@pytest.mark.parametrize("line", ["/help", "/exit", "/status", "/sessions", "/history",
                                  "/context", "/help   ", "  /help"])
def test_known_command(line):
    """Scenario «Comando conocido»: the line is a command, never a question."""
    parsed = parse_line(line)
    assert isinstance(parsed, Command)
    assert parsed.name == line.strip()[1:]
    assert parsed.args == ()


@pytest.mark.parametrize("line", ["/nada", "/exti", "/Help", "/", "/ help", "/help!",
                                  "  /nada x", "/he\x1b[31mlp"])
def test_unknown_command_is_an_error_not_a_question(line):
    """Scenario «Comando desconocido»: a mistyped command is never sent to the provider."""
    with pytest.raises(LineError):
        parse_line(line)


@pytest.mark.parametrize("line", ["/help extra", "/exit now", "/resume", "/resume 1 2",
                                  "/file", "/file a b", "/memory", "/skill", "/context x"])
def test_wrong_number_of_arguments_is_an_error(line):
    with pytest.raises(LineError):
        parse_line(line)


def test_unknown_command_message_names_help():
    with pytest.raises(LineError) as refused:
        parse_line("/nada")
    assert "/help" in str(refused.value)


@pytest.mark.parametrize(("line", "sent"), [
    ("//ruta/de/ejemplo es correcta?", "/ruta/de/ejemplo es correcta?"),
    ("//", "/"),
    ("  //help", "/help"),
])
def test_a_question_that_starts_with_a_slash(line, sent):
    """Scenario «Pregunta que empieza por barra»."""
    parsed = parse_line(line)
    assert parsed == Question(sent)


@pytest.mark.parametrize("line", ["​/exit", "﻿/exit", " ​ ⁠/exit",
                                  "​​/exit "])
def test_an_invisible_character_before_the_slash_does_not_make_a_question(line):
    """Review 2026-11-25: a zero-width space pasted before `/exit` must not send `/exit`."""
    assert parse_line(line) == Command("exit", ())


@pytest.mark.parametrize("line", ["", "   ", "\t", "\n", " \r\n", "​", "﻿ ​"])
def test_empty_line(line):
    """Scenario «Línea vacía»: nothing to send and nothing to run."""
    assert parse_line(line) == Empty()


def test_a_normal_line_is_a_question_as_typed():
    assert parse_line("¿Qué es una ADR?") == Question("¿Qué es una ADR?")
    assert parse_line("a / b") == Question("a / b")


def test_line_end_is_not_part_of_the_question():
    assert parse_line("hola\r\n") == Question("hola")


@pytest.mark.parametrize(("line", "args"), [
    ('/memory adr decisiones', ("adr", "decisiones")),
    ('/memory "dos palabras" otra', ("dos palabras", "otra")),
    ('/file "carpeta con espacios/nota.md"', ("carpeta con espacios/nota.md",)),
    ('/skill architecture-memory tema="un tema" --file notas=a.md',
     ("architecture-memory", "tema=un tema", "--file", "notas=a.md")),
    ('/new --project demo-alpha "Sesión nueva"', ("--project", "demo-alpha", "Sesión nueva")),
    ('/resume 2', ("2",)),
    ('/memory ""', ("",)),
])
def test_arguments_and_double_quotes(line, args):
    parsed = parse_line(line)
    assert isinstance(parsed, Command)
    assert parsed.args == args


def test_unbalanced_quote_is_an_error():
    with pytest.raises(LineError):
        parse_line('/memory "sin cerrar')


def test_every_command_of_d10_and_nothing_else():
    assert set(COMMANDS) == {"help", "status", "new", "sessions", "resume", "history",
                             "memory", "context", "skill", "file", "exit",
                             "mode"}  # response-mode, 2026-11-27


def test_parsing_is_linear():
    started = time.monotonic()
    for line in ('/memory ' + '"a" ' * (1 << 17), "/" + "x" * (1 << 20), '/memory "' * (1 << 18),
                 "/memory " + " " * (1 << 20) + "x"):
        try:
            parse_line(line)
        except LineError:
            pass
    assert time.monotonic() - started < 5.0
