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

from .model import Relation, Task

TASK_STATUS = ("open", "doing", "done", "dropped")
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
    art = Artifact(label=label, path=str(data.get("path", "")).strip(),
                   url=str(data.get("url", "")).strip(),
                   kind=str(data.get("kind", "doc")).strip() or "doc")
    project.artifacts.append(art)
    return art
