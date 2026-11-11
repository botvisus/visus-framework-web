"""Pick a date, or a range, in any date field.

Three ways, tried in this order:

1. A native ``<input type=date>``: the value is set directly (ISO), with the
   ``input``/``change`` events a real edit fires.
2. A text field that accepts typing: the date is typed in the format the field
   already shows (``10/23/2026`` → month/day/year, no zero padding) and read back.
3. A calendar that only opens and clicks (a read-only field, or one that rejects
   typing): the field is clicked, the month panels are found by their header
   (``November 2026``, ``novembro de 2026``, ``2026년 11월``), the ◂ ▸ arrows are
   clicked until the month is on screen, and the day is clicked inside THAT month's
   panel — never the greyed day of the neighbouring month that shares the grid.
   For a range the start is clicked, then the end; an Apply/OK button is pressed
   when the picker has one.

Every path ends by reading the field back: a date that did not stick is an error,
not a silent success. Only the public Page/Locator API is used, so the CLI daemon
and the MCP server share this one implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast

__all__ = ["DateFormat", "DatePickError", "detect_format", "parse_iso", "pick_date"]

_SETTLE_MS = 250  # a calendar re-renders after each click
_MAX_MONTH_STEPS = 48  # four years either way

Order = Literal["ymd", "mdy", "dmy"]


class DatePickError(RuntimeError):
    """The date could not be set; the message says what the field showed instead."""


def parse_iso(text: str) -> date:
    match = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*", text or "")
    if not match:
        raise ValueError(f"date {text!r} must be YYYY-MM-DD, e.g. 2026-11-02")
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError as exc:
        raise ValueError(f"date {text!r} does not exist: {exc}") from exc


# one date inside a field's text: 10/23/2026, 2026-10-23, 23.10.2026
_TOKEN = re.compile(r"(\d{1,4})([/.\-])(\d{1,2})\2(\d{1,4})")


@dataclass(frozen=True)
class DateFormat:
    """How a field writes a date: the order of the parts, the separator, whether day
    and month get a leading zero, and what sits between the two dates of a range."""

    order: Order
    sep: str
    pad: bool
    range_sep: str = " - "

    def one(self, day: date) -> str:
        month = f"{day.month:02d}" if self.pad else str(day.month)
        dd = f"{day.day:02d}" if self.pad else str(day.day)
        year = f"{day.year:04d}"
        parts = {"ymd": (year, month, dd), "mdy": (month, dd, year), "dmy": (dd, month, year)}
        return self.sep.join(parts[self.order])

    def render(self, start: date, end: date | None = None) -> str:
        if end is None:
            return self.one(start)
        return f"{self.one(start)}{self.range_sep}{self.one(end)}"

    def parse_all(self, text: str) -> list[date]:
        found: list[date] = []
        for match in _TOKEN.finditer(text or ""):
            if match[2] != self.sep:
                continue
            a, b, c = int(match[1]), int(match[3]), int(match[4])
            year, month, day = {"ymd": (a, b, c), "mdy": (c, a, b), "dmy": (c, b, a)}[self.order]
            try:
                found.append(date(year, month, day))
            except ValueError:
                continue
        return found


def detect_format(sample: str, *, lang: str = "") -> DateFormat | None:
    """The format of the date(s) a field shows, or None when it shows no date.

    Month/day versus day/month is read from the value itself when one part is
    above 12 (``10/23/2026``); otherwise from the separator (``.`` is day-first) and
    the page language (English is month-first, the rest day-first).
    """
    tokens = list(_TOKEN.finditer(sample or ""))
    if not tokens:
        return None
    first = tokens[0]
    a, sep, b, c = first[1], first[2], first[3], first[4]
    order: Order
    if len(a) == 4:
        order = "ymd"
    elif len(c) == 4:
        x, y = int(a), int(b)
        if x > 12:
            order = "dmy"
        elif y > 12:
            order = "mdy"
        elif sep == ".":
            order = "dmy"
        else:
            language = lang.lower()
            order = "mdy" if not language or language.startswith("en") else "dmy"
    else:
        return None
    # the day and month parts of every date shown: one with a single digit means no padding
    pos = (3, 4) if order == "ymd" else (1, 3)
    day_month = [t[i] for t in tokens for i in pos]
    if any(len(part) == 1 for part in day_month):
        pad = False
    elif any(part.startswith("0") for part in day_month):
        pad = True
    else:
        # nothing to tell: ISO and dotted dates are padded by convention, slashes are not
        pad = order == "ymd" or sep == "."
    range_sep = sample[tokens[0].end() : tokens[1].start()] if len(tokens) > 1 else " - "
    return DateFormat(order=order, sep=sep, pad=pad, range_sep=range_sep or " - ")


# --- the page side ------------------------------------------------------------------

_FIELD_JS = r"""(el) => {
  const tag = el.tagName.toLowerCase();
  const isInput = tag === "input" || tag === "textarea";
  return {
    tag,
    input: isInput,
    type: isInput ? (el.type || "text").toLowerCase() : "",
    readonly: !!(el.readOnly || el.disabled || el.getAttribute("aria-readonly") === "true"),
    value: isInput ? el.value : (el.textContent || "").trim(),
    placeholder: el.getAttribute("placeholder") || "",
    lang: (el.closest("[lang]") || document.documentElement).getAttribute("lang") || "",
  };
}"""

_SET_NATIVE_JS = r"""(el, value) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return el.value;
}"""

# The field's own opener when clicking the field does nothing (Wijmo's InputDate opens only
# from its ▾ button): the nearest button-like element inside the field's component, at most
# four ancestors up — never one that contains the field (that would be the whole form).
_TOGGLE_JS = r"""(el) => {
  document.querySelectorAll("[data-visus-toggle]")
    .forEach((t) => t.removeAttribute("data-visus-toggle"));
  const visible = (n) => {
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(n).visibility !== "hidden";
  };
  const OPENERS = "button, [role=button], .wj-btn, [class*=toggle], [class*=calendar], "
    + "[class*=datepicker], [class*=date-picker], .input-group-addon, .input-group-append, "
    + ".input-group-text, [aria-haspopup]";
  let box = el.parentElement;
  for (let up = 0; box && up < 4; up++, box = box.parentElement) {
    const found = Array.from(box.querySelectorAll(OPENERS))
      .find((n) => n !== el && !n.contains(el) && visible(n));
    if (found) { found.setAttribute("data-visus-toggle", "1"); return true; }
  }
  return false;
}"""

_COMMIT_JS = r"""(el) => {
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}"""

# Finds every visible month panel (left to right), marks its clickable days with
# data-visus-day="<panel>:Y-M-D" and the month arrows with data-visus-nav="<panel>:prev|next"
# ("*:" when shared), and says which months are on screen.
_CALENDAR_JS = r"""() => {
  const MONTHS = {
    january: 0, february: 1, march: 2, april: 3, may: 4, june: 5, july: 6, august: 7,
    september: 8, october: 9, november: 10, december: 11,
    jan: 0, feb: 1, mar: 2, apr: 3, jun: 5, jul: 6, aug: 7, sep: 8, sept: 8, oct: 9,
    nov: 10, dec: 11,
    janeiro: 0, fevereiro: 1, marco: 2, abril: 3, maio: 4, junho: 5, julho: 6, agosto: 7,
    setembro: 8, outubro: 9, novembro: 10, dezembro: 11,
    fev: 1, abr: 3, mai: 4, ago: 7, set: 8, out: 9, dez: 11,
    enero: 0, febrero: 1, marzo: 2, mayo: 4, junio: 5, julio: 6, septiembre: 8, setiembre: 8,
    octubre: 9, noviembre: 10, diciembre: 11, ene: 0, dic: 11,
  };
  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && parseFloat(s.opacity || "1") > 0.05;
  };
  const header = (text) => {
    const t = norm(text);
    if (!t || t.length > 40) return null;
    let m = t.match(/(\d{4})\s*년\s*(\d{1,2})\s*월/);
    if (m) return { year: +m[1], month: +m[2] - 1 };
    const year = t.match(/\b(19|20)\d{2}\b/);
    if (!year) return null;
    for (const word of t.split(/[^a-z]+/)) {
      if (word && Object.prototype.hasOwnProperty.call(MONTHS, word)) {
        return { year: +year[0], month: MONTHS[word] };
      }
    }
    m = t.match(/^(\d{4})\s*[./-]\s*(\d{1,2})$/);
    if (m) return { year: +m[1], month: +m[2] - 1 };
    m = t.match(/^(\d{1,2})\s*[./-]\s*(\d{4})$/);
    if (m) return { year: +m[2], month: +m[1] - 1 };
    return null;
  };

  document.querySelectorAll("[data-visus-day],[data-visus-nav]").forEach((el) => {
    el.removeAttribute("data-visus-day");
    el.removeAttribute("data-visus-nav");
  });

  const all = Array.from(document.body.querySelectorAll("*"));
  const dayOf = (el) => {
    const t = (el.textContent || "").trim();
    return /^\d{1,2}$/.test(t) ? +t : 0;
  };
  const leaves = all.filter((el) => el.children.length === 0 && dayOf(el) >= 1 && dayOf(el) <= 31
    && visible(el));
  const leafSet = new Set(leaves);
  // the deepest visible element whose own text is a month and a year
  const heads = [];
  for (const el of all) {
    if (leafSet.has(el) || !visible(el)) continue;
    const text = (el.textContent || "").trim();
    if (text.length > 40) continue;
    const parsed = header(text);
    if (!parsed) continue;
    if (Array.from(el.children).some((c) => header(c.textContent || ""))) continue;
    heads.push({ el, ...parsed });
  }

  const before = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  // a disabled day: by markup (class, aria, the not-allowed cursor) or by being greyed
  // out — far less contrast with its background than the other days of the month
  const OFF = new RegExp("(^|[\\s_-])(disabled|inactive|unavailable|blocked|not-allowed"
    + "|out-of-range)([\\s_-]|$)", "i");
  const offByMarkup = (el) => {
    for (let e = el, i = 0; e && i < 3; e = e.parentElement, i++) {
      const cls = typeof e.className === "string" ? e.className : "";
      const aria = e.getAttribute("aria-disabled") === "true";
      if (OFF.test(cls) || aria || e.hasAttribute("disabled")) {
        return true;
      }
      if (getComputedStyle(e).cursor === "not-allowed") return true;
    }
    return false;
  };
  const lum = (rgb) => {
    const m = (rgb || "").match(/[\d.]+/g);
    if (!m || m.length < 3) return null;
    if (m.length > 3 && +m[3] === 0) return null;
    const [r, g, b] = m.slice(0, 3).map((v) => +v / 255);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (el) => {
    const fg = lum(getComputedStyle(el).color);
    let bg = 1;
    for (let e = el, i = 0; e && i < 8; e = e.parentElement, i++) {
      const l = lum(getComputedStyle(e).backgroundColor);
      if (l !== null) { bg = l; break; }
    }
    return fg === null ? 1 : Math.abs(fg - bg);
  };

  const panels = [];
  for (let h = 0; h < heads.length; h++) {
    const head = heads[h];
    // the smallest ancestor holding a month's worth of days
    let box = head.el.parentElement;
    let inside = [];
    for (let up = 0; box && up < 10; up++, box = box.parentElement) {
      inside = leaves.filter((l) => box.contains(l));
      if (inside.length >= 28) break;
    }
    if (!box || inside.length < 28) continue;
    const nextHead = heads.find((o, k) => k !== h && box.contains(o.el) && before(head.el, o.el));
    const days = inside.filter((l) => before(head.el, l) && (!nextHead || before(l, nextHead.el)));
    // the month itself is the run 1, 2, 3 … N; what comes before and after it is the
    // greyed tail of the neighbouring months and must never be clicked
    const values = days.map((l) => +l.textContent.trim());
    let best = { at: -1, len: 0 };
    for (let i = 0; i < values.length; i++) {
      if (values[i] !== 1) continue;
      let j = i;
      while (j < values.length && values[j] === j - i + 1) j++;
      if (j - i > best.len) best = { at: i, len: j - i };
    }
    if (best.len < 28) continue;
    const run = days.slice(best.at, best.at + best.len);
    const levels = run.map(contrast);
    // the most contrasted day is what an enabled one looks like here — not the median:
    // when the end limits the start, most of the month can be greyed out
    const reference = Math.max(...levels);
    const greyed = (i) => reference >= 0.35 && levels[i] < reference * 0.55;
    const rect = box.getBoundingClientRect();
    panels.push({
      year: head.year, month: head.month, days: best.len, el: box, head: head.el, run,
      off: run.map((cell, i) => offByMarkup(cell) || greyed(i)), left: rect.left, right: rect.right,
      x: head.el.getBoundingClientRect().left, y: head.el.getBoundingClientRect().top,
    });
  }
  // left to right (then top to bottom): the 1st is where a range starts, the last where it ends
  panels.sort((a, b) => (Math.abs(a.y - b.y) > 40 ? a.y - b.y : a.x - b.x));
  panels.forEach((p, index) => {
    p.enabled = 0;
    p.run.forEach((cell, i) => {
      if (p.off[i]) return;
      p.enabled++;
      cell.setAttribute("data-visus-day", `${index}:${p.year}-${p.month + 1}-${i + 1}`);
    });
  });

  // the month arrows: by label first (aria-label, title, class, a symbol), then by
  // position — the leftmost and rightmost small clickables on a header's row. Each one
  // belongs to the calendar whose header it sits on ("0:next"), or to all ("*:next")
  const PREV = /\b(prev|previous|anterior|back|backward|left|atras)\b|이전/;
  const NEXT = /\b(next|proximo|proxima|seguinte|siguiente|forward|right|avancar)\b|다음/;
  const PREV_SYM = new Set(["‹", "«", "<", "◀", "◂", "←", "❮", "<<"]);
  const NEXT_SYM = new Set(["›", "»", ">", "▶", "▸", "→", "❯", ">>"]);
  const navs = panels.map(() => ({ prev: null, next: null }));
  const shared = { prev: null, next: null };
  if (panels.length) {
    let root = panels[0].el;
    while (root.parentElement && !panels.every((p) => root.contains(p.el))) {
      root = root.parentElement;
    }
    root = root.parentElement || root;
    const rows = panels.map((p) => p.head.getBoundingClientRect());
    const onHeaderRow = (el) => {
      const r = el.getBoundingClientRect();
      const cy = r.top + r.height / 2;
      return rows.some((h) => Math.abs(cy - (h.top + h.height / 2)) < 40);
    };
    const clickable = Array.from(root.querySelectorAll("*")).filter((el) => {
      if (leafSet.has(el) || !visible(el) || leaves.some((l) => el.contains(l))) return false;
      if (heads.some((h) => h.el === el)) return false;
      const tag = el.tagName.toLowerCase();
      const pointer = tag === "button" || tag === "a" || el.getAttribute("role") === "button"
        || getComputedStyle(el).cursor === "pointer";
      return pointer && onHeaderRow(el);
    });
    const deepest = clickable.filter((el) => !clickable.some((o) => o !== el && el.contains(o)));
    const owner = (el) => {
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const i = panels.findIndex((p) => cx >= p.left && cx <= p.right);
      return i >= 0 ? navs[i] : shared;
    };
    const loose = [];
    for (const el of deepest) {
      const text = (el.textContent || "").trim();
      const cls = typeof el.className === "string" ? el.className.replace(/[-_]+/g, " ") : "";
      const label = norm(
        [el.getAttribute("aria-label"), el.getAttribute("title"), cls, text].join(" "));
      const slot = owner(el);
      if (PREV_SYM.has(text) || PREV.test(label)) { if (!slot.prev) slot.prev = el; }
      else if (NEXT_SYM.has(text) || NEXT.test(label)) { if (!slot.next) slot.next = el; }
      else if (text.length <= 2) loose.push(el);
    }
    // icon arrows with no label at all: the leftmost and rightmost of each calendar's row
    navs.forEach((slot, i) => {
      if (slot.prev && slot.next) return;
      const mine = loose.filter((el) => owner(el) === slot)
        .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
      if (mine.length >= 2) {
        slot.prev = slot.prev || mine[0];
        slot.next = slot.next || mine[mine.length - 1];
      }
    });
  }
  navs.forEach((slot, i) => {
    if (slot.prev) slot.prev.setAttribute("data-visus-nav", `${i}:prev`);
    if (slot.next && slot.next !== slot.prev) slot.next.setAttribute("data-visus-nav", `${i}:next`);
  });
  if (shared.prev) shared.prev.setAttribute("data-visus-nav", "*:prev");
  if (shared.next && shared.next !== shared.prev) {
    shared.next.setAttribute("data-visus-nav", "*:next");
  }
  return {
    panels: panels.map((p, i) => ({
      index: i, year: p.year, month: p.month + 1, days: p.days, enabled: p.enabled,
      prev: !!navs[i].prev, next: !!navs[i].next,
    })),
    prev: !!shared.prev,
    next: !!shared.next,
  };
}"""

_APPLY_JS = r"""() => {
  const WORDS = new RegExp("^(apply|ok|done|confirm|select|aplicar|confirmar|selecionar"
    + "|concluir|aceptar|확인|적용)$", "i");
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };
  const button = Array.from(document.querySelectorAll("button,[role=button],a,input[type=button]"))
    .find((el) => visible(el) && WORDS.test(((el.value || el.textContent) || "").trim()));
  if (!button) return false;
  button.setAttribute("data-visus-apply", "1");
  return true;
}"""


def _value(field: Any) -> str:
    try:
        return str(field.input_value())
    except Exception:  # noqa: BLE001 -- not an <input>: the text it shows
        return str(field.text_content() or "").strip()


class _DayDisabled(DatePickError):
    """The day is greyed out in its calendar (e.g. a start after the current end)."""


def _describe(scan: dict[str, Any]) -> str:
    """What the calendar shows, for the error — the agent decides from it (and the screen)."""
    shown = [
        f"calendar {int(p['index']) + 1} shows {int(p['year'])}-{int(p['month']):02d} "
        f"({int(p['enabled'])} days clickable)"
        for p in scan.get("panels", [])
    ]
    return "; ".join(shown) or "no calendar on screen"


def _arrow(page: Any, index: int, direction: str) -> Any | None:
    """The arrow of THIS calendar; else one shared by all; else any in that direction."""
    for selector in (
        f'[data-visus-nav="{index}:{direction}"]',
        f'[data-visus-nav="*:{direction}"]',
        f'[data-visus-nav$=":{direction}"]',
    ):
        found = page.locator(selector)
        if found.count():
            return found.first()
    return None


Slot = Literal["first", "last", "any"]


def _click_day(page: Any, day: date, slot: Slot, reopen: Any) -> None:
    """Steps ``slot``'s calendar to ``day``'s month with its arrows, then clicks the day.

    ``first``/``last``: the start of a range goes in the first calendar and the end in
    the last — in a picker with two independent calendars (one for each end, each with
    its own arrows) that is the only way that works, and in a picker whose arrows move
    both months it works just the same. ``any``: a single date, wherever its month is.
    """
    want = (day.year, day.month)
    reopened = False
    seen: tuple[int, int] | None = None
    stuck = 0
    for _ in range(_MAX_MONTH_STEPS):
        scan = cast(dict[str, Any], page.evaluate(_CALENDAR_JS))
        panels = scan.get("panels", [])
        if not panels:
            if not reopened:  # it closed after the previous click: open it again
                reopen()
                reopened = True
                continue
            raise DatePickError(
                "no calendar is open after clicking the field — open it (its calendar icon) "
                "and try again, or fill the field as text"
            )
        months = [(int(p["year"]), int(p["month"])) for p in panels]
        if slot == "first":
            index = 0
        elif slot == "last":
            index = len(panels) - 1
        elif want in months:
            index = months.index(want)
        else:
            index = len(panels) - 1 if want > max(months) else 0
        month = months[index]
        if month == want:
            cell = page.locator(f'[data-visus-day="{index}:{day.year}-{day.month}-{day.day}"]')
            if cell.count() == 0:
                raise _DayDisabled(
                    f"{day.isoformat()} is disabled in calendar {index + 1} ({_describe(scan)})"
                )
            cell.first().click()
            page.wait_for_timeout(_SETTLE_MS)
            return
        direction = "next" if want > month else "prev"
        stuck = stuck + 1 if month == seen else 0
        if stuck >= 2:
            raise DatePickError(
                f"the {direction} arrow does not move calendar {index + 1} ({_describe(scan)})"
            )
        seen = month
        arrow = _arrow(page, index, direction)
        if arrow is None:
            raise DatePickError(
                f"calendar {index + 1} has no {direction} arrow to reach "
                f"{day.year}-{day.month:02d} ({_describe(scan)})"
            )
        arrow.click()
        page.wait_for_timeout(150)
    raise DatePickError(f"could not reach {day.year}-{day.month:02d} ({_describe(scan)})")


def _shows(fmt: DateFormat | None, value: str, wanted: list[date]) -> bool:
    if fmt is not None:
        return fmt.parse_all(value)[: len(wanted)] == wanted
    # no format to read it with: at least every wanted day number is there
    return all(re.search(rf"(?<!\d)0?{d.day}(?!\d)", value) for d in wanted) and bool(value)


def pick_date(page: Any, field: Any, start: date | str, end: date | str | None = None) -> str:
    """Set ``field`` to ``start`` (or to the range ``start``–``end``); returns what the
    field shows afterwards. Raises :class:`DatePickError` when it did not stick.

    Dates are :class:`datetime.date` or ``YYYY-MM-DD`` text (what a generated script
    passes: ``pick_date(page, page.locator("#range"), "2026-11-02", "2026-11-06")``).
    """
    if isinstance(start, str):
        start = parse_iso(start)
    if isinstance(end, str):
        end = parse_iso(end)
    if end is not None and end < start:
        start, end = end, start
    wanted = [start] if end is None else [start, end]
    loc = field.first()
    info = cast(dict[str, Any], loc.evaluate(_FIELD_JS))

    if info.get("type") in ("date", "datetime-local", "month"):
        if end is not None:
            raise DatePickError(
                "a native date field holds one date: pick the start and the end in their two fields"
            )
        loc.evaluate(_SET_NATIVE_JS, start.isoformat())
        value = _value(loc)
        if not value.startswith(start.isoformat()[: 7 if info.get("type") == "month" else 10]):
            raise DatePickError(f"the field refused {start.isoformat()} and shows {value!r}")
        return f"date set: {value}"

    lang = str(info.get("lang", ""))
    fmt = detect_format(str(info.get("value", "")), lang=lang) or detect_format(
        str(info.get("placeholder", "")), lang=lang
    )

    # typing first, only where the field takes it — and only if it sticks: a read-only
    # field (the GMES one) or a masked one goes straight to its calendar
    if fmt is not None and info.get("input") and not info.get("readonly"):
        loc.fill(fmt.render(start, end))
        loc.evaluate(_COMMIT_JS)
        loc.blur()
        page.wait_for_timeout(_SETTLE_MS)
        value = _value(loc)
        if _shows(fmt, value, wanted):
            return f"date set: {value} (typed)"

    def reopen() -> None:
        loc.click()
        page.wait_for_timeout(_SETTLE_MS)
        scan = cast(dict[str, Any], page.evaluate(_CALENDAR_JS))
        if not scan.get("panels") and loc.evaluate(_TOGGLE_JS):
            # clicar no campo não abriu nada: o calendário abre pelo botão do componente
            page.locator("[data-visus-toggle]").first().click()
            page.wait_for_timeout(_SETTLE_MS)

    reopen()
    if end is None:
        _click_day(page, start, "any", reopen)
    else:
        try:
            _click_day(page, start, "first", reopen)
            _click_day(page, end, "last", reopen)
        except _DayDisabled:
            # two calendars that limit each other: the start one greys out every day after
            # the CURRENT end — move the end first, then the start
            _click_day(page, end, "last", reopen)
            _click_day(page, start, "first", reopen)
    value = _value(loc)
    if not _shows(fmt, value, wanted) and page.evaluate(_APPLY_JS):
        page.locator("[data-visus-apply]").first().click()
        page.wait_for_timeout(_SETTLE_MS)
        value = _value(loc)
    if not _shows(fmt, value, wanted):
        expected = fmt.render(start, end) if fmt else " ~ ".join(d.isoformat() for d in wanted)
        raise DatePickError(
            f"the calendar was used but the field shows {value!r}, not {expected!r}"
        )
    return f"date set: {value} (calendar)"
