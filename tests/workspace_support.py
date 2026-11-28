"""Shared helpers of the workspace-tools tests: the synthetic folder and an accepted root."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from harness.workspace.paths import Root
from harness.workspace.root import check_root

BUILD = Path(__file__).resolve().parent / "fixtures" / "workspace" / "build.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("workspace_fixture_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses look their module up while building
    spec.loader.exec_module(module)
    return module


builder = load_builder()


@pytest.fixture
def built(tmp_path: Path):
    return builder.build(tmp_path / "base")


@pytest.fixture
def root(built, tmp_path: Path) -> Root:
    return check_root(str(built.root), data_dir=tmp_path / "data", environ={})
