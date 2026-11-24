"""Find the Copilot controls by behaviour, for the probe (`copilot_probe.py discover`).

Nothing here is written for one page. The probe types a fixed synthetic prompt, sends it, and
then looks for what changed: the element that shows the prompt back (user turn), the element
that holds the reply's marker (assistant turn), controls that appear while the reply streams
and go away at its end (stop), controls that appear only at the end (done), `aria-busy` that
flips, and a "new conversation" control that empties the thread and changes the URL.

Locators are derived from stable attributes of those elements and their ancestors (`data-*`,
`role`, `id`, `type`, class tokens, tag), never from text content. An attribute value is used
only when it is a plain word (letters, `-`, `_`, no digit), and never when the same word also
appears in the page's text or human-readable attributes: an id built from a name, a title or a
tenant cannot become a locator. The JavaScript returns element serials, numbers, booleans and
such selectors; it never returns page text.

What discovery cannot find it names, and the probe asks for that single item.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

ECHO_TIMEOUT_S = 15.0
NEW_CHAT_TIMEOUT_S = 6.0
WATCH_INTERVAL_MS = 100

INSTALL_JS = r"""
() => {
  if (window.__aiHarnessProbe && window.__aiHarnessProbe.version === 1) return;
  const P = window.__aiHarnessProbe = {
    version: 1, elements: new Map(), serialOf: new WeakMap(), next: 1, watch: null,
  };
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);
  const EDITABLE = 'textarea, input[type="text"], input:not([type]), [contenteditable="true"], ' +
    '[contenteditable=""], [contenteditable="plaintext-only"], [role="textbox"]';
  const CONTROL = 'button, [role="button"], a[role], [aria-busy]';
  const reg = (el) => {
    let s = P.serialOf.get(el);
    if (!s) { s = P.next++; P.serialOf.set(el, s); P.elements.set(s, el); }
    return s;
  };
  const get = (s) => P.elements.get(s);
  const parentOf = (el) => el.parentElement ||
    (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null);
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const st = getComputedStyle(el);
    return st.visibility !== "hidden" && st.display !== "none";
  };
  const enabled = (el) => !(el.disabled || el.getAttribute("aria-disabled") === "true");
  const norm = (t) => t.replace(/\s+/g, " ").trim().toLowerCase();

  // -- words a locator must never be built from: the page's text and human attributes --
  const haystack = () => {
    const parts = [document.title];
    const walk = (root) => {
      const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
      for (let n = w.currentNode; n; n = w.nextNode()) {
        if (n.nodeType === 3) {
          if (!(n.parentElement && SKIP.has(n.parentElement.tagName))) parts.push(n.nodeValue);
          continue;
        }
        for (const a of ["aria-label", "title", "alt", "placeholder", "value"]) {
          const v = n.getAttribute(a); if (v) parts.push(v);
        }
        if (n.shadowRoot) walk(n.shadowRoot);
      }
    };
    walk(document.documentElement);
    return parts.join("\n").toLowerCase();
  };
  const SAFE = /^[A-Za-z][A-Za-z_-]{1,40}$/;
  const STATE_NAME = /state|status|busy|load|active|select|expand|open|visib|hidden|disabl|focus|hover|index|idx|key|time|count|track|bi-|telemetry|clarity|^data-m$|^data-id$|-id$/i;
  const STATE_CLASS = /active|select|disabl|hover|focus|open|close|hidden|visible|load|busy|anim|appear|enter|exit|motion|transition|show|fade|ripple/i;
  const PREF_DATA = new Set(["data-testid", "data-test-id", "data-automation-id", "data-tid", "data-qa"]);

  const ownParts = (el, hay) => {
    const tag = el.tagName.toLowerCase();
    const parts = [];
    const ok = (v) => SAFE.test(v) && !hay.includes(v.toLowerCase());
    for (const a of el.attributes) {
      const name = a.name.toLowerCase();
      let pref = null;
      if (PREF_DATA.has(name)) pref = 0;
      else if (name.startsWith("data-") && !STATE_NAME.test(name)) pref = 1;
      else if (name === "role") pref = 2;
      else if (name === "aria-live" || name === "aria-multiline") pref = 3;
      else if (name === "id") pref = 4;
      else if (name === "type" || name === "contenteditable") pref = 5;
      if (pref === null) continue;
      if (name === "contenteditable") { parts.push({ sel: `[contenteditable="${a.value}"]`, pref }); continue; }
      if (!ok(a.value)) continue;
      parts.push({ sel: `[${name}="${a.value}"]`, pref });
    }
    for (const c of el.classList) {
      if (ok(c) && !STATE_CLASS.test(c)) parts.push({ sel: "." + c, pref: 6 });
    }
    return { tag, parts };
  };
  const candidates = (el, hay) => {
    const { tag, parts } = ownParts(el, hay);
    const out = [];
    for (const p of parts) {
      out.push({ sel: p.sel, score: p.pref * 2 + 1 });
      out.push({ sel: tag + p.sel, score: p.pref * 2 + 2 });
    }
    for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
      out.push({ sel: tag + parts[i].sel + parts[j].sel, score: (parts[i].pref + parts[j].pref) * 2 + 4 });
    }
    out.push({ sel: tag, score: 30 });
    return out.sort((a, b) => a.score - b.score);
  };
  const matches = (sel, root) => { try { return [...root.querySelectorAll(sel)]; } catch { return null; } };

  // Selectors for `s` that match exactly `expect` elements in `scope` (or the document),
  // `s` among them. Own attributes first, then "ancestor descendant" pairs.
  P.selectors = (s, expect, scopeSerial) => {
    const el = get(s);
    if (!el) return [];
    const root = scopeSerial ? get(scopeSerial) : document;
    if (!root) return [];
    const hay = haystack();
    const found = [];
    const test = (sel, score) => {
      const m = matches(sel, root);
      if (m && m.length === expect && m.includes(el) && !found.some((f) => f.sel === sel)) {
        found.push({ sel, score });
      }
    };
    const own = candidates(el, hay);
    for (const c of own) test(c.sel, c.score);
    if (found.length < 3) {
      let anc = parentOf(el);
      for (let level = 1; anc && level <= 5 && anc !== root; level++, anc = parentOf(anc)) {
        if (anc === document.body || anc === document.documentElement) break;
        const ancParts = candidates(anc, hay).filter((c) => c.score < 30).slice(0, 4);
        for (const a of ancParts) for (const c of own.slice(0, 6)) {
          test(`${a.sel} ${c.sel}`, a.score + c.score + 10 + level);
        }
      }
    }
    return found.sort((a, b) => a.score - b.score).slice(0, 4).map((f) => f.sel);
  };
  P.count = (sel, scopeSerial) => {
    const root = scopeSerial ? get(scopeSerial) : document;
    const m = root && matches(sel, root);
    return m ? m.length : -1;
  };
  P.lastContains = (sel, s) => {
    const m = matches(sel, document);
    const el = get(s);
    return !!(m && m.length && el && (m[m.length - 1] === el || m[m.length - 1].contains(el)));
  };

  // -- the editor --
  const editableTarget = (el) => {
    if (el.isContentEditable || el.tagName === "TEXTAREA" || el.tagName === "INPUT") return el;
    return el.querySelector('[contenteditable="true"], [contenteditable=""], textarea, input') || el;
  };
  P.editors = () => {
    const seen = new Set();
    const out = [];
    for (const raw of document.querySelectorAll(EDITABLE)) {
      if (!visible(raw) || !enabled(raw) || raw.readOnly) continue;
      const el = editableTarget(raw);
      const outer = el.parentElement && el.parentElement.closest('[contenteditable="true"], [contenteditable=""]');
      const target = outer || el;
      if (seen.has(target)) continue;
      seen.add(target);
      const r = target.getBoundingClientRect();
      out.push({
        serial: reg(target), area: Math.round(r.width * r.height), bottom: Math.round(r.bottom),
        kind: target.tagName === "TEXTAREA" ? "textarea" : target.isContentEditable
          ? "contenteditable" : target.tagName === "INPUT" ? "input" : "textbox",
        paragraph: !!target.querySelector("p"),
      });
    }
    return out;
  };
  P.editorLength = (s) => {
    const el = get(s);
    if (!el) return -1;
    return ("value" in el && el.tagName !== "DIV" ? el.value : el.textContent).length;
  };

  // -- buttons near the editor and their state, to see which one a typed prompt enables --
  P.buttonsNear = (s) => {
    const ed = get(s);
    const out = [];
    const seen = new Set();
    let anc = ed && parentOf(ed);
    for (let level = 1; anc && level <= 6; level++, anc = parentOf(anc)) {
      for (const b of anc.querySelectorAll('button, [role="button"]')) {
        if (seen.has(b) || ed.contains(b)) continue;
        seen.add(b);
        out.push({ serial: reg(b), level, visible: visible(b), enabled: enabled(b) });
      }
    }
    return out;
  };

  // -- where a fixed string shows up: deepest visible elements, outside editors and `exclude` --
  P.findText = (needle, exclude) => {
    const n = norm(needle);
    const excluded = (exclude || []).map(get).filter(Boolean);
    const hits = [];
    const descend = (el) => {
      let found = false;
      const kids = el.shadowRoot ? [...el.shadowRoot.children, ...el.children] : [...el.children];
      for (const child of kids) {
        if (SKIP.has(child.tagName)) continue;
        if (norm(child.textContent).includes(n)) { found = true; descend(child); }
      }
      if (!found && el !== document.body) hits.push(el);
    };
    if (norm(document.body.textContent).includes(n)) descend(document.body);
    const readable = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
    return hits  // a 1-pixel screen-reader copy is not the turn
      .filter((el) => visible(el) && readable(el) && !el.closest(EDITABLE) &&
                      !excluded.some((x) => x.contains(el)))
      .map(reg);
  };
  // A cheap signature of an element's text: its length and a hash. Never the text.
  P.textSig = (s, marker) => {
    const el = get(s);
    if (!el || !el.isConnected) return null;
    let t = el.textContent;
    if (marker) { const i = t.lastIndexOf(marker); if (i >= 0) t = t.slice(0, i + marker.length); }
    let h = 0;
    for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0;
    return `${t.length}:${h}`;
  };

  // -- ancestry --
  P.chain = (s) => {
    const out = [];
    for (let el = get(s); el && el !== document.body && el !== document.documentElement; el = parentOf(el)) {
      out.push(reg(el));
    }
    return out;
  };
  P.contains = (a, b) => { const A = get(a), B = get(b); return !!(A && B && A.contains(B)); };
  P.alive = (s) => { const el = get(s); return !!(el && el.isConnected); };

  // -- what appears, disappears and flips while a reply streams --
  P.watchStart = () => {
    if (P.watch) clearInterval(P.watch.timer);
    const W = P.watch = { t0: performance.now(), items: new Map(), timer: null, ticks: 0 };
    const tick = () => {
      const now = Math.round(performance.now() - W.t0);
      const first = W.ticks === 0;
      W.ticks += 1;
      const present = new Set();
      for (const el of document.querySelectorAll(CONTROL)) {
        const s = reg(el);
        present.add(s);
        const vis = visible(el);
        const busy = el.getAttribute("aria-busy");
        let it = W.items.get(s);
        if (!it) {
          it = { serial: s, existing: first && vis, appeared: null, disappeared: null,
                 visibleNow: false, busyTrue: null, busyEnd: null, selectors: null,
                 button: el.matches('button, [role="button"], a[role]') };
          W.items.set(s, it);
        }
        if (vis && !it.existing && it.appeared === null) {
          it.appeared = now;
          if (it.button) it.selectors = P.selectors(s, 1, null);
        }
        if (!vis && it.visibleNow && it.disappeared === null) it.disappeared = now;
        if (vis && it.disappeared !== null && it.appeared !== null && now > it.disappeared) {
          it.disappeared = null;  // it came back: only the last disappearance counts
        }
        it.visibleNow = vis;
        if (busy === "true" && it.busyTrue === null) {
          it.busyTrue = now;
          it.selectors = P.selectors(s, 1, null);
        }
        if (busy !== "true" && it.busyTrue !== null && it.busyEnd === null) it.busyEnd = now;
        if (busy === "true") it.busyEnd = null;
      }
      for (const it of W.items.values()) {
        if (!present.has(it.serial) && it.visibleNow) {
          it.visibleNow = false;
          if (it.disappeared === null) it.disappeared = now;
        }
        if (!present.has(it.serial) && it.busyTrue !== null && it.busyEnd === null) it.busyEnd = now;
      }
    };
    tick();
    W.timer = setInterval(tick, %INTERVAL%);
    return true;
  };
  P.watchNow = () => (P.watch ? Math.round(performance.now() - P.watch.t0) : null);
  P.watchStop = () => {
    const W = P.watch;
    if (!W) return [];
    clearInterval(W.timer);
    P.watch = null;
    return [...W.items.values()].filter((it) => !it.existing || it.busyTrue !== null);
  };

  // -- "new conversation": by accessible name in common UI languages, or by attributes --
  P.newChatCandidates = () => {
    const NAME = /^\s*(new chat|new conversation|start (a )?new (chat|conversation)|nuevo chat|nueva conversaci[oó]n|chat nuevo|iniciar (un )?(nuevo chat|nueva conversaci[oó]n)|neuer chat|neue unterhaltung|nouvelle conversation|nouveau chat|nova conversa|novo chat|nuova chat|nuova conversazione)\b/i;
    const ATTR = /new[-_]?(chat|conversation)|newchat|newconversation/i;
    const out = [];
    for (const el of document.querySelectorAll('button, [role="button"], a')) {
      if (!visible(el) || !enabled(el)) continue;
      const name = el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || "";
      const byName = NAME.test(name.replace(/\s+/g, " "));
      let byAttr = false;
      for (const a of el.attributes) {
        if ((a.name === "id" || a.name === "class" || a.name.startsWith("data-")) && ATTR.test(a.value)) byAttr = true;
      }
      if (byName || byAttr) out.push({ serial: reg(el), byName, byAttr });
    }
    return out;
  };
  P.click = (s) => { const el = get(s); if (el) el.click(); return !!el; };

  // -- a page that offers to sign in is not the chat: count visible elements marked so --
  P.signedOutHints = () => {
    const HINT = /(^|[^a-z])(unauth\w*|sign[-_ ]?in|log[-_ ]?in)([^a-z]|$)/i;
    let n = 0;
    for (const el of document.querySelectorAll("*")) {
      if (!visible(el)) continue;
      for (const a of el.attributes) {
        if (!(a.name === "id" || a.name === "class" || a.name.startsWith("data-"))) continue;
        if (HINT.test(a.value.replace(/([a-z])([A-Z])/g, "$1 $2"))) { n += 1; break; }
      }
    }
    return n;
  };
}
""".replace("%INTERVAL%", str(WATCH_INTERVAL_MS))


@dataclass
class Discovery:
    """What discovery found. `locators` is in the shape of `candidates.json`."""

    locators: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


# One line per item that discovery may fail to find: what to give the probe instead.
ASK = {
    "signed_in": "the page looks signed out (it offers to sign in): run `probe login`, sign in "
    "and choose to stay signed in, then run this step again",
    "composer": "the message box: record a click in it with codegen",
    "send": "how to send: record a click on the send button with codegen",
    "user_turn": "your message in the thread: record a click on the text you sent",
    "assistant_turn": "the reply in the thread: record a click on the reply text",
    "new_conversation": "the new-conversation control: record a click on it with codegen",
}


async def js(page: Page, call: str, *args: Any) -> Any:
    """Call one of the installed helpers, installing them first if the page navigated."""
    await page.evaluate(INSTALL_JS)
    return await page.evaluate(f"(args) => window.__aiHarnessProbe.{call}(...args)", list(args))


def css(selector: str) -> dict[str, str]:
    return {"css": selector}


async def wait_for(check, timeout_s: float, interval_s: float = 0.25):
    deadline = time.monotonic() + timeout_s
    while True:
        value = await check()
        if value or time.monotonic() >= deadline:
            return value
        await asyncio.sleep(interval_s)


async def find_editor(page: Page, found: Discovery) -> int | None:
    editors = await js(page, "editors")
    found.facts["editors_visible"] = len(editors)
    if not editors:
        return None
    best = max(editors, key=lambda e: (e["area"], e["bottom"]))
    found.facts["editor_kind"] = best["kind"]
    found.facts["editor_has_paragraph"] = best["paragraph"]
    selectors = await js(page, "selectors", best["serial"], 1, None)
    if not selectors:
        return None
    found.locators["composer"] = css(selectors[0])
    return best["serial"]


@dataclass
class Timing:
    """How long a reply must stay unchanged to count as finished, and the hard limits."""

    stable_ms: int
    settle_ms: int
    deadline_s: float


@dataclass
class Sent:
    method: str | None  # "enter", "button" or None when nothing sent the prompt
    user_hits: list[int]
    answer: int | None
    echo_ms: int | None
    answer_seen_ms: int | None
    truth_ms: int | None  # watch clock: when the reply, up to its marker, last changed


async def editor_empty(page: Page, editor: int) -> bool:
    return await js(page, "editorLength", editor) == 0


async def send_and_follow(
    page: Page, editor: int, composer_css: str, prompt: str, marker: str, timing: Timing,
    method: str | None, send_css: str | None,
) -> tuple[Sent, list[int]]:
    """Type the prompt and send it, then follow the reply until it stops changing.

    With no known method, Enter is tried first; if Enter does not send, only a button that
    typing enabled is clicked (never another one). Returns what was seen and the serials of
    the buttons that typing enabled.
    """
    composer = page.locator(composer_css).first
    before = {b["serial"]: b for b in await js(page, "buttonsNear", editor)}
    await composer.fill(prompt)
    after = await js(page, "buttonsNear", editor)
    enabled_by_typing = [
        b["serial"] for b in after
        if b["visible"] and b["enabled"]
        and not (before.get(b["serial"], {}).get("visible") and before.get(b["serial"], {}).get("enabled"))
    ]
    started = time.monotonic()

    async def sent() -> bool:
        return bool(await js(page, "findText", prompt, [])) or await editor_empty(page, editor)

    used = None
    if method in (None, "enter"):
        await composer.press("Enter")
        if await wait_for(sent, ECHO_TIMEOUT_S):
            used = "enter"
    if used is None and method in (None, "button"):
        target = send_css
        if target is None and enabled_by_typing:
            selectors = await js(page, "selectors", enabled_by_typing[0], 1, None)
            target = selectors[0] if selectors else None
        if target is not None:
            await page.locator(target).first.click(timeout=5000)
            if await wait_for(sent, ECHO_TIMEOUT_S):
                used = "button"
    result = Sent(used, [], None, None, None, None)
    if used is None:
        return result, enabled_by_typing

    async def echoed() -> list[int]:
        return await js(page, "findText", prompt, [])

    result.user_hits = await wait_for(echoed, 3.0) or []
    if result.user_hits:
        result.echo_ms = round((time.monotonic() - started) * 1000)

    async def answered() -> list[int]:
        return await js(page, "findText", marker, result.user_hits)

    hits = await wait_for(answered, timing.deadline_s, 0.1)
    if not hits:
        return result, enabled_by_typing
    result.answer = hits[-1]  # the newest place that holds the marker
    result.answer_seen_ms = round((time.monotonic() - started) * 1000)
    last_sig, truth = None, await js(page, "watchNow")
    changed_at = time.monotonic()
    while time.monotonic() - started < timing.deadline_s:
        sig = await js(page, "textSig", result.answer, marker)
        if sig != last_sig:
            last_sig, changed_at, truth = sig, time.monotonic(), await js(page, "watchNow")
        elif (time.monotonic() - changed_at) * 1000 >= timing.stable_ms + timing.settle_ms:
            break
        await asyncio.sleep(0.1)
    result.truth_ms = truth
    return result, enabled_by_typing


async def first_selector(page: Page, serial: int) -> str:
    selectors = await js(page, "selectors", serial, 1, None)
    if not selectors:
        raise LookupError("no stable selector")
    return selectors[0]


async def levels_between(page: Page, hit: int, other: int | None, editor: int) -> list[int]:
    """The element and its ancestors that do not also hold `other` (or the editor)."""
    levels = []
    for serial in await js(page, "chain", hit):
        if other is not None and await js(page, "contains", serial, other):
            break
        if await js(page, "contains", serial, editor):
            break
        levels.append(serial)
    return levels


async def nearest(page: Page, hits: list[int], target: int) -> int:
    """Of several places that hold the prompt, the one closest to the reply in the tree."""
    target_chain = await js(page, "chain", target)
    best, best_rank = hits[0], len(target_chain) + 1
    for hit in hits:
        for rank, serial in enumerate(target_chain):
            if await js(page, "contains", serial, hit):
                if rank < best_rank:
                    best, best_rank = hit, rank
                break
    return best


async def candidates_by_level(page: Page, levels: list[int]) -> list[tuple[int, list[str]]]:
    return [(index, await js(page, "selectors", serial, 1, None)) for index, serial in enumerate(levels)]


async def pick_turn(
    page: Page, options: list[tuple[int, list[str]]], newest: int
) -> tuple[str, int] | None:
    """After the second send: the highest level whose selector now matches exactly two
    elements, the last of which holds the new text."""
    for index, selectors in reversed(options):
        for selector in selectors:
            if await js(page, "count", selector, None) == 2 and await js(
                page, "lastContains", selector, newest
            ):
                return selector, index
    return None


def kind_of(selector: str) -> str:
    """The kind of a selector, for the tenant-free summary (never the selector itself)."""
    if "[data-" in selector:
        return "data-attribute"
    if "[role=" in selector:
        return "role"
    if "[id=" in selector:
        return "id"
    if "[contenteditable" in selector or "[type=" in selector or "[aria-" in selector:
        return "attribute"
    if "." in selector:
        return "class"
    return "tag"


async def discover(
    page: Page, prompts: tuple[str, str], markers: tuple[str, str], timing: Timing, locate_reference
) -> Discovery:
    """Two fixed sends in one conversation, then a check of the new-conversation control."""
    found = Discovery()
    facts = found.facts
    facts["sends"] = 0
    facts["signed_out_hints"] = await js(page, "signedOutHints")
    if facts["signed_out_hints"]:
        found.missing = ["signed_in"]  # never type into a page that offers to sign in
        return found
    editor = await find_editor(page, found)
    if editor is None:
        found.missing = ["composer"]
        return found
    composer_css = found.locators["composer"]["css"]
    url_before = page.url

    await js(page, "watchStart")
    first, enabled = await send_and_follow(
        page, editor, composer_css, prompts[0], markers[0], timing, None, None
    )
    watched = await js(page, "watchStop")
    facts["sends"] = 1 if first.method else 0
    facts["send_with"] = first.method
    if first.method is None:
        found.missing = ["send"]
        return found
    found.locators["send_with"] = first.method
    send_css = None
    if enabled:
        selectors = await js(page, "selectors", enabled[0], 1, None)
        send_css = selectors[0] if selectors else None
    if send_css:
        found.locators["send"] = css(send_css)
    elif first.method == "button":
        found.missing.append("send")
    facts["send_button_found"] = send_css is not None
    facts["echo_ms"] = first.echo_ms
    facts["answer_seen_ms"] = first.answer_seen_ms
    facts["user_echo_found"] = bool(first.user_hits)
    if first.answer is None:
        found.missing += (["user_turn"] if not first.user_hits else []) + ["assistant_turn"]
        return found

    user_hit = await nearest(page, first.user_hits, first.answer) if first.user_hits else None
    user_levels = await levels_between(page, user_hit, first.answer, editor) if user_hit else []
    answer_levels = await levels_between(page, first.answer, user_hit, editor)
    user_options = await candidates_by_level(page, user_levels)
    answer_options = await candidates_by_level(page, answer_levels)
    ref = locate_reference([url_before], [page.url])
    facts["conversation_ref"] = ref.model_dump(mode="json", exclude_none=True) if ref else None

    # End-of-response candidates, from what changed while the first reply streamed.
    truth = first.truth_ms or 0
    turn_top = answer_levels[-1] if answer_levels else first.answer
    stops = [
        w for w in watched
        if w["button"] and w["appeared"] is not None and w["appeared"] <= truth
        and w["disappeared"] is not None and not w["visibleNow"] and w["selectors"]
    ]
    stop = min(stops, key=lambda w: abs(w["disappeared"] - truth), default=None)
    if stop:
        found.locators["stop"] = css(stop["selectors"][0])
    dones = [
        w for w in watched
        if w["button"] and w["appeared"] is not None and w["visibleNow"]
        and await js(page, "contains", turn_top, w["serial"])
    ]
    done = min(dones, key=lambda w: abs(w["appeared"] - truth), default=None)
    busy_items = [
        w for w in watched
        if w["busyTrue"] is not None and w["busyEnd"] is not None and w["selectors"]
    ]
    busy = min(busy_items, key=lambda w: abs(w["busyEnd"] - truth), default=None)
    facts["truth_watch_ms"] = first.truth_ms
    facts["stop_found"] = stop is not None
    facts["busy_found"] = busy is not None
    facts["controls_appeared"] = sum(1 for w in watched if w["appeared"] is not None)

    # Second send: the turn locators must now match exactly two turns each.
    second, _ = await send_and_follow(
        page, editor, composer_css, prompts[1], markers[1], timing, first.method, send_css
    )
    facts["sends"] = 2 if second.method else 1
    if second.answer is not None:
        newest_user = (
            await nearest(page, second.user_hits, second.answer) if second.user_hits else None
        )
        picked = await pick_turn(page, user_options, newest_user) if newest_user else None
        if picked:
            found.locators["user_turn"] = css(picked[0])
            facts["user_turn_level"] = picked[1]
        picked = await pick_turn(page, answer_options, second.answer)
        if picked:
            found.locators["assistant_turn"] = css(picked[0])
            facts["assistant_turn_level"] = picked[1]
            chosen = answer_levels[picked[1]]
            if done and await js(page, "contains", chosen, done["serial"]):
                scoped = await js(page, "selectors", done["serial"], 1, chosen)
                if scoped:
                    found.locators["response_done_control"] = css(scoped[0])
            if busy and busy["serial"] != chosen:
                found.locators["busy_region"] = css(busy["selectors"][0])
    facts["done_control_found"] = "response_done_control" in found.locators
    for part in ("user_turn", "assistant_turn"):
        if part not in found.locators:
            found.missing.append(part)

    # New conversation: a control named or marked like one, proven by what it does.
    candidates = await js(page, "newChatCandidates")
    facts["new_chat_candidates"] = len(candidates)
    facts["new_chat_verified"] = False
    turns = [found.locators[p]["css"] for p in ("user_turn", "assistant_turn") if p in found.locators]
    for candidate in candidates[:3]:
        try:
            selector = await first_selector(page, candidate["serial"])
        except LookupError:
            continue
        url_then = page.url
        try:
            await page.locator(selector).first.click(timeout=5000)
        except PlaywrightError:
            continue

        async def emptied() -> bool:
            counts = [await js(page, "count", t, None) for t in turns]
            return page.url != url_then and all(c == 0 for c in counts)

        if turns and await wait_for(emptied, NEW_CHAT_TIMEOUT_S):
            found.locators["new_conversation"] = css(selector)
            facts["new_chat_verified"] = True
            facts["new_chat_by_name"] = candidate["byName"]
            break
    if "new_conversation" not in found.locators:
        found.missing.append("new_conversation")
    facts["locator_kinds"] = {
        name: kind_of(spec["css"]) for name, spec in found.locators.items() if isinstance(spec, dict)
    }
    return found


