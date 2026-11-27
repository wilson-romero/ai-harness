"""The text of every SQL statement in product code is fixed in the source (sqlmodel-persistence D9).

Values reach the database as parameters, never as part of the statement. This test reads the
syntax tree of `harness/` and `main.py` and, for every call to a SQL method (`SQL_METHODS`,
whatever object it is called on), requires the statement to be *literal SQL*:

- a string literal (adjacent literals are one literal for Python);
- `a + b`, where `a` and `b` are literal SQL;
- a name bound exactly once in the same module, at module level, to literal SQL, and bound
  nowhere else in that module (no assignment in a function, loop, `with`, import or `global`).

Everything else is refused: f-strings, `%`, `.format`, `str.join`, function calls, attributes,
locals, parameters, subscripts. A SQL method may not be referenced without calling it
(`run = conn.execute`, `getattr(conn, "execute")`, `partial(conn.execute, ...)`), so the rule
cannot be dodged with an alias. A call must name its statement (positionally or as `sql`); `*args`
is refused. The one exception, with its reason, is `EXEMPT`.

Known limits: another module can still rebind a constant (`engine._HALF_DONE = ...`) or reach a
method through `getattr` with a computed name; `operator.methodcaller` and C extensions are not
followed; `scripts/` and `tests/` are not checked.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SQL_METHODS = frozenset({"execute", "executemany", "executescript", "exec_driver_sql"})
# (file, enclosing function, method): why the statement is not literal.
EXEMPT = {
    ("harness/storage/database.py", "migrate", "executescript"):
        "runs the numbered migration files shipped inside the package",
}


def _bound_names(tree: ast.AST) -> Counter[str]:
    """How many times each name is bound anywhere in the module."""
    bound: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound[node.id] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound[node.name] += 1
        elif isinstance(node, ast.alias):
            bound[(node.asname or node.name).split(".")[0]] += 1
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                bound[name] += 2  # a function may rebind it
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound[node.name] += 1
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound[node.rest] += 1
    return bound


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    bound = _bound_names(tree)
    constants: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name) and bound[target.id] == 1:
            constants[target.id] = value
    return constants


def _is_literal_sql(node: ast.expr, constants: dict[str, ast.expr], seen: frozenset[str]) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_is_literal_sql(node.left, constants, seen)
                and _is_literal_sql(node.right, constants, seen))
    if isinstance(node, ast.Name) and node.id in constants and node.id not in seen:
        return _is_literal_sql(constants[node.id], constants, seen | {node.id})
    return False


def _statement(call: ast.Call) -> ast.expr | None:
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg in ("sql", "sql_script", "statement"):
            return keyword.value
    return None


def find_violations(source: str, relative: str) -> list[str]:
    """Each place in `source` where SQL is not literal, as `file:line: reason`."""
    tree = ast.parse(source, filename=relative)
    constants = _module_constants(tree)
    called: set[int] = set()
    found: list[str] = []

    def visit(node: ast.AST, function: str | None) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in SQL_METHODS:
                called.add(id(func))
                statement = _statement(node)
                if (relative, function, func.attr) in EXEMPT:
                    pass
                elif statement is None:
                    found.append(f"{relative}:{node.lineno}: {func.attr} without a named statement")
                elif not _is_literal_sql(statement, constants, frozenset()):
                    found.append(f"{relative}:{node.lineno}: {func.attr} with non-literal SQL: "
                                 f"{ast.unparse(statement)[:80]}")
            elif (isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) >= 2
                  and isinstance(node.args[1], ast.Constant) and node.args[1].value in SQL_METHODS):
                found.append(f"{relative}:{node.lineno}: getattr of {node.args[1].value}")
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, None)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in SQL_METHODS and id(node) not in called:
            found.append(f"{relative}:{node.lineno}: {node.attr} referenced without being called")
    return sorted(found)


def _product_files() -> list[Path]:
    return [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "harness").rglob("*.py"))]


def test_product_sql_is_literal():
    offenders = []
    for path in _product_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        offenders += find_violations(path.read_text(encoding="utf-8"), relative)
    assert offenders == []


def test_the_guard_sees_the_product_statements():
    """The guard is not vacuous: it finds the SQL calls the product makes."""
    calls = 0
    for path in _product_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in SQL_METHODS):
                calls += 1
    assert calls >= 70  # 71 on 2026-11-27


ACCEPTED = {
    "literal": 'conn.execute("SELECT 1 FROM t WHERE a = ?", (a,))',
    "adjacent literals": 'conn.execute("SELECT 1 " "FROM t")',
    "literal plus literal": 'conn.execute("SELECT 1 " + "FROM t")',
    "module constant": 'Q = "SELECT 1"\nconn.execute(Q)',
    "constant built from constants": 'A = "a = 1"\nQ = "SELECT 1 WHERE " + A\nconn.execute(Q)',
    "literal plus constant": 'A = "a = 1"\ndef f(conn):\n    conn.execute("SELECT 1 WHERE " + A)',
    "keyword statement": 'conn.execute(sql="SELECT 1")',
    "annotated constant": 'Q: str = "SELECT 1"\nconn.execute(Q)',
}

REFUSED = {
    "f-string with a variable":
        'def f(conn, name):\n    conn.execute(f"SELECT 1 WHERE name = \'{name}\'")',
    "f-string with a constant only": 'A = "x"\nconn.execute(f"SELECT {A}")',
    "format": 'def f(conn, t):\n    conn.execute("SELECT * FROM {}".format(t))',
    "percent": 'def f(conn, t):\n    conn.execute("SELECT * FROM %s" % t)',
    "plus a parameter": 'def f(conn, t):\n    conn.execute("SELECT * FROM " + t)',
    "plus a local literal": 'def f(conn):\n    t = "x"\n    conn.execute("SELECT * FROM " + t)',
    "name bound to a call": 'Q = make_query()\nconn.execute(Q)',
    "name bound to a join": 'Q = ", ".join(["?"] * 3)\nconn.execute("SELECT " + Q)',
    "constant rebound in a function":
        'Q = "SELECT 1"\ndef f():\n    global Q\n    Q = input()\nconn.execute(Q)',
    "constant bound twice": 'Q = "SELECT 1"\nQ = input()\nconn.execute(Q)',
    "constant rebound by a loop": 'Q = "SELECT 1"\nfor Q in rows: pass\nconn.execute(Q)',
    "constant rebound by an import": 'Q = "SELECT 1"\nfrom m import x as Q\nconn.execute(Q)',
    "attribute": 'conn.execute(self.sql)',
    "subscript": 'conn.execute(queries["x"])',
    "star args": 'conn.execute(*args)',
    "no statement": 'conn.execute()',
    "alias of the method": 'def f(conn, t):\n    run = conn.execute\n    run(t)',
    "alias kept on an object": 'self._run = conn.execute',
    "getattr": 'def f(conn, t):\n    getattr(conn, "execute")(t)',
    "partial": 'run = functools.partial(conn.executescript)',
    "cursor execute with a variable": 'def f(conn, t):\n    conn.cursor().execute(t)',
    "executemany with a variable": 'def f(conn, t, rows):\n    conn.executemany(t, rows)',
    "executescript with a variable": 'def f(conn, t):\n    conn.executescript(t)',
    "exec_driver_sql with a variable": 'def f(conn, t):\n    conn.exec_driver_sql(t)',
    "bytes literal": 'conn.execute(b"SELECT 1")',
}


@pytest.mark.parametrize("source", ACCEPTED.values(), ids=ACCEPTED.keys())
def test_the_guard_accepts_literal_sql(source):
    assert find_violations(source, "synthetic.py") == []


@pytest.mark.parametrize("source", REFUSED.values(), ids=REFUSED.keys())
def test_the_guard_refuses_built_sql(source):
    assert find_violations(source, "synthetic.py") != []


def test_the_exemption_is_only_the_migration_runner():
    source = "def other(conn, path):\n    conn.executescript(path.read_text())"
    assert find_violations(source, "harness/storage/database.py") != []
