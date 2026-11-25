"""The decision writer and its reconciliation, on a copy of the synthetic vault (D3, D6, D7)."""

from __future__ import annotations

import hashlib
import os

import pytest

from harness.memory import decisions
from harness.memory.context import build_context
from harness.memory.decisions import (
    DecisionRefused,
    reconcile_decision,
    temp_name_for,
    write_decision,
)
from harness.memory.paths import walk_vault
from tests.conftest import fingerprint, make_symlink

IDENT = "dec-b20925399f56d81f"
NAME = "2026-11-20-cola-gestionada-para-eventos-de-ventas-b2092539.md"
TEMP = temp_name_for("01900000-0000-7000-8000-000000000001", "save")
NOTE = (
    "---\ntype: decision\ndecision_id: dec-b20925399f56d81f\nproject_slug: demo-alpha\n"
    "status: accepted\ncreated: 2026-11-20\nupdated: 2026-11-20\ntags: [decision, demo-alpha]\n"
    "source: ai-harness\nskill: architecture-memory@1.0.0\nrun_id: x\n---\n# Cola\n\nTexto.\n"
).encode()
SHA = hashlib.sha256(NOTE).hexdigest()


def entries(vault):
    """The fingerprint, but a directory only by its presence: writing a temporary file in
    it and removing it again changes its mtime and nothing else."""
    return {k: (v[0],) if v[0] == "dir" else v for k, v in fingerprint(vault).items()}


def _root(vault):
    return vault.resolve(strict=True)


def test_one_new_file_and_nothing_else(vault):
    before = fingerprint(vault)
    relative = write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    after = fingerprint(vault)
    assert relative == f"Decisiones/{NAME}"
    assert set(after) - set(before) == {relative}
    assert {k: v for k, v in after.items() if k in before and k != "Decisiones"} == {
        k: v for k, v in before.items() if k != "Decisiones"}
    assert (vault / relative).read_bytes() == NOTE
    assert os.lstat(vault / relative).st_nlink == 1


def test_occupied_destination_is_never_replaced(vault, monkeypatch):
    target = vault / "Decisiones" / NAME
    original = decisions._publish

    def someone_writes_first(root, temp, final, identity):
        final.write_bytes(b"nota de otra persona\n")
        return original(root, temp, final, identity)

    monkeypatch.setattr(decisions, "_publish", someone_writes_first)
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "conflict"
    assert target.read_bytes() == b"nota de otra persona\n"
    assert not (vault / "Decisiones" / TEMP).exists()


def test_existing_name_before_writing_is_a_conflict(vault):
    (vault / "Decisiones" / NAME).write_bytes(b"otra\n")
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "conflict"
    assert (vault / "Decisiones" / NAME).read_bytes() == b"otra\n"


def test_same_identifier_under_another_name_is_a_duplicate(vault):
    (vault / "Decisiones" / "a-mano.md").write_bytes(NOTE)
    before = fingerprint(vault)
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "duplicate_decision" and "a-mano.md" in str(caught.value)
    assert fingerprint(vault) == before


def test_decisiones_created_at_the_first_approved_write(vault):
    for entry in (vault / "Decisiones").iterdir():
        entry.unlink()
    (vault / "Decisiones").rmdir()
    before = fingerprint(vault)
    write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert set(fingerprint(vault)) - set(before) == {"Decisiones", f"Decisiones/{NAME}"}


def test_decisiones_as_a_link_to_outside_is_refused(vault, tmp_path):
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "existente.md").write_text("fuera\n", encoding="utf-8")
    for entry in (vault / "Decisiones").iterdir():
        entry.unlink()
    (vault / "Decisiones").rmdir()
    make_symlink(vault / "Decisiones", outside)
    outside_before = fingerprint(outside)
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "unsafe_target"
    assert fingerprint(outside) == outside_before
    assert reconcile_decision(_root(vault), IDENT, SHA, TEMP) == "conflict"


def test_a_folder_named_in_another_case_is_refused(vault):
    (vault / "Decisiones").rename(vault / "decisiones-tmp")
    (vault / "decisiones-tmp").rename(vault / "decisiones")
    before = fingerprint(vault)
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "unsafe_target"
    assert fingerprint(vault) == before


def test_a_file_system_without_hard_links_fails_without_writing(vault, monkeypatch):
    def no_links(src, dst, **kwargs):
        raise PermissionError("hard links are not supported here")

    monkeypatch.setattr(decisions.os, "link", no_links)
    before = entries(vault)
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "write_failed"
    assert entries(vault) == before


def test_unsafe_names_are_refused_before_anything(vault):
    before = fingerprint(vault)
    for name, temp in [("../fuera.md", TEMP), ("con.md", TEMP), (".oculta.md", TEMP),
                       (NAME, "visible.tmp"), (NAME, "../.harness-x.tmp")]:
        with pytest.raises(DecisionRefused):
            write_decision(_root(vault), name, NOTE, temp, IDENT)
    assert fingerprint(vault) == before


def test_a_leftover_temporary_file_is_invisible_to_the_memory(vault):
    (vault / "Decisiones" / TEMP).write_bytes(NOTE)
    walked = walk_vault(_root(vault))
    assert all(TEMP not in f.relative for f in walked.files)
    assert (f"Decisiones/{TEMP}", "hidden") in walked.skipped
    context = build_context(_root(vault), "demo-alpha", 64_000)
    assert TEMP not in context.text


def test_a_note_with_two_links_is_invisible_until_reconciled(vault):
    """A death between the link and the removal of the temporary file (D6, step 6)."""
    folder = vault / "Decisiones"
    (folder / TEMP).write_bytes(NOTE)
    os.link(folder / TEMP, folder / NAME)
    walked = walk_vault(_root(vault))
    assert (f"Decisiones/{NAME}", "hard-link") in walked.skipped
    assert reconcile_decision(_root(vault), IDENT, SHA, TEMP) == "applied"
    assert not (folder / TEMP).exists() and os.lstat(folder / NAME).st_nlink == 1
    assert any(f.relative == f"Decisiones/{NAME}" for f in walk_vault(_root(vault)).files)


def test_reconcile_absent_applied_and_conflict(vault):
    root = _root(vault)
    assert reconcile_decision(root, IDENT, SHA, TEMP) == "absent"
    (vault / "Decisiones" / TEMP).write_bytes(NOTE[:10])  # died before the link
    assert reconcile_decision(root, IDENT, SHA, TEMP) == "absent"
    assert not (vault / "Decisiones" / TEMP).exists()
    write_decision(root, NAME, NOTE, TEMP, IDENT)
    assert reconcile_decision(root, IDENT, SHA, TEMP) == "applied"
    assert reconcile_decision(root, IDENT, "0" * 64, TEMP) == "conflict"
    assert reconcile_decision(root, "not-an-id", SHA, TEMP) == "conflict"


def test_reconcile_without_decisiones_is_absent_and_creates_nothing(vault):
    for entry in (vault / "Decisiones").iterdir():
        entry.unlink()
    (vault / "Decisiones").rmdir()
    before = fingerprint(vault)
    assert reconcile_decision(_root(vault), IDENT, SHA, TEMP) == "absent"
    assert fingerprint(vault) == before


def test_reconcile_never_removes_a_link_in_place_of_its_temporary_file(vault, tmp_path):
    victim = tmp_path / "victima.txt"
    victim.write_text("no tocar\n", encoding="utf-8")
    make_symlink(vault / "Decisiones" / TEMP, victim)
    reconcile_decision(_root(vault), IDENT, SHA, TEMP)
    assert victim.read_text(encoding="utf-8") == "no tocar\n"
    assert (vault / "Decisiones" / TEMP).is_symlink()


def test_the_temporary_name_is_hidden_and_legal():
    assert TEMP.startswith(".harness-") and TEMP.endswith(".tmp")
    with pytest.raises(ValueError):
        temp_name_for("../x", "save")


# -- 7.1 once the link exists the outcome is "applied" or "uncertain", never "failed" -----------


def _temp_unlink_fails(monkeypatch):
    """`os.unlink` of the harness's temporary file raises, as when another program (a sync
    client, an antivirus) holds it open on Windows; any other unlink works."""
    real = os.unlink

    def unlink(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)).startswith(decisions.TEMP_PREFIX):
            raise PermissionError("the file is in use by another process")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(decisions.os, "unlink", unlink)


def test_a_temporary_file_that_cannot_be_removed_after_the_link_is_uncertain(vault, monkeypatch):
    _temp_unlink_fails(monkeypatch)
    with pytest.raises(decisions.DecisionUncertain):
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    folder = vault / "Decisiones"
    assert (folder / NAME).read_bytes() == NOTE and (folder / TEMP).exists()
    # The note is published with two links: the memory skips it until reconciled.
    assert (f"Decisiones/{NAME}", "hard-link") in walk_vault(_root(vault)).skipped
    # While the temporary file still cannot be removed, reconcile says so and changes nothing.
    assert reconcile_decision(_root(vault), IDENT, SHA, TEMP) == "blocked"
    monkeypatch.undo()
    assert reconcile_decision(_root(vault), IDENT, SHA, TEMP) == "applied"
    assert not (folder / TEMP).exists() and os.lstat(folder / NAME).st_nlink == 1
    assert any(f.relative == f"Decisiones/{NAME}" for f in walk_vault(_root(vault)).files)


def test_a_published_note_that_cannot_be_checked_is_uncertain(vault, monkeypatch):
    real = decisions.Path.lstat
    calls = []

    def lstat(self, *args, **kwargs):
        if self.name == NAME:
            calls.append(self)
            if len(calls) > 1:  # the first one is the check that the name is free
                raise PermissionError("cannot be read now")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(decisions.Path, "lstat", lstat)
    with pytest.raises(decisions.DecisionUncertain):
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    monkeypatch.undo()
    assert (vault / "Decisiones" / NAME).read_bytes() == NOTE


def test_a_published_name_that_is_not_the_file_written_is_uncertain(vault, monkeypatch):
    """The identity check after the link: whatever got the name is not reported as ours."""

    def link_writes_another_file(src, dst, **kwargs):
        with open(dst, "xb") as handle:
            handle.write(b"otro fichero\n")

    monkeypatch.setattr(decisions.os, "link", link_writes_another_file)
    with pytest.raises(decisions.DecisionUncertain):
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    monkeypatch.undo()
    assert (vault / "Decisiones" / NAME).read_bytes() == b"otro fichero\n"
    assert reconcile_decision(_root(vault), IDENT, SHA, TEMP) == "absent"


def test_decisiones_swapped_for_a_link_during_the_write_takes_the_note_back(vault, monkeypatch):
    """Between the checks and the link, `Decisiones/` becomes a link to another folder: the note
    published there is removed again and the write is refused."""
    folder = vault / "Decisiones"
    moved = vault / "Movida"
    real_link = os.link

    def swap_then_link(src, dst, **kwargs):
        folder.rename(moved)
        make_symlink(folder, moved)
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(decisions.os, "link", swap_then_link)
    with pytest.raises(DecisionRefused) as caught:
        write_decision(_root(vault), NAME, NOTE, TEMP, IDENT)
    assert caught.value.code == "unsafe_target"
    assert not (moved / NAME).exists() and not (moved / TEMP).exists()
