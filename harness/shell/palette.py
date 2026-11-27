"""The colour roles of the full screen (tui-spacing D1): every colour is a Textual theme
variable named by what it is for, never a colour of the house.

The screen's CSS declares each role as a variable (`$you-bar`), and the row styles of
`tui.STYLES` take the theme variable a role names. In an ANSI theme the fills of the chrome
are transparent, so no role is the only mark of anything: the shape is (a titled frame, a bar,
a prefix), and colour and fill only reinforce it (study D7).
"""

from __future__ import annotations

ROLES: dict[str, str] = {
    # The approval box (approval-buttons D7): the only heavy frame on the screen.
    "approval-frame": "$warning",
    "approval-fill": "$warning-muted",
    "box-fill": "$surface",
    # Text from outside the harness: a neutral frame, structure and not a state (D6).
    "foreign-frame": "$foreground-muted",
    # The person's messages (D3): a bar of their own colour and a soft fill.
    "you-bar": "$primary",
    "you-fill": "$boost",
    # The harness's chrome: footer, separators, the picker, selection and browsing.
    "chrome-fill": "$panel",
    "chrome-muted": "$text-muted",
    "rule": "$panel-lighten-2",
    "picker-frame": "$primary",
    "select-fill": "$accent 25%",
    "select-frame": "$accent",
    "browse-frame": "$warning",
    # The chrome of a folded block (collapsible-blocks D4): the one fill a row style has.
    "fold-text": "$foreground",
    "fold-fill": "$panel-lighten-1",
    # Row styles: statuses of the harness only...
    "error-text": "$text-error",
    "warning-text": "$text-warning",
    # ...and what foreign text may take: never a status colour, a fill or reverse.
    "heading-text": "$text-primary",
    "bullet-text": "$text-primary",
    "code-text": "$text-secondary",
}


def css_variables() -> str:
    """The lines that declare ROLES at the top of a Textual stylesheet."""
    return "\n".join(f"${name}: {value};" for name, value in ROLES.items())
