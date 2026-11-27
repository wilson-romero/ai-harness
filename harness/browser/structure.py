"""A dump of a page's STRUCTURE with every piece of human text removed, in the page itself.

The dump lists elements (tag, a few attribute names, sanitised values, text lengths) so the
layout of a real page can be studied without reading anything a person wrote or a service
answered. Sanitising happens in the page's JavaScript, so raw text never reaches Python; the
Python side then checks the result again (`check_sanitised`) before anything is written.

Rules:
- identifier attributes (role, id, class, data-*, a few aria states and id references) keep
  their value only when it is a plain identifier (letters, digits, `-`, `_`); runs of hex
  that contain a digit become `<hex>` and other digit runs `#`. A value that also appears in
  the page's text or human-readable attributes becomes `<len:N,in-text>`: a title or a name
  used as an id does not survive;
- human-readable attributes (aria-label, title, alt, placeholder, value, href, src, ...) and
  any other attribute become `<len:N,category>`;
- a text node becomes its length; script, style and template contents are skipped.
"""

from __future__ import annotations

import re

from playwright.async_api import Page

MAX_NODES = 12000

# A kept value has no digit and no space: every digit was masked or the value was replaced.
_KEPT_VALUE = re.compile(r"(?:[A-Za-z_.#-]|<hex>)+")
_REPLACED_VALUE = re.compile(r"<len:\d+(?:,[a-z-]+)?>")
_LINE = re.compile(
    r"(?P<indent> *)(?P<label>\[[a-z-]+\] )?(?P<tag>[a-z][a-z0-9-]*|#shadow-root|#more)"
    r"(?P<rest>.*)"
)
# Attributes whose value may be kept (sanitised); every other attribute must be replaced.
IDENT_ATTRS = frozenset(
    "role id class type contenteditable tabindex dir lang name disabled hidden inert draggable "
    "spellcheck autocomplete aria-busy aria-live aria-hidden aria-expanded aria-disabled "
    "aria-selected aria-pressed aria-checked aria-haspopup aria-multiline aria-current "
    "aria-atomic aria-relevant aria-level aria-posinset aria-setsize aria-modal aria-orientation "
    "aria-autocomplete aria-readonly aria-required aria-invalid aria-labelledby aria-describedby "
    "aria-controls aria-owns aria-activedescendant aria-details aria-errormessage aria-flowto".split()
)
_TOKEN_NAMED = re.compile(r"(?P<name>[a-z][a-z0-9_:-]*)=(?P<value>\S+)")
_REST_FIELD = re.compile(r"text:\d+|@-?\d+,-?\d+,\d+,\d+|hidden|nodes:\d+")


class UnsafeStructure(ValueError):
    """The dump holds something that the sanitising rules should have removed."""


DUMP_JS = r"""
([maxNodes, labels]) => {
  const IDENT_ATTRS = new Set(["role", "id", "class", "type", "contenteditable", "tabindex", "dir",
    "lang", "name", "disabled", "hidden", "inert", "draggable", "spellcheck", "autocomplete",
    "aria-busy", "aria-live", "aria-hidden", "aria-expanded", "aria-disabled", "aria-selected",
    "aria-pressed", "aria-checked", "aria-haspopup", "aria-multiline", "aria-current",
    "aria-atomic", "aria-relevant", "aria-level", "aria-posinset", "aria-setsize", "aria-modal",
    "aria-orientation", "aria-autocomplete", "aria-readonly", "aria-required", "aria-invalid",
    "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-activedescendant",
    "aria-details", "aria-errormessage", "aria-flowto"]);
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "LINK", "META", "HEAD"]);
  const PLAIN = /^[A-Za-z0-9_-]+$/;
  const human = [];
  const collect = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walker.currentNode; n; n = walker.nextNode()) {
      if (n.nodeType === 3) {
        if (n.parentElement && SKIP.has(n.parentElement.tagName)) continue;
        const t = n.nodeValue.trim();
        if (t) human.push(t.toLowerCase());
        continue;
      }
      for (const a of ["aria-label", "title", "alt", "placeholder", "value", "aria-description"]) {
        const v = n.getAttribute && n.getAttribute(a);
        if (v) human.push(v.toLowerCase());
      }
      if (n.shadowRoot) collect(n.shadowRoot);
    }
  };
  collect(document.documentElement);
  human.push(document.title.toLowerCase());
  const haystack = human.join("\n");
  const category = (v) => {
    if (!v) return "empty";
    if (/^(https?:)?\/\//i.test(v)) return "url";
    if (v.startsWith("/")) return "path";
    if (v.startsWith("#")) return "fragment";
    if (/^\d+$/.test(v)) return "number";
    if (/\s/.test(v)) return "words";
    return "word";
  };
  const replaced = (v, cat) => `<len:${v.length},${cat || category(v)}>`;
  const mask = (v) => v.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, "<hex>")
                       .replace(/[0-9A-Fa-f]{6,}/g, (m) => /\d/.test(m) ? "<hex>" : m)
                       .replace(/\d+/g, "#");
  const ident = (v) => {
    if (v === "") return "<len:0,empty>";
    if (!PLAIN.test(v)) return replaced(v);
    if (v.length >= 3 && haystack.includes(v.toLowerCase())) return replaced(v, "in-text");
    return mask(v);
  };
  const lines = [];
  let count = 0;
  const visit = (el, depth) => {
    if (count >= maxNodes) return;
    if (SKIP.has(el.tagName)) return;
    count += 1;
    const tag = el.tagName.toLowerCase();
    const parts = [];
    for (const attr of el.attributes) {
      const name = attr.name.toLowerCase();
      if (!/^[a-z][a-z0-9_:-]*$/.test(name)) continue;
      let value;
      if (name === "class") {
        value = attr.value.split(/\s+/).filter(Boolean).map(ident).join(".");
        if (!value) continue;
      } else if (IDENT_ATTRS.has(name) || name.startsWith("data-")) {
        value = name.startsWith("aria-") && /(by|controls|owns|details|flowto)$/.test(name)
          ? attr.value.split(/\s+/).filter(Boolean).map(ident).join(".")
          : ident(attr.value);
      } else {
        value = replaced(attr.value);
      }
      parts.push(`${name}=${value}`);
    }
    let text = 0;
    for (const child of el.childNodes) if (child.nodeType === 3) text += child.nodeValue.trim().length;
    if (text) parts.push(`text:${text}`);
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (rect.width === 0 && rect.height === 0 || style.visibility === "hidden" || style.display === "none") {
      parts.push("hidden");
    } else {
      parts.push(`@${Math.round(rect.x)},${Math.round(rect.y)},${Math.round(rect.width)},${Math.round(rect.height)}`);
    }
    const label = labels.get(el);
    lines.push(`${" ".repeat(depth)}${label ? "[" + label + "] " : ""}${tag}${parts.length ? " " + parts.join(" ") : ""}`);
    if (tag === "svg" || tag === "iframe") {
      lines[lines.length - 1] += ` nodes:${el.querySelectorAll("*").length}`;
      return;
    }
    if (el.shadowRoot) {
      lines.push(`${" ".repeat(depth + 1)}#shadow-root`);
      for (const child of el.shadowRoot.children) visit(child, depth + 2);
    }
    for (const child of el.children) visit(child, depth + 1);
  };
  visit(document.documentElement, 0);
  if (count >= maxNodes) lines.push("#more");
  return lines;
}
"""

# Labels let a caller mark elements it found (the editor, a turn) in the dump. They are fixed
# words chosen by code, never page content.
LABELS_JS = r"""
(entries) => {
  const labels = new Map();
  const registry = window.__aiHarnessProbe && window.__aiHarnessProbe.elements;
  if (registry) for (const [serial, label] of entries) {
    const el = registry.get(serial);
    if (el) labels.set(el, label);
  }
  return labels;
}
"""


async def structure_dump(page: Page, labels: dict[int, str] | None = None) -> list[str]:
    """The sanitised structure of the page's main frame, one element per line."""
    for label in (labels or {}).values():
        if not re.fullmatch(r"[a-z-]+", label):
            raise ValueError(f"invalid label {label!r}")
    entries = list((labels or {}).items())
    lines = await page.evaluate(
        f"""(args) => {{
            const labels = ({LABELS_JS})(args[1]);
            return ({DUMP_JS})([args[0], labels]);
        }}""",
        [MAX_NODES, entries],
    )
    check_sanitised(lines)
    return lines


def check_sanitised(lines: list[str]) -> None:
    """Raise UnsafeStructure unless every line follows the dump's grammar.

    A kept attribute value may hold no digit and no space; anything else must be one of the
    replacement forms. This catches a sanitising rule that was skipped or broken.
    """
    for number, line in enumerate(lines, 1):
        match = _LINE.fullmatch(line)
        if not match:
            raise UnsafeStructure(f"line {number}: not an element line")
        for field in match.group("rest").split():
            if _REST_FIELD.fullmatch(field):
                continue
            token = _TOKEN_NAMED.fullmatch(field)
            if not token:
                raise UnsafeStructure(f"line {number}: unexpected field")
            name = token.group("name")
            keepable = name in IDENT_ATTRS or name.startswith("data-")
            for value in token.group("value").split("."):
                if _REPLACED_VALUE.fullmatch(value):
                    continue
                if not (keepable and value and _KEPT_VALUE.fullmatch(value)):
                    raise UnsafeStructure(f"line {number}: unsanitised value")
