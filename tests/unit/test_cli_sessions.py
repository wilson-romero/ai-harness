from uuid import UUID, uuid7

from tests.conftest import query


def test_session_created_with_name(cli):
    code, out, _ = cli("session", "create", "Arquitectura WhatsApp")
    assert code == 0
    session_id = out.strip()
    assert str(UUID(session_id)) == session_id

    code, out, _ = cli("session", "list")
    assert code == 0
    (line,) = out.strip().splitlines()
    assert line.split("\t")[:2] == [session_id, "created"]
    assert line.endswith("Arquitectura WhatsApp")


def test_empty_name_is_rejected(cli, data_dir):
    code, out, err = cli("session", "create", "")
    assert code != 0 and out == ""
    assert "name must not be empty" in err
    assert query(data_dir, "SELECT count(*) FROM sessions") == [(0,)]


def test_three_sessions_listed(cli):
    ids = [cli("session", "create", f"S{i}")[1].strip() for i in range(3)]
    code, out, _ = cli("session", "list")
    assert code == 0
    listed = [line.split("\t")[0] for line in out.strip().splitlines()]
    assert sorted(listed) == sorted(ids) and len(listed) == 3


def test_empty_list(cli):
    code, out, err = cli("session", "list")
    assert (code, out.strip(), err) == (0, "No sessions.", "")


def test_malformed_identifier(cli):
    for bad in ("no-es-un-uuid", "01a20dfa", "{01a20dfa-7440-77e2-a029-353641a76512}"):
        code, out, err = cli("history", bad)
        assert code == 1 and out == ""
        assert "not a valid session identifier" in err
        assert "Traceback" not in err


def test_missing_session(cli, data_dir):
    missing = str(uuid7())
    code, out, err = cli("ask", missing, "hello")
    assert code == 1 and out == ""
    assert "does not exist" in err and "Traceback" not in err
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]

    code, _, err = cli("history", missing)
    assert code == 1 and "does not exist" in err
