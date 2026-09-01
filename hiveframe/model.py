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

# Altitude. Three tiers, because the whole board is one portfolio and a fourth
# tier for a set of one is filing for its own sake.
#
#   program    a theme that holds work. It does not finish, it stops being worth
#              running. Next-Gen Delivery Lab is the case: it generates
#              hypotheses, some of which are promoted to projects, and asking
#              when it is "done" is the wrong question.
#   project    has an end state. A hypothesis is a small project: it resolves.
#   operation  never ends, and that is correct rather than a defect. Admin is
#              not a low-priority project, it is the tax paid before any project
#              is chosen. See capacity() for the consequence.
TIERS = ("program", "project", "operation")

# Which tier may contain which. A project sits under a program or stands alone.
# An operation is never contained: it belongs to no theme, it is overhead on all
# of them.
TIER_PARENT = {
    "program": (),
    "project": ("program",),
    "operation": (),
}

# What a thing IS, now that tier carries how high it sits. Previously "kind"
# tried to answer both and answered neither: "initiative" is an altitude,
# "tool" is a nature, and sorting a list containing both is meaningless.
KINDS = ("experiment", "tool", "deliverable", "analysis", "service", "admin",
         "platform", "initiative")


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
    status: str = "open"          # open | doing | validate | done | dropped
    due: date | None = None
    effort_h: float = 0.0
    urgent: bool = False
    important: bool = False
    blocked_by: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def open(self) -> bool:
        return self.status in ("open", "doing", "validate")

    @property
    def workable(self) -> bool:
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

    A program gets its own charter rather than inheriting one. It answers a
    different question from a project's, and the field that differs is the
    ending: a project has done_when, a program has stop_when. Next-Gen Delivery
    Lab has no completion state and should not be given a fake one, but it can
    absolutely stop being worth running, and writing down what that looks like
    is what stops a program becoming permanent by default.
    """
    problem: str = ""
    hypothesis: str = ""
    goal: str = ""
    kill_when: str = ""
    done_when: str = ""
    stop_when: str = ""           # programs: what makes this no longer worth running
    constraints: list[str] = field(default_factory=list)

    def complete_for(self, tier: str = "project") -> bool:
        """A program is not incomplete for lacking done_when.

        Judging every tier against the project's fields is how a program either
        gets a fabricated end date or sits permanently flagged as unfinished.
        """
        if tier == "program":
            return bool(self.problem and self.goal and self.stop_when)
        if tier == "operation":
            return bool(self.problem and self.goal)
        return bool(self.problem and self.goal and self.done_when)

    def missing_for(self, tier: str = "project") -> list[str]:
        if tier == "program":
            wanted = ("problem", "goal", "stop_when")
        elif tier == "operation":
            wanted = ("problem", "goal")
        else:
            wanted = ("problem", "hypothesis", "goal", "kill_when", "done_when")
        return [n for n in wanted if not getattr(self, n)]

    @property
    def complete(self) -> bool:
        return self.complete_for("project")

    @property
    def missing(self) -> list[str]:
        return self.missing_for("project")


@dataclass
class Project:
    id: str
    name: str
    tier: str = "project"         # program | project | operation
    parent: str = ""              # exactly one, or empty. See below.
    kind: str = "initiative"      # what it is: experiment | tool | deliverable | ...
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

    # Containment is a field, not a relation, and the distinction is load
    # bearing. A relation is a claim: it can be suggested, confirmed or
    # rejected, and there can be many of them. Containment is structural. One
    # parent, no cycles, and the parent must sit higher. As a relation you get
    # two parents and a loop, and any rollup computed over it is meaningless.

    @property
    def is_operation(self) -> bool:
        return self.tier == "operation"

    @property
    def charter_complete(self) -> bool:
        return self.charter.complete_for(self.tier)

    @property
    def charter_missing(self) -> list[str]:
        return self.charter.missing_for(self.tier)

    @property
    def folder_roots(self) -> list[tuple[str, str, str]]:
        """The directories this project can browse, as (label, path, mode).

        Mode is ``home`` for the one declared ``folder``, and ``linked`` for a
        directory artifact. A linked folder is a pointer: it is browsable and
        read-only, and nothing is ever written or copied into it. The home is
        the only place this project writes.

        A project is worked in places it has explicitly named, and the file view
        shows those places rather than the whole store: a tree that lists
        everything is the same context bleed the charter exists to stop.

        Nested paths are dropped in favour of the outermost one, so a folder is
        not drawn twice.
        """
        out: list[tuple[str, str, str]] = []
        if self.folder:
            out.append(("Project home", self.folder, "home"))
        for a in self.artifacts:
            if not a.path:
                continue
            try:
                if Path(a.path).expanduser().is_dir():
                    out.append((a.label or "Linked folder", a.path, "linked"))
            except OSError:
                continue

        kept: list[tuple[str, str, str]] = []
        seen: list[Path] = []
        for label, raw, mode in out:
            p = Path(raw).expanduser()
            try:
                resolved = p.resolve()
            except OSError:
                continue
            if any(resolved == s or s in resolved.parents for s in seen):
                continue
            seen.append(resolved)
            kept.append((label, str(p), mode))
        return kept

    @property
    def folders(self) -> list[tuple[str, str]]:
        """The browsable directories as (label, path). See ``folder_roots``."""
        return [(label, path) for label, path, _ in self.folder_roots]

    @property
    def home_folder(self) -> str | None:
        """The single directory this project writes into, if one is declared."""
        for _, path, mode in self.folder_roots:
            if mode == "home":
                return path
        return None

    @property
    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.open]

    @property
    def workable_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.workable]

    @property
    def open_effort_h(self) -> float:
        return sum(t.effort_h for t in self.open_tasks)

    @property
    def actionable_tasks(self) -> list[Task]:
        """Open tasks whose prerequisites are already done.

        These are the moves available right now. A project can be blocked and
        still have several of them, which is the whole point of the distinction.
        """
        open_ids = {t.id for t in self.workable_tasks}
        return [t for t in self.workable_tasks
                if not any(dep in open_ids for dep in t.blocked_by)]

    @property
    def stalled(self) -> bool:
        """Live, has open work, and no move available. Nothing I can do today."""
        return bool(self.workable_tasks) and not self.actionable_tasks

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
        files = t.get("files") or []
        if isinstance(files, str):
            files = [files]
        t["files"] = [str(p) for p in files if str(p).strip()]
        tasks.append(Task(**{k: v for k, v in t.items()
                             if k in Task.__dataclass_fields__}))

    relations = [Relation(**{k: v for k, v in r.items()
                             if k in Relation.__dataclass_fields__})
                 for r in raw.get("relation", [])]

    return Project(
        id=p.get("id", path.stem),
        name=p.get("name", path.stem),
        tier=p.get("tier", "project"),
        parent=p.get("parent", ""),
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

    A configured store whose directory does not exist is also an error. It was
    once skipped silently, which meant a mistyped path and an empty board were
    indistinguishable: the server answered 200 with zero projects and the
    portfolio appeared to have been lost. Absent is not empty.
    """

    def __init__(self, roots: dict[str, Path]):
        self.roots = {k: Path(v).expanduser() for k, v in roots.items()}
        for name in self.roots:
            if name not in STORES:
                raise StoreError(f"unknown store: {name}")

    def check(self) -> list[str]:
        """Configured roots that are not usable directories, as readable lines.

        Returned rather than raised so a caller can report every problem at
        once, at startup, instead of discovering them one request at a time.
        """
        bad = []
        for name, root in sorted(self.roots.items()):
            if not root.exists():
                bad.append(f"store {name}: directory does not exist: {root}")
            elif not root.is_dir():
                bad.append(f"store {name}: not a directory: {root}")
        return bad

    def _root_checked(self, store: str) -> Path:
        """The root for a store, or a StoreError naming exactly what is wrong.

        One gate for readers and writers both, so they cannot disagree about
        whether a store is usable.
        """
        if store not in STORES:
            raise StoreError(f"unknown store: {store}")
        root = self.roots.get(store)
        if root is None:
            raise StoreError(f"store {store} is not configured")
        if not root.exists():
            raise StoreError(
                f"store {store} is configured but its directory does not exist: "
                f"{root}. Set HIVEFRAME_{store.upper()} to the right path."
            )
        if not root.is_dir():
            raise StoreError(f"store {store} is not a directory: {root}")
        return root

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
        return self._root_checked(store)

    def load(self, stores: tuple[str, ...] = ("work",)) -> list[Project]:
        out: list[Project] = []
        for name in stores:
            if name not in STORES:
                raise StoreError(f"unknown store: {name}")
            # Not configured is a legitimate skip: a work-only setup should not
            # have to pretend a personal store exists. Configured but missing is
            # not, and _root_checked says which of the two it is.
            if name not in self.roots:
                continue
            root = self._root_checked(name)
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
        out: list[Tool] = []
        for name in stores:
            if name not in STORES:
                raise StoreError(f"unknown store: {name}")
            if name not in self.roots:
                continue
            out.extend(load_tools(self._root_checked(name)))
        return out


def hierarchy(projects: list[Project]) -> dict:
    """Resolve containment, and report where it is broken rather than guessing.

    Three failures are worth naming out loud, because each one hides work:
    a parent that does not exist (the child is orphaned and invisible under any
    program), a parent at the wrong altitude (a project owning a project is how
    a program gets created by accident), and a cycle (which makes rollup
    nonsense). None of these are repaired silently. A structure quietly fixed is
    a structure nobody learns from.
    """
    by_id = {p.id: p for p in projects}
    problems: list[dict] = []
    children: dict[str, list[str]] = {p.id: [] for p in projects}
    roots: list[str] = []

    for p in projects:
        if p.tier not in TIERS:
            problems.append({"project": p.id, "issue": f"unknown tier {p.tier!r}"})
        if not p.parent:
            roots.append(p.id)
            continue
        parent = by_id.get(p.parent)
        if parent is None:
            problems.append({"project": p.id,
                             "issue": f"parent {p.parent!r} does not exist"})
            roots.append(p.id)
            continue
        allowed = TIER_PARENT.get(p.tier, ())
        if parent.tier not in allowed:
            problems.append({
                "project": p.id,
                "issue": f"a {p.tier} cannot sit under a {parent.tier}",
            })
        children.setdefault(parent.id, []).append(p.id)

    # Cycles. Walk up from each node with a step budget; anything still walking
    # after len(projects) hops is in a loop.
    for p in projects:
        seen, cur, n = {p.id}, p.parent, 0
        while cur and n <= len(projects):
            if cur in seen:
                problems.append({"project": p.id, "issue": f"parent cycle through {cur}"})
                break
            seen.add(cur)
            nxt = by_id.get(cur)
            cur = nxt.parent if nxt else ""
            n += 1

    return {"roots": sorted(roots), "children": children, "problems": problems}


def rollup(project: Project, projects: list[Project]) -> dict:
    """A program's real state is its children's, not its own task list.

    A program with no open tasks of its own is not idle if three projects
    beneath it are moving. Reading the container instead of the contents is how
    a healthy program looks dead and a stalled one looks fine.
    """
    h = hierarchy(projects)
    by_id = {p.id: p for p in projects}
    kids = [by_id[c] for c in h["children"].get(project.id, []) if c in by_id]

    live = [k for k in kids if k.status in LIVE_STATUSES]
    return {
        "children": len(kids),
        "live": len(live),
        "blocked": len([k for k in kids if k.status == "blocked"]),
        "stalled": len([k for k in live if k.stalled]),
        "killed": len([k for k in kids if k.status == "killed"]),
        "open_effort_h": round(sum(k.open_effort_h for k in live)
                               + project.open_effort_h, 1),
        "child_ids": [k.id for k in kids],
    }


def capacity(projects: list[Project], weekly_hours: float,
             horizon_days: int = 28, today: date | None = None) -> dict:
    """Fixed weekly budget against committed effort.

    Fixed rather than calendar-derived on purpose: cruder, and it always works.
    Move to calendar-derived only if the fixed number proves too blunt.

    Operations are subtracted before projects are measured, not ranked beside
    them. You never actually choose between "do admin" and "do the platform
    work": admin is the tax paid before any choice is available. Counting it as
    a competitor inflates the apparent budget and then quietly eats it, which is
    how a plan that looked affordable stops being one. What is left after the
    tax is the only number that can honestly answer "can I take this on".

    Estimates are wrong at first. Logged focus sessions produce actual hours,
    so the correction is measured later rather than guessed now.
    """
    today = today or date.today()
    end = today + timedelta(days=horizon_days)
    gross = weekly_hours * (horizon_days / 7.0)

    committed = 0.0
    undated = 0.0
    operations = 0.0
    at_risk: list[dict] = []

    for p in projects:
        if p.status not in LIVE_STATUSES:
            continue
        for t in p.open_tasks:
            if p.is_operation:
                # Overhead lands in the window whether or not it carries a date,
                # because it recurs. An undated operational task is not
                # unscheduled, it is continuous.
                operations += t.effort_h
                continue
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

    available = gross - operations

    return {
        "window_days": horizon_days,
        "weekly_hours": weekly_hours,
        "gross_h": round(gross, 1),
        "operations_h": round(operations, 1),
        "available_h": round(available, 1),
        "committed_h": round(committed, 1),
        "undated_h": round(undated, 1),
        "overcommitted_by_h": round(max(committed - available, 0), 1),
        "overcommitted": committed > available,
        "consumed_by_operations": (round(operations / gross * 100)
                                   if gross else 0),
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

    # Operations do not compete for rank. They are removed from the budget in
    # capacity() before anything is ranked, and letting them appear in the
    # ordering would count the same hours twice: once as overhead, once as a
    # rival. It is also a choice nobody makes. You do not decide between doing
    # admin and doing the platform work, you do the admin and then decide.
    # Zero here means "not in this contest", not "unimportant".
    if project.is_operation:
        return 0.0, ["routine running work, not ranked against projects"]

    if project.status == "blocked":
        why.append("waiting on someone outside this board")

    nxt = project.next_actionable()
    due = nxt.due if nxt else None
    # Read aloud, not printed. "due in 1 days" and "due in 0 days" are the two
    # places a reader stops trusting the sentence, and "today" is the word they
    # would have used anyway.
    def when(d: int) -> str:
        if d == 0:
            return "due today"
        return f"due in {d} day" + ("" if d == 1 else "s")

    if due is not None:
        days = (due - today).days
        if days < 0:
            pts += 40 + min(abs(days), 10)
            n = abs(days)
            why.append(f"{n} day{'' if n == 1 else 's'} past its date")
        elif days <= 7:
            pts += 30 - days
            why.append(when(days))
        elif days <= 28:
            pts += 8
            why.append(when(days))

    # Size is a tiebreaker, not a priority. Between two things due the same day,
    # the one that fits in a sitting is the one that gets finished, and an
    # unfinished start on the other leaves the board exactly where it was.
    if nxt is not None and due is not None and (due - today).days <= 2:
        if nxt.effort_h and nxt.effort_h <= 0.5:
            pts += 6
            why.append(f"next step is short, {nxt.effort_h}h")
        elif nxt.effort_h >= 4:
            pts -= 4
            why.append(f"next step needs {nxt.effort_h}h, too big for today")

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
        why.append(f"{len(urgent)} urgent step(s) ready to start")
    if important:
        pts += 10 + 3 * (len(important) - 1)
        why.append(f"{len(important)} important step(s) ready to start")

    # An item other work waits on outranks an item nothing waits on.
    blocks = [r for r in project.confirmed_relations if r.type == "blocks"]
    if blocks:
        pts += 15 * len(blocks)
        why.append(f"{len(blocks)} other project(s) are waiting on this")

    if project.pending_relations:
        pts += 3
        why.append(f"{len(project.pending_relations)} suggested link(s) need a yes or no")

    if not project.charter_complete:
        pts += 5
        why.append("its purpose has not been fully written down")

    # A block is a reason to act, not a reason to wait. If there is a move that
    # attacks it, promote it: unblocking work releases everything downstream and
    # gets cheaper the earlier it is done.
    if project.status == "blocked" and project.actionable_tasks:
        pts += 25
        why.append(f"{len(project.actionable_tasks)} step(s) available to clear the blockage")

    # Stalled is the honest state for any live project with open work and no
    # move available, blocked or not. Demote only enough to break a tie: it is
    # still on the board, and it still needs someone to find it a move.
    if project.stalled:
        pts -= 5
        why.append("nothing can be started today")

    if not project.open_tasks:
        pts -= 10
        why.append("no open work left")

    return pts, why
