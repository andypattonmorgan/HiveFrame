"""Data model and loader for HiveFrame.

One TOML file per project. The file is the contract: it is diffable, greppable,
editable by hand, and readable without this application. If the UI is thrown
away, nothing is lost.

Two stores, work and personal, resolved from separate roots. The boundary is
enforced here rather than in the UI, because a boundary enforced at the display
layer is a boundary that leaks the first time someone adds a view.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

STORES = ("work", "personal")

# Relation types. Only "blocks" and "feeds" drive behaviour; the rest record
# meaning. Keeping them distinct is the point: an untyped edge says two things
# are related without saying what follows from that.
RELATION_TYPES = ("feeds", "blocks", "shares-evidence", "supersedes", "informs")

# A relation proposed by the assistant has no effect until a human confirms it.
RELATION_STATUS = ("suggested", "confirmed", "rejected")

# Statuses that still carry work. "blocked" is live: something outside my control
# is in the way, which is a fact about the world, not a reason to rank the project
# down. There is almost always a move that attacks the block, and that move is
# usually more urgent than the work it is holding up.
LIVE_STATUSES = ("active", "blocked")


class StoreError(RuntimeError):
    """Raised when a caller reaches for a store it is not allowed to see."""


@dataclass
class Tool:
    """A capability that exists independently of any project.

    Tools are declared once in ``tools.toml`` and referenced by projects through
    ``uses``. They are deliberately not members of a project: a connector is not
    owned by whatever happened to need it first, and copying its description into
    three project files guarantees the three copies disagree within a month.

    The registry is worth having for one reason beyond tidiness. Once tools are
    declared separately, "which tools does nothing depend on" becomes a question
    the board can answer, and that list is where the unkilled work has been
    hiding.
    """
    id: str
    name: str = ""
    does: str = ""                # what it does, one line
    where: str = ""               # where it runs or what it reads
    path: str = ""
    status: str = "active"        # active | experimental | unused | retired
    access: str = "read-only"     # read-only | read-write-local | write
    note: str = ""

    @property
    def exists(self) -> bool:
        if not self.path:
            return False
        return Path(self.path).expanduser().exists()

    @property
    def documented(self) -> bool:
        """A tool nobody can describe in one line is a tool nobody can hand over."""
        return bool(self.does.strip())


@dataclass
class Artifact:
    label: str
    path: str = ""
    url: str = ""
    kind: str = "doc"

    @property
    def exists(self) -> bool:
        if not self.path:
            return False
        return Path(self.path).expanduser().exists()


@dataclass
class Task:
    id: str
    title: str
    status: str = "open"          # open | doing | done | dropped
    due: date | None = None
    effort_h: float = 0.0
    urgent: bool = False
    important: bool = False
    blocked_by: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def open(self) -> bool:
        return self.status in ("open", "doing")

    def days_left(self, today: date | None = None) -> int | None:
        if self.due is None:
            return None
        return (self.due - (today or date.today())).days


@dataclass
class Relation:
    to: str
    type: str = "informs"
    status: str = "suggested"
    note: str = ""


@dataclass
class Charter:
    """The defining context. Kept on screen at all times in the project view.

    Drift happens when the goal is out of sight, so this is not collapsible and
    not on a second tab.
    """
    problem: str = ""
    hypothesis: str = ""
    goal: str = ""
    kill_when: str = ""
    done_when: str = ""
    constraints: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.problem and self.goal and self.done_when)

    @property
    def missing(self) -> list[str]:
        gaps = []
        for name in ("problem", "hypothesis", "goal", "kill_when", "done_when"):
            if not getattr(self, name):
                gaps.append(name)
        return gaps


@dataclass
class Project:
    id: str
    name: str
    kind: str = "initiative"      # initiative | experiment | commitment | admin
    horizon: str = ""             # H1 | H2 | H3
    status: str = "active"        # active | blocked | paused | done | killed
    store: str = "work"
    folder: str = ""              # the working directory this project lives in
    started: date | None = None
    charter: Charter = field(default_factory=Charter)
    artifacts: list[Artifact] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)   # tool ids, not tool copies
    source_file: Path | None = None

    @property
    def folders(self) -> list[tuple[str, str]]:
        """The directories that belong to this project, as (label, path).

        A declared ``folder`` is the whole answer. Otherwise the fallback is any
        artifact whose path is a directory. A project is worked in a place, and
        the file view should show that place rather than the whole store: a tree
        that lists everything is the same context bleed the charter exists to
        stop.

        Nested paths are dropped in favour of the outermost one, so a folder is
        not drawn twice.
        """
        out: list[tuple[str, str]] = []
        if self.folder:
            out.append(("Project folder", self.folder))
        else:
            for a in self.artifacts:
                if not a.path:
                    continue
                try:
                    if Path(a.path).expanduser().is_dir():
                        out.append((a.label or "Folder", a.path))
                except OSError:
                    continue

        kept: list[tuple[str, str]] = []
        seen: list[Path] = []
        for label, raw in out:
            p = Path(raw).expanduser()
            try:
                resolved = p.resolve()
            except OSError:
                continue
            if any(resolved == s or s in resolved.parents for s in seen):
                continue
            seen.append(resolved)
            kept.append((label, str(p)))
        return kept

    @property
    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.open]

    @property
    def open_effort_h(self) -> float:
        return sum(t.effort_h for t in self.open_tasks)

    @property
    def actionable_tasks(self) -> list[Task]:
        """Open tasks whose prerequisites are already done.

        These are the moves available right now. A project can be blocked and
        still have several of them, which is the whole point of the distinction.
        """
        open_ids = {t.id for t in self.open_tasks}
        return [t for t in self.open_tasks
                if not any(dep in open_ids for dep in t.blocked_by)]

    @property
    def stalled(self) -> bool:
        """Live, has open work, and no move available. Nothing I can do today."""
        return bool(self.open_tasks) and not self.actionable_tasks

    @property
    def confirmed_relations(self) -> list[Relation]:
        return [r for r in self.relations if r.status == "confirmed"]

    @property
    def pending_relations(self) -> list[Relation]:
        return [r for r in self.relations if r.status == "suggested"]

    def next_due(self) -> date | None:
        dates = [t.due for t in self.open_tasks if t.due]
        return min(dates) if dates else None

    def next_actionable(self) -> "Task | None":
        """The soonest task I could actually start, or None.

        Ranking uses this rather than next_due, because a deadline on a task
        that is waiting on a sibling is a deadline on the sibling.
        """
        dated = [t for t in self.actionable_tasks if t.due]
        if dated:
            return min(dated, key=lambda t: t.due)
        return self.actionable_tasks[0] if self.actionable_tasks else None


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_project(path: Path) -> Project:
    raw = tomllib.loads(path.read_text())
    p = raw.get("project", {})

    charter = Charter(**{k: v for k, v in raw.get("charter", {}).items()
                         if k in Charter.__dataclass_fields__})

    artifacts = [Artifact(**{k: v for k, v in a.items()
                             if k in Artifact.__dataclass_fields__})
                 for a in raw.get("artifact", [])]

    tasks = []
    for t in raw.get("task", []):
        t = dict(t)
        t["due"] = _as_date(t.get("due"))
        tasks.append(Task(**{k: v for k, v in t.items()
                             if k in Task.__dataclass_fields__}))

    relations = [Relation(**{k: v for k, v in r.items()
                             if k in Relation.__dataclass_fields__})
                 for r in raw.get("relation", [])]

    return Project(
        id=p.get("id", path.stem),
        name=p.get("name", path.stem),
        kind=p.get("kind", "initiative"),
        horizon=p.get("horizon", ""),
        status=p.get("status", "active"),
        store=p.get("store", "work"),
        folder=p.get("folder", ""),
        started=_as_date(p.get("started")),
        charter=charter,
        artifacts=artifacts,
        tasks=tasks,
        relations=relations,
        uses=list(p.get("uses", [])),
        source_file=path,
    )


TOOLS_FILE = "tools.toml"


def load_tools(root: Path) -> list[Tool]:
    """Read the tool registry for a store. A missing registry is empty, not an error."""
    path = root / TOOLS_FILE
    if not path.exists():
        return []
    raw = tomllib.loads(path.read_text())
    out = []
    for t in raw.get("tool", []):
        out.append(Tool(**{k: v for k, v in t.items()
                           if k in Tool.__dataclass_fields__}))
    return out


def tool_usage(tools: list[Tool], projects: list[Project]) -> dict[str, list[str]]:
    """Which projects use each tool, and which tools nobody declared.

    The unused list is the point. A tool with no declared user is either
    genuinely dead, or it is load-bearing and undeclared, and both of those are
    worth knowing before someone deletes it.
    """
    usage: dict[str, list[str]] = {t.id: [] for t in tools}
    for p in projects:
        for tid in p.uses:
            usage.setdefault(tid, []).append(p.id)
    return usage


class Board:
    """All projects from one or more stores.

    Callers name the stores they want. A work view that never asks for the
    personal store cannot accidentally receive it, and asking for an unknown
    store is an error rather than an empty result.
    """

    def __init__(self, roots: dict[str, Path]):
        self.roots = {k: Path(v).expanduser() for k, v in roots.items()}
        for name in self.roots:
            if name not in STORES:
                raise StoreError(f"unknown store: {name}")

    @classmethod
    def from_env(cls) -> "Board":
        roots = {}
        work = os.environ.get("HIVEFRAME_WORK")
        personal = os.environ.get("HIVEFRAME_PERSONAL")
        if work:
            roots["work"] = Path(work)
        if personal:
            roots["personal"] = Path(personal)
        if not roots:
            roots["work"] = Path(__file__).resolve().parents[1] / "example" / "projects"
        return cls(roots)

    def root_for(self, store: str) -> Path:
        """The directory backing a store. Same gate as load(), for writers."""
        if store not in STORES:
            raise StoreError(f"unknown store: {store}")
        root = self.roots.get(store)
        if root is None:
            raise StoreError(f"store {store} is not configured")
        return root

    def load(self, stores: tuple[str, ...] = ("work",)) -> list[Project]:
        for s in stores:
            if s not in STORES:
                raise StoreError(f"unknown store: {s}")
        out: list[Project] = []
        for name in stores:
            root = self.roots.get(name)
            if not root or not root.exists():
                continue
            for f in sorted(root.glob("*.toml")):
                if f.name == TOOLS_FILE:
                    continue          # the registry is not a project
                proj = load_project(f)
                # The file's own store field cannot promote it into a store the
                # caller did not ask for. The directory it lives in decides.
                proj.store = name
                out.append(proj)
        return out

    def tools(self, stores: tuple[str, ...] = ("work",)) -> list[Tool]:
        for s in stores:
            if s not in STORES:
                raise StoreError(f"unknown store: {s}")
        out: list[Tool] = []
        for name in stores:
            root = self.roots.get(name)
            if root and root.exists():
                out.extend(load_tools(root))
        return out


def capacity(projects: list[Project], weekly_hours: float,
             horizon_days: int = 28, today: date | None = None) -> dict:
    """Fixed weekly budget against committed effort.

    Fixed rather than calendar-derived on purpose: cruder, and it always works.
    Move to calendar-derived only if the fixed number proves too blunt.

    Estimates are wrong at first. Logged focus sessions produce actual hours,
    so the correction is measured later rather than guessed now.
    """
    today = today or date.today()
    end = today + timedelta(days=horizon_days)
    available = weekly_hours * (horizon_days / 7.0)

    committed = 0.0
    undated = 0.0
    at_risk: list[dict] = []

    for p in projects:
        if p.status not in LIVE_STATUSES:
            continue
        for t in p.open_tasks:
            if t.due is None:
                undated += t.effort_h
                continue
            if t.due > end:
                continue
            committed += t.effort_h
            days = max((t.due - today).days, 0)
            hours_before_due = weekly_hours * (days / 7.0)
            if t.effort_h > hours_before_due:
                at_risk.append({
                    "project": p.id,
                    "project_name": p.name,
                    "task": t.id,
                    "title": t.title,
                    "due": t.due.isoformat(),
                    "days_left": days,
                    "effort_h": t.effort_h,
                    "hours_available": round(hours_before_due, 1),
                })

    return {
        "window_days": horizon_days,
        "weekly_hours": weekly_hours,
        "available_h": round(available, 1),
        "committed_h": round(committed, 1),
        "undated_h": round(undated, 1),
        "overcommitted_by_h": round(max(committed - available, 0), 1),
        "overcommitted": committed > available,
        "at_risk": sorted(at_risk, key=lambda r: r["days_left"]),
    }


def score(project: Project, today: date | None = None) -> tuple[float, list[str]]:
    """Rank a project, and say why.

    The reasons are returned with the number because a priority with no visible
    reason is an instruction, and a priority with a reason is an argument that
    can be rejected.
    """
    today = today or date.today()
    pts = 0.0
    why: list[str] = []

    if project.status not in LIVE_STATUSES:
        return 0.0, [f"not live ({project.status})"]

    if project.status == "blocked":
        why.append("blocked externally")

    nxt = project.next_actionable()
    due = nxt.due if nxt else None
    if due is not None:
        days = (due - today).days
        if days < 0:
            pts += 40 + min(abs(days), 10)
            why.append(f"overdue by {abs(days)}d")
        elif days <= 7:
            pts += 30 - days
            why.append(f"due in {days}d")
        elif days <= 28:
            pts += 8
            why.append(f"due in {days}d")

    # Size is a tiebreaker, not a priority. Between two things due the same day,
    # the one that fits in a sitting is the one that gets finished, and an
    # unfinished start on the other leaves the board exactly where it was.
    if nxt is not None and due is not None and (due - today).days <= 2:
        if nxt.effort_h and nxt.effort_h <= 0.5:
            pts += 6
            why.append(f"next move is {nxt.effort_h}h")
        elif nxt.effort_h >= 4:
            pts -= 4
            why.append(f"next move is {nxt.effort_h}h, will not fit today")

    # Flags are counted on the tasks that can actually be started today. An
    # urgent task waiting on an open sibling is not urgent to me, it is urgent
    # to the thing in front of it, and counting it twice is how six projects end
    # up tied. Additional flagged tasks add less than the first: a project with
    # five urgent tasks is worse than one with a single urgent task, but it is
    # not five times more worth starting.
    urgent = [t for t in project.actionable_tasks if t.urgent]
    important = [t for t in project.actionable_tasks if t.important]
    if urgent:
        pts += 20 + 6 * (len(urgent) - 1)
        why.append(f"{len(urgent)} urgent and startable")
    if important:
        pts += 10 + 3 * (len(important) - 1)
        why.append(f"{len(important)} important and startable")

    # An item other work waits on outranks an item nothing waits on.
    blocks = [r for r in project.confirmed_relations if r.type == "blocks"]
    if blocks:
        pts += 15 * len(blocks)
        why.append(f"blocks {len(blocks)} other project(s)")

    if project.pending_relations:
        pts += 3
        why.append(f"{len(project.pending_relations)} relation(s) awaiting a verdict")

    if not project.charter.complete:
        pts += 5
        why.append("charter incomplete")

    # A block is a reason to act, not a reason to wait. If there is a move that
    # attacks it, promote it: unblocking work releases everything downstream and
    # gets cheaper the earlier it is done.
    if project.status == "blocked" and project.actionable_tasks:
        pts += 25
        why.append(f"{len(project.actionable_tasks)} move(s) available to unblock it")

    # Stalled is the honest state for any live project with open work and no
    # move available, blocked or not. Demote only enough to break a tie: it is
    # still on the board, and it still needs someone to find it a move.
    if project.stalled:
        pts -= 5
        why.append("no move available today")

    if not project.open_tasks:
        pts -= 10
        why.append("no open tasks")

    return pts, why
