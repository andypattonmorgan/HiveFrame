"""Emit a project back to TOML, so the UI can edit what it displays.

Why a full emitter and not more surgical line edits
---------------------------------------------------
``verdict.set_status`` rewrites one known line and refuses if it cannot find
exactly one. That works for a single scalar with a fixed shape. It does not
extend to adding a task, editing a charter field, or confirming a relation,
because those change structure rather than a value, and a regex that edits
structure is a regex that will eventually corrupt a file.

So structural edits go through a real emitter: the model is the truth, and the
file is regenerated from it.

The cost, stated plainly
------------------------
Regenerating loses hand-written comments and any ordering the emitter does not
reproduce. That is a real loss and the reason this is not used for the status
verdict, which stays surgical. The mitigations are that the layout is stable
(so a diff shows only what changed), and that every rewrite leaves a ``.bak``
of the previous contents next to the file.

If you keep notes in TOML comments, put them in a task ``note`` or a charter
field instead. Those survive, because they are data rather than decoration.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path


def _s(value: str) -> str:
    """A TOML basic string. Escapes are the only ones TOML requires."""
    out = str(value).replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "")
    return f'"{out}"'


def _arr(values: list[str]) -> str:
    return "[" + ", ".join(_s(v) for v in values) + "]"


def _num(value: float) -> str:
    """Drop a pointless trailing .0 so 2 does not read as 2.0 in the file."""
    return str(int(value)) if float(value) == int(value) else str(value)


def _kv(key: str, value, pad: int = 0) -> str:
    k = key.ljust(pad)
    if isinstance(value, bool):
        return f"{k} = {'true' if value else 'false'}"
    if isinstance(value, date):
        return f"{k} = {value.isoformat()}"
    if isinstance(value, (int, float)):
        return f"{k} = {_num(value)}"
    if isinstance(value, list):
        return f"{k} = {_arr(value)}"
    return f"{k} = {_s(value)}"


def dumps(project) -> str:
    """Render a Project as TOML in the layout the hand-written files use."""
    L: list[str] = []

    L.append("[project]")
    L.append(_kv("id", project.id, 7))
    L.append(_kv("name", project.name, 7))
    # Altitude and containment sit next to identity. Losing parent on a write is
    # not a cosmetic bug: it silently orphans the project out of its program,
    # which is the same disappearance this tier model exists to prevent.
    L.append(_kv("tier", project.tier, 7))
    if project.parent:
        L.append(_kv("parent", project.parent, 7))
    L.append(_kv("kind", project.kind, 7))
    if project.horizon:
        L.append(_kv("horizon", project.horizon, 7))
    L.append(_kv("status", project.status, 7))
    L.append(_kv("store", project.store, 7))
    if project.folder:
        L.append(_kv("folder", project.folder, 7))
    if project.started:
        L.append(_kv("started", project.started, 7))
    if project.uses:
        # Tool ids, not tool descriptions. The registry owns the description, so
        # there is exactly one place to correct it when it changes.
        L.append(_kv("uses", project.uses, 7))

    c = project.charter
    # stop_when belongs to programs, done_when to projects. Both are written
    # when present rather than filtered by tier, so retiering a project does not
    # quietly destroy the ending someone already wrote down.
    charter_rows = [(k, getattr(c, k)) for k in
                    ("problem", "hypothesis", "goal", "kill_when", "done_when",
                     "stop_when")]
    charter_rows = [(k, v) for k, v in charter_rows if v]
    if charter_rows or c.constraints:
        L.append("")
        L.append("[charter]")
        for k, v in charter_rows:
            L.append(_kv(k, v, 10))
        if c.constraints:
            L.append(_kv("constraints", c.constraints, 10))

    for a in project.artifacts:
        L.append("")
        L.append("[[artifact]]")
        L.append(_kv("label", a.label, 5))
        if a.path:
            L.append(_kv("path", a.path, 5))
        if a.url:
            L.append(_kv("url", a.url, 5))
        L.append(_kv("kind", a.kind, 5))

    for t in project.tasks:
        L.append("")
        L.append("[[task]]")
        L.append(_kv("id", t.id, 9))
        L.append(_kv("title", t.title, 9))
        if t.due:
            L.append(_kv("due", t.due, 9))
        if t.effort_h:
            L.append(_kv("effort_h", t.effort_h, 9))
        if t.urgent:
            L.append(_kv("urgent", True, 9))
        if t.important:
            L.append(_kv("important", True, 9))
        L.append(_kv("status", t.status, 9))
        if t.blocked_by:
            L.append(_kv("blocked_by", t.blocked_by, 9))
        if t.files:
            L.append(_kv("files", t.files, 9))
        if t.note:
            L.append(_kv("note", t.note, 9))

    for r in project.relations:
        L.append("")
        L.append("[[relation]]")
        L.append(_kv("to", r.to, 6))
        L.append(_kv("type", r.type, 6))
        L.append(_kv("status", r.status, 6))
        if r.note:
            L.append(_kv("note", r.note, 6))

    return "\n".join(L) + "\n"


def save(project, path: Path | None = None) -> Path:
    """Write the project back to its file, keeping one backup.

    The backup is the undo. It is a single ``.bak`` rather than a history,
    because the file itself lives in a git-backed or cloud-synced directory and
    a second history here would only compete with that one.
    """
    target = Path(path or project.source_file)
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    target.write_text(dumps(project), encoding="utf-8")
    return target


def dumps_tools(tools) -> str:
    """Render the tool registry."""
    L = ["# Tool registry for this store.",
         "#",
         "# A tool is a capability that exists independently of any project.",
         "# Projects reference tools by id in their own `uses` list; they never",
         "# copy the description, so there is one place to correct it.",
         "#",
         "# Fields: does (one line, what it does), where (what it runs against),",
         "# path, status, access, note."]
    for t in tools:
        L.append("")
        L.append("[[tool]]")
        L.append(_kv("id", t.id, 7))
        if t.name:
            L.append(_kv("name", t.name, 7))
        if t.does:
            L.append(_kv("does", t.does, 7))
        if t.where:
            L.append(_kv("where", t.where, 7))
        if t.path:
            L.append(_kv("path", t.path, 7))
        L.append(_kv("status", t.status, 7))
        L.append(_kv("access", t.access, 7))
        if t.note:
            L.append(_kv("note", t.note, 7))
    return "\n".join(L) + "\n"


def save_tools(tools, root: Path) -> Path:
    from .model import TOOLS_FILE
    target = Path(root) / TOOLS_FILE
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    target.write_text(dumps_tools(tools), encoding="utf-8")
    return target
