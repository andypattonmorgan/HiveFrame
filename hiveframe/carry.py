"""Carry-forward items, as decisions rather than a standing list.

CARRY-FORWARD.md is the memory between working sessions: things agreed in one
session that must surface in the next. It is read by start_my_day.py and printed
at the top of the morning briefing.

The failure mode it grows into is a list nobody acts on. Nineteen items printed
every morning is not a reminder, it is wallpaper: the cost of reading it stays
the same every day and the list only gets longer, so the rational response is to
skip it. This module turns each item into something with exactly three exits:
put it on a project as a task, make it a project of its own, or drop it.

Nothing is deleted. An item that leaves the file is appended to the archive with
the date, what it became, and its full original text, because the point is to
make the list actionable, not to lose the things on it. The archive is the
receipt: it answers "what happened to that thing we agreed" months later, which
a deleted bullet cannot.

Identity is content derived. There is no id in the markdown and adding one would
make the file worse to hand-edit, so an item is identified by a hash of its own
text. Editing an item changes its id, which is correct: it is then a different
item, and acting on a stale id fails loudly instead of removing the wrong
bullet.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date
from pathlib import Path

# Both files live beside the operator's working notes, not in a store. The
# location is environment overridable so a second adopter never inherits a path
# from this one.
CARRY_PATH = Path(os.environ.get(
    "HIVEFRAME_CARRY_FILE",
    Path.home() / "Library" / "CloudStorage" / "OneDrive-KaiserPermanente"
    / "KaiserKM" / "CARRY-FORWARD.md")).expanduser()

ARCHIVE_NAME = "CARRY-FORWARD-ARCHIVE.md"

OUTCOMES = ("task", "project", "drop")

_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_HEADING_RE = re.compile(r"^##\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_DUE_RE = re.compile(r"\(due (\d{4})-(\d{2})-(\d{2})\)")


class CarryError(RuntimeError):
    """Raised when the file cannot be read, or an item is not there."""


def _archive_path(path: Path) -> Path:
    return path.parent / ARCHIVE_NAME


def _item_id(text: str) -> str:
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


def _title_of(first_line: str) -> str:
    """The bolded lead, which is how these are written, else the first clause."""
    m = _BOLD_RE.search(first_line)
    if m:
        return m.group(1).strip().rstrip(".")
    plain = re.sub(r"\s+", " ", first_line).strip()
    cut = plain.split(". ")[0]
    return (cut if len(cut) <= 90 else cut[:87] + "...").strip().rstrip(".")


def parse(path: Path | None = None) -> list[dict]:
    """Every bullet in the file, with the line range it occupies.

    The range is what makes removal exact. Rewriting the file from parsed
    objects would reformat every item the operator hand-wrote, so the file is
    edited by cutting lines rather than by regenerating it.
    """
    path = Path(path or CARRY_PATH)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise CarryError(f"could not read {path.name}: {e}") from e

    items: list[dict] = []
    heading = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        h = _HEADING_RE.match(line)
        if h:
            heading = h.group(1).strip()
            i += 1
            continue
        b = _BULLET_RE.match(line)
        if not b:
            i += 1
            continue

        start = i
        body = [b.group(1).rstrip()]
        i += 1
        # Continuation lines are indented. A blank line only continues the item
        # if indented content follows it, otherwise it is the separator before
        # the next bullet and does not belong to this one.
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                j = i
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and lines[j].startswith(("  ", "\t")) \
                        and not _BULLET_RE.match(lines[j].strip()):
                    i = j
                    continue
                break
            if _BULLET_RE.match(nxt) or _HEADING_RE.match(nxt):
                break
            if nxt.startswith(("  ", "\t")):
                body.append(nxt.strip())
                i += 1
                continue
            break
        end = i  # exclusive

        text = " ".join(body).strip()
        due, due_state = "", ""
        m = _DUE_RE.search(text)
        if m:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            today = date.today()
            due = d.isoformat()
            due_state = ("overdue" if d < today
                         else "today" if d == today else "upcoming")
        items.append({
            "id": _item_id(text),
            "heading": heading,
            "title": _title_of(body[0]),
            "text": text,
            "detail": " ".join(body[1:]).strip(),
            "due": due,
            "due_state": due_state,
            "line_start": start,
            "line_end": end,
        })
    return items


def get(item_id: str, path: Path | None = None) -> dict:
    for it in parse(path):
        if it["id"] == item_id:
            return it
    raise CarryError("that carry-forward item is no longer in the file")


def _tidy(lines: list[str]) -> list[str]:
    """Drop headings left with no bullets, and collapse blank runs."""
    out: list[str] = []
    for n, line in enumerate(lines):
        if _HEADING_RE.match(line):
            has_item = False
            for later in lines[n + 1:]:
                if _HEADING_RE.match(later):
                    break
                if _BULLET_RE.match(later):
                    has_item = True
                    break
            if not has_item:
                continue
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def resolve(item_id: str, outcome: str, note: str = "",
            path: Path | None = None) -> dict:
    """Take an item out of the standing list and record where it went.

    Removing and archiving are one operation on purpose. Two calls could leave
    an item deleted with no record of it, which is the one outcome this is meant
    to prevent.
    """
    if outcome not in OUTCOMES:
        raise CarryError(f"unknown outcome {outcome!r}")
    path = Path(path or CARRY_PATH)
    item = get(item_id, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    original = lines[item["line_start"]:item["line_end"]]
    kept = _tidy(lines[:item["line_start"]] + lines[item["line_end"]:])

    archive = _archive_path(path)
    label = {"task": "became a task", "project": "became a project",
             "drop": "dropped"}[outcome]
    entry = [
        "",
        f"## {date.today():%Y-%m-%d} - {item['title']}",
        "",
        f"- Outcome: {label}{f' ({note})' if note else ''}",
        f"- Was under: {item['heading'] or 'no heading'}",
        "",
        "Original item:",
        "",
    ] + original + [""]

    try:
        if not archive.exists():
            archive.write_text(
                "# Carry-forward archive\n\n"
                "Items that left `CARRY-FORWARD.md`, and what they became.\n"
                "Written by HiveFrame. Nothing here is deleted from the record.\n",
                encoding="utf-8")
        with archive.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(entry) + "\n")
    except OSError as e:
        raise CarryError(f"could not write the archive: {e}") from e

    # The archive is written first. If this fails the item is still listed and
    # still recorded, which is recoverable; the reverse loses it.
    try:
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as e:
        raise CarryError(f"could not update {path.name}: {e}") from e

    return {"id": item_id, "outcome": outcome, "title": item["title"],
            "archive": str(archive)}
