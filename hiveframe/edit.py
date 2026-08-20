"""Structural edits to a project: charter fields, tasks, relations.

Every function here takes a loaded ``Project``, mutates it, and hands it back.
The caller saves. Splitting mutation from persistence keeps validation in one
place and means a rejected edit never reaches the disk.

The rules that are enforced rather than suggested:

- a task keeps a stable id, generated once from its title and never rewritten,
  because ``blocked_by`` refers to ids and a renamed id silently breaks a chain
- a task cannot block itself, directly or through a cycle, since a cycle makes
  every task in it permanently unstartable and the board would just show a
  stalled project with no explanation
- a relation verdict is confirm or reject, never delete. A rejected relation is
  evidence that the question was asked and answered; deleting it means the same
  suggestion arrives again next month looking new.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .model import (KINDS, TIER_PARENT, TIERS, Charter, Project, Relation,
                    Task)

TASK_STATUS = ("open", "doing", "validate", "done", "dropped")
# Mirrors the verdict vocabulary: a project created here can only start in a
# state the review screen already knows how to change.
PROJECT_STATUS = ("active", "blocked", "paused", "done", "killed")
RELATION_VERDICTS = ("confirmed", "rejected", "suggested")


class EditError(Exception):
    """An edit was refused. The project is unchanged."""


def _slug(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32] or "task"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _as_date(value):
    if value in (None, "", "none"):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise EditError(f"{value!r} is not a date in YYYY-MM-DD form") from e


def _find_task(project, task_id: str) -> Task:
    for t in project.tasks:
        if t.id == task_id:
            return t
    raise EditError(f"no task {task_id!r} in {project.id}")


def _canon_path(path: str) -> str:
    p = Path(path).expanduser()
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def _as_paths(value) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if str(v).strip()]


def _would_cycle(project, task_id: str, deps: list[str]) -> bool:
    """Depth-first walk from each proposed dependency back to the task."""
    by_id = {t.id: t for t in project.tasks}
    seen: set[str] = set()

    def reaches(start: str) -> bool:
        if start == task_id:
            return True
        if start in seen or start not in by_id:
            return False
        seen.add(start)
        return any(reaches(d) for d in by_id[start].blocked_by)

    return any(reaches(d) for d in deps)


def new_project(existing, fields: dict):
    """A project created from something that was only ever a note.

    Kept deliberately thin. A project made in one click from a carry-forward
    item is a placeholder for a decision, not a finished charter, so this fills
    in what is known (the problem it came from) and leaves the rest missing on
    purpose. The board already flags an incomplete charter, and an invented
    hypothesis would silence that flag without answering it.
    """
    name = str(fields.get("name", "")).strip()
    if not name:
        raise EditError("a project needs a name")

    tier = str(fields.get("tier") or "project").strip()
    if tier not in TIERS:
        raise EditError(f"unknown tier {tier!r}")
    kind = str(fields.get("kind") or "initiative").strip()
    if kind not in KINDS:
        raise EditError(f"unknown kind {kind!r}")

    taken = {p.id for p in existing}
    parent = str(fields.get("parent", "")).strip()
    if parent:
        if parent not in taken:
            raise EditError(f"no such parent project {parent!r}")
        allowed = TIER_PARENT.get(tier, ())
        if not allowed:
            raise EditError(f"a {tier} does not sit under anything")
        parent_tier = next(p.tier for p in existing if p.id == parent)
        if parent_tier not in allowed:
            raise EditError(f"a {tier} cannot sit under a {parent_tier}")

    project = Project(
        id=_slug(name, taken),
        name=name,
        tier=tier,
        parent=parent,
        kind=kind,
        horizon=str(fields.get("horizon", "")).strip(),
        status=str(fields.get("status") or "active").strip(),
        store=str(fields.get("store") or "work").strip(),
        charter=Charter(problem=str(fields.get("problem", "")).strip()),
    )
    if project.status not in PROJECT_STATUS:
        raise EditError(f"unknown status {project.status!r}")
    return project


def edit_charter(project, fields: dict):
    allowed = ("problem", "hypothesis", "goal", "kill_when", "done_when")
    for k, v in fields.items():
        if k == "constraints":
            if isinstance(v, str):
                v = [s.strip() for s in v.split("\n") if s.strip()]
            project.charter.constraints = list(v)
        elif k in allowed:
            setattr(project.charter, k, str(v).strip())
        else:
            raise EditError(f"charter has no field {k!r}")
    return project


def edit_project(project, fields: dict):
    allowed = ("name", "kind", "horizon")
    for k, v in fields.items():
        if k not in allowed:
            raise EditError(f"{k!r} is not editable here")
        setattr(project, k, str(v).strip())
    return project


def add_task(project, data: dict) -> Task:
    title = str(data.get("title", "")).strip()
    if not title:
        raise EditError("a task needs a title")
    taken = {t.id for t in project.tasks}
    task = Task(
        id=_slug(title, taken),
        title=title,
        status=data.get("status", "open"),
        due=_as_date(data.get("due")),
        effort_h=float(data.get("effort_h") or 0),
        urgent=bool(data.get("urgent")),
        important=bool(data.get("important")),
        blocked_by=[d for d in (data.get("blocked_by") or []) if d in taken],
        files=[_canon_path(p) for p in _as_paths(data.get("files"))],
        note=str(data.get("note", "")).strip(),
    )
    if task.status not in TASK_STATUS:
        raise EditError(f"unknown task status {task.status!r}")
    project.tasks.append(task)
    return task


def edit_task(project, task_id: str, fields: dict) -> Task:
    t = _find_task(project, task_id)
    for k, v in fields.items():
        if k == "title":
            v = str(v).strip()
            if not v:
                raise EditError("a task needs a title")
            t.title = v
        elif k == "status":
            if v not in TASK_STATUS:
                raise EditError(f"unknown task status {v!r}")
            t.status = v
        elif k == "due":
            t.due = _as_date(v)
        elif k == "effort_h":
            t.effort_h = float(v or 0)
        elif k in ("urgent", "important"):
            setattr(t, k, bool(v))
        elif k == "note":
            t.note = str(v).strip()
        elif k == "blocked_by":
            deps = [d for d in (v or []) if d != task_id]
            unknown = [d for d in deps if d not in {x.id for x in project.tasks}]
            if unknown:
                raise EditError(f"no such task(s): {', '.join(unknown)}")
            if _would_cycle(project, task_id, deps):
                raise EditError(
                    "that dependency closes a loop, which would make every task "
                    "in it permanently unstartable")
            t.blocked_by = deps
        elif k == "files":
            t.files = [_canon_path(p) for p in _as_paths(v)]
        else:
            raise EditError(f"a task has no field {k!r}")
    return t


def drop_task(project, task_id: str, reason: str) -> Task:
    """Tasks are dropped with a reason, not deleted.

    A deleted task takes its estimate and its history with it, and the capacity
    numbers quietly improve for no reason anyone can point at.
    """
    if not (reason or "").strip():
        raise EditError("dropping a task needs a reason")
    t = _find_task(project, task_id)
    t.status = "dropped"
    t.note = (t.note + " | " if t.note else "") + f"dropped: {reason.strip()}"
    return t


def set_relation(project, to: str, verdict: str, note: str = "") -> Relation:
    if verdict not in RELATION_VERDICTS:
        raise EditError(f"unknown relation verdict {verdict!r}")
    for r in project.relations:
        if r.to == to:
            r.status = verdict
            if note:
                r.note = note.strip()
            return r
    raise EditError(f"no relation to {to!r} on {project.id}")


def add_relation(project, to: str, type_: str, note: str = "") -> Relation:
    if not to.strip():
        raise EditError("a relation needs a target project id")
    if to == project.id:
        raise EditError("a project cannot relate to itself")
    if any(r.to == to for r in project.relations):
        raise EditError(f"a relation to {to!r} already exists")
    # Declared by hand, so it is confirmed on arrival. Suggested is reserved for
    # relations a machine proposed, which is a claim that still needs a verdict.
    rel = Relation(to=to, type=type_ or "informs", status="confirmed",
                   note=note.strip())
    project.relations.append(rel)
    return rel


def add_artifact(project, data: dict):
    from .model import Artifact
    label = str(data.get("label", "")).strip()
    if not label:
        raise EditError("an artifact needs a label")
    path = str(data.get("path", "")).strip()
    kind = str(data.get("kind", "doc")).strip() or "doc"
    if path:
        p = Path(path).expanduser()
        if p.exists():
            kind = "folder" if p.is_dir() else "file" if p.is_file() else kind
        path = _canon_path(path)
    art_path = path
    if art_path and any((a.path and _canon_path(a.path) == art_path) for a in project.artifacts):
        raise EditError(f"that path is already listed on {project.id}")
    art = Artifact(label=label, path=art_path,
                   url=str(data.get("url", "")).strip(),
                   kind=kind)
    project.artifacts.append(art)
    return art


def add_task_file(project, task_id: str, data: dict):
    t = _find_task(project, task_id)
    path = _canon_path(str(data.get("path", "")).strip())
    if not path.strip():
        raise EditError("a task file needs a path")
    p = Path(path)
    if not p.exists():
        raise EditError(f"file not found: {path}")
    if not p.is_file():
        raise EditError("task files must be files, not folders")
    if any(_canon_path(x) == path for x in t.files):
        raise EditError("that file is already attached to the task")
    t.files.append(path)
    return t


def remove_task_file(project, task_id: str, data: dict):
    t = _find_task(project, task_id)
    path = _canon_path(str(data.get("path", "")).strip())
    if not path.strip():
        raise EditError("a task file needs a path")
    files = [x for x in t.files if _canon_path(x) != path]
    if len(files) == len(t.files):
        raise EditError("that file is not attached to the task")
    t.files = files
    return t


# ---- tools ---------------------------------------------------------------
# Tools are edited in the registry, and attached to projects by id. Attaching a
# copy instead of a reference is the mistake this whole section exists to avoid:
# three copies of a description disagree within a month, and then nobody trusts
# any of them.

TOOL_STATUS = ("active", "experimental", "unused", "retired")
TOOL_ACCESS = ("read-only", "read-write-local", "write")


def set_uses(project, tool_ids: list[str], known: set[str]):
    """Declare which tools a project depends on.

    Unknown ids are refused rather than silently dropped. A dependency on a tool
    that does not exist is either a typo or a tool nobody registered, and both
    are worth stopping on.
    """
    ids = [t.strip() for t in tool_ids if t and t.strip()]
    unknown = [t for t in ids if t not in known]
    if unknown:
        raise EditError(f"no registered tool(s): {', '.join(unknown)}")
    project.uses = sorted(dict.fromkeys(ids))
    return project


def upsert_tool(tools: list, data: dict):
    """Add a tool, or update the one with the same id."""
    from .model import Tool
    tid = str(data.get("id", "")).strip()
    if not tid:
        raise EditError("a tool needs an id")
    status = str(data.get("status", "active")).strip() or "active"
    access = str(data.get("access", "read-only")).strip() or "read-only"
    if status not in TOOL_STATUS:
        raise EditError(f"unknown tool status {status!r}")
    if access not in TOOL_ACCESS:
        raise EditError(f"unknown access mode {access!r}")

    existing = next((t for t in tools if t.id == tid), None)
    target = existing or Tool(id=tid)
    target.name = str(data.get("name", target.name)).strip()
    target.does = str(data.get("does", target.does)).strip()
    target.where = str(data.get("where", target.where)).strip()
    target.path = str(data.get("path", target.path)).strip()
    target.note = str(data.get("note", target.note)).strip()
    target.status = status
    target.access = access
    if existing is None:
        tools.append(target)
    return target


def retire_tool(tools: list, tool_id: str, reason: str, usage: dict):
    """Retire a tool. Refused while a project still declares it.

    Retiring something another project depends on is how a board loses a
    capability it did not know it was using.
    """
    if not (reason or "").strip():
        raise EditError("retiring a tool needs a reason")
    t = next((x for x in tools if x.id == tool_id), None)
    if t is None:
        raise EditError(f"no tool {tool_id!r} in the registry")
    users = usage.get(tool_id, [])
    if users:
        raise EditError(
            f"{tool_id} is still declared by: {', '.join(users)}. "
            "Remove the dependency first, or say why it is no longer needed there.")
    t.status = "retired"
    t.note = (t.note + " | " if t.note else "") + f"retired: {reason.strip()}"
    return t
