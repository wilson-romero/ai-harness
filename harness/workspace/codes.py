"""Every reason a work-folder tool can refuse with (workspace-tools design D1-D4, B1-5).

Stable strings: they are printed, tested and stored in `workspace_events.code`, whose CHECK
lists exactly `CODES` (tests/unit/test_workspace_audit.py compares the two).
"""

from __future__ import annotations

from harness.core.errors import HarnessError

OK = "ok"

# The work folder itself (D1).
ROOT_CODES = (
    "not_absolute",
    "root_not_found",
    "link",
    "not_a_directory",
    "harness_repo",
    "data_dir",
    "vault",
    "code_run_root",  # in the closed list; checked once code-run exists (design B1-3)
    "home",
    "filesystem_root",
    "workspace_changed",
)
# The shape of a relative path, decided on the string alone (D2, phase 1).
FORM_CODES = (
    "empty_path",
    "path_too_long",
    "absolute",
    "backslash",
    "colon",
    "forbidden_character",
    "invisible_character",
    "not_nfc",
    "empty_component",
    "dot_component",
    "component_too_long",
    "trailing_dot_or_space",
    "reserved_name",
)
# The real path and the open (D2, phases 2 and 3).
WALK_CODES = (
    "not_found",
    "name_not_exact",
    "not_regular",
    "hard_link",
    "changed",
    "outside_root",
    "unreadable",
)
# What is never read even inside the folder (D3).
RULE_CODES = ("denied_component", "denied_name", "credential_in_file", "binary", "too_large")
READ_CODES = ("offset_out_of_range",)

CODES = tuple(dict.fromkeys((OK, *ROOT_CODES, *FORM_CODES, *WALK_CODES, *RULE_CODES,
                              *READ_CODES)))
# Refusals decided from the arguments alone, before the disk is touched: audited as a denied
# call (`argument_invalid`), not as a failed one.
STRING_CODES = frozenset(FORM_CODES) | {"denied_component", "denied_name"}


class WorkspaceRefused(HarnessError):
    """A controlled refusal. `detail` is written by the harness and never holds file text."""

    def __init__(self, code: str, detail: str = "") -> None:
        assert code in CODES and code != OK, code
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
