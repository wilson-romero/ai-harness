"""What is never read or written, even inside the work folder (workspace-tools D3).

Closed lists in code, compared after `casefold()`: no file of the folder and no setting can
widen or narrow them. The name rules are pure; the content rules look at bytes already read.

The names are conventions, not a guarantee: a credential in a file with any other name is
read, unless its content has one of the forms `redaction` knows (then `credential_in_file`).
Widened after the review of d0a65d8 (finding 3): `*.env`, `.env-*`/`.env_*`, `kubeconfig`,
Terraform state and variables, and the usual client files of databases and registries.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass

from harness.skills.approvals import is_invisible
from harness.text.redaction import secret_kinds
from harness.workspace.codes import WorkspaceRefused

FILE_MAX_BYTES = 256 * 1024
BINARY_SNIFF_BYTES = 8 * 1024

# A path with one of these components anywhere is refused (version-control internals and the
# usual homes of credentials).
DENIED_COMPONENTS = frozenset(
    {".git", ".hg", ".svn", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker"}
)
DENIED_NAMES = frozenset(
    {
        ".env", ".envrc", ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials",
        "credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml",
        "secrets.toml", "kubeconfig", ".pgpass", ".my.cnf", ".htpasswd", ".vault-token",
        ".dockercfg",
    }
)
ENV_EXAMPLES = frozenset({".env.example", ".env.sample", ".env.template"})
DENIED_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".env.", ".env-", ".env_")
DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ovpn",
                   ".env", ".kubeconfig", ".tfstate", ".tfstate.backup", ".tfvars",
                   ".tfvars.json")


def name_refusal(parts: tuple[str, ...]) -> str | None:
    """`denied_component` or `denied_name` for a path's components, or None."""
    for part in parts:
        if part.casefold() in DENIED_COMPONENTS:
            return "denied_component"
    if not parts:
        return None
    name = parts[-1].casefold()
    if name in ENV_EXAMPLES:
        return None
    if (
        name in DENIED_NAMES
        or name.startswith(DENIED_PREFIXES)
        or name.endswith(DENIED_SUFFIXES)
    ):
        return "denied_name"
    return None


def check_names(parts: tuple[str, ...]) -> None:
    code = name_refusal(parts)
    if code is not None:
        raise WorkspaceRefused(code, "this name is never read or written by the harness")


@dataclass(frozen=True)
class Decoded:
    text: str  # without the BOM
    bom: bool


def decode_checked(raw: bytes) -> Decoded:
    """The text of a file the rules allow: UTF-8, not binary, no known credential (D3)."""
    if len(raw) > FILE_MAX_BYTES:
        raise WorkspaceRefused("too_large", f"files over {FILE_MAX_BYTES} bytes are not read")
    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        raise WorkspaceRefused("binary", "the file has a NUL byte: binary files are not read")
    bom = raw.startswith(codecs.BOM_UTF8)
    try:
        text = raw[len(codecs.BOM_UTF8) if bom else 0:].decode("utf-8")
    except UnicodeDecodeError:
        raise WorkspaceRefused("binary", "the file is not valid UTF-8") from None
    # As `normalise_content` does: an invisible character inside a credential must not keep
    # it from being found.
    if secret_kinds(text) or secret_kinds("".join(c for c in text if not is_invisible(c))):
        raise WorkspaceRefused(
            "credential_in_file", "the file holds a credential of a known form: not read"
        )
    return Decoded(text, bom)
