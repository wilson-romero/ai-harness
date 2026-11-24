"""Guards on the runtime the project is pinned to."""

import sys


def test_runs_on_cpython_314() -> None:
    assert sys.version_info[:2] == (3, 14)
    assert sys.implementation.name == "cpython"
