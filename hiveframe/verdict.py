"""Triage verdicts and interruption capture: the only things HiveFrame writes.

Scope and posture
-----------------
Two write targets, both local files inside a store the caller already named:

  1. the ``status`` line in a project's own ``.toml``
  2. an append-only ``decisions.jsonl`` and ``inbox.jsonl`` beside the projects

Nothing else on the disk is touched, and no production system is written to at
all. Every data connector in the wider suite stays GET-only; this module does
not talk to any of them.

Why a surgical line edit rather than a rewrite
----------------------------------------------
A project file carries comments, ordering, and the operator's own phrasing. A
round-trip through a TOML writer would flatten all of that, and a tool that
quietly reformats a file you hand-wrote is a tool you stop trusting with your
files. So the verdict rewrites exactly one line, the ``status`` assignment in
the ``[project]`` table, and refuses if it cannot find exactly one.

Why the decision is logged separately
-------------------------------------
The status line records the current state. It cannot record why, or when, or
what the alternative was. A killed project whose reason is not written down
comes back six weeks later as a new idea. The log is the part that stops that,
so a verdict without a reason is rejected.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

VERDICTS = ("active", "blocked", "paused", "done", "killed")


class VerdictError(Exception):
    """A verdict was refused. The file is unchanged."""


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def set_status(source_file: Path, new_status: str) -> str:
    """Rewrite the project's status line in place. Returns the previous value.

    Raises rather than guessing. A file with no status line, or with more than
    one, is a file this function does not understand well enough to edit.
    """
    if new_status not in VERDICTS:
        raise VerdictError(
            f"unknown status {new_status!r}, expected one of {', '.join(VERDICTS)}")

    text = source_file.read_text(encoding="utf-8")
    pattern = re.compile(r'^(\s*status\s*=\s*)"([^"]*)"\s*$', re.MULTILINE)

    # Only the [project] table's status counts. Tasks and relations carry their
    # own status keys, and matching one of those would silently corrupt a task.
    head = text.split("\n[[", 1)[0]
    matches = list(pattern.finditer(head))
    if len(matches) != 1:
        raise VerdictError(
            f"expected exactly one project status line in {source_file.name}, "
            f"found {len(matches)}. Refusing to guess.")

    m = matches[0]
    previous = m.group(2)
    if previous == new_status:
        return previous

    new_head = head[:m.start()] + f'{m.group(1)}"{new_status}"' + head[m.end():]
    source_file.write_text(new_head + text[len(head):], encoding="utf-8")
    return previous


def record_verdict(project, new_status: str, reason: str,
                   store_root: Path) -> dict:
    """Apply a triage verdict and log it. Reason is mandatory.

    A verdict with no reason is indistinguishable from forgetting about the
    project, which is the state triage exists to end.
    """
    reason = (reason or "").strip()
    if not reason:
        raise VerdictError("a verdict needs a reason. Say why, in one line.")
    if project.source_file is None:
        raise VerdictError("this project has no source file to update")

    previous = set_status(Path(project.source_file), new_status)
    record = {
        "at": _stamp(),
        "project": project.id,
        "name": project.name,
        "from": previous,
        "to": new_status,
        "reason": reason,
        "open_tasks": len(project.open_tasks),
        "open_effort_h": project.open_effort_h,
        "source_file": str(project.source_file),
    }
    _append(store_root / "decisions.jsonl", record)
    return record


def capture(text: str, store_root: Path, project_id: str = "",
            task_id: str = "") -> dict:
    """Park an interruption without acting on it.

    The point is to get the thought out of working memory in under two seconds
    and keep going. It lands in a file rather than a toast message, because a
    capture box that discards what you typed teaches you not to use it.
    """
    text = (text or "").strip()
    if not text:
        raise VerdictError("nothing to capture")
    record = {"at": _stamp(), "text": text,
              "during_project": project_id, "during_task": task_id}
    _append(store_root / "inbox.jsonl", record)
    return record


def read_log(store_root: Path, name: str, limit: int = 50) -> list[dict]:
    """Most recent entries first. A missing log is an empty log, not an error."""
    path = store_root / name
    if not path.exists():
        return []
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return list(reversed(rows))[:limit]
