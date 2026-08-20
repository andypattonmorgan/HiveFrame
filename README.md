# HiveFrame

A private working surface for running many threads at once without them bleeding
into each other. HiveLab publishes findings outward. HiveFrame is where the work
is held.

Named for the beekeeping frame: the panel you lift out to inspect one section
without disturbing the rest of the hive.

## Scope and posture

**What it does.** Holds projects and experiments as plain files, each with its own
charter, tasks, artifacts and declared relationships. Brings one project into
focus so its context is on screen while you work on it. Ranks what to do next and
says why. Runs a focus timer bound to a real task. Records triage verdicts so the
board can lose entries.

**What it must never do.** Write to any system of record. HiveFrame reads local
files and calls existing read-only connectors. It has no write path into Jira,
ServiceNow, Concerto or the warehouse, and it adds no new access.

**What it writes.** Local files only, inside a store the caller named: project
`.toml` files, an append-only `decisions.jsonl`, and an append-only
`inbox.jsonl`. Everything else is a GET.

Two write paths, on purpose. A triage verdict rewrites exactly one `status` line
and refuses if it cannot find exactly one, so nothing else in the file can move.
A structural edit (charter, task, artifact, relation) regenerates the file from
the model, because a regex that edits structure is a regex that will eventually
corrupt a file. The cost is that hand-written TOML comments are lost on a
structural edit, so keep notes in a task `note` or a charter field where they are
data rather than decoration. Every regeneration leaves a `.bak`.

A verdict without a reason is rejected, and so is dropping a task without one. A
kill with no reason written down returns in six weeks as a new idea.

**Whose identity.** Runs as the operator, locally, bound to 127.0.0.1. No auth
because there is no network exposure.

## The problem it exists for

Not a dashboard. The problem is context bleed: when a dozen threads are held in
one conversation and one head, work on one drifts into another and the direction
changes before anyone notices.

Three consequences it addresses directly:

- **Context is implicit.** Relationships between projects exist only as inference.
  An inferred link that is usually right is the dangerous case, because a wrong
  one looks identical to a right one. HiveFrame makes relationships declared
  objects with a status, and a suggested relation affects nothing until confirmed.
- **The goal goes out of sight.** The charter (problem, hypothesis, goal, kill
  when, done when) stays on screen in the project view. Not collapsed, not on a
  second tab.
- **Capacity is unmeasured.** A fixed weekly budget against dated, estimated
  tasks, so overcommitment is visible before a date is missed rather than after.

## Files

| Path | Purpose |
|---|---|
| `hiveframe/model.py` | Data model, loader, store boundary, capacity, scoring |
| `hiveframe/edit.py` | Structural edits and the rules they must satisfy |
| `hiveframe/writer.py` | Renders a project back to TOML, keeps a `.bak` |
| `hiveframe/verdict.py` | Triage verdicts, decision log, interruption inbox |
| `hiveframe/server.py` | Local HTTP service and self test |
| `hiveframe/web/index.html` | The interface: project rail, project view, brief, triage, capacity, focus timer |
| `example/projects/*.toml` | Example projects with invented data, so the shape is obvious |
| `example/projects/tools.toml` | Example tool registry, showing the reference-not-copy shape |

**The file format is the contract.** One TOML per project: diffable, greppable,
editable by hand, readable without this application. If the UI is replaced,
nothing is lost.

## Usage

```
# self test first, always
python3 -m hiveframe.server --selftest

# run it
python3 -m hiveframe.server --port 8787
# then open http://127.0.0.1:8787
```

Point it at real data with environment variables. Neither store is in this repo.

```
export HIVEFRAME_WORK=~/Library/CloudStorage/OneDrive-.../hiveframe/projects
export HIVEFRAME_PERSONAL=~/Library/CloudStorage/GoogleDrive-.../hiveframe/projects
export HIVEFRAME_WEEKLY_HOURS=10
```

## Work and personal separation

Two stores, separate roots. The boundary is enforced in the loader, not in the
UI, because a boundary enforced at the display layer leaks the first time someone
adds a view.

- A caller names the stores it wants. A work view that never asks for the personal
  store cannot receive it.
- An unknown store is an error, not an empty result.
- A project file cannot promote itself into a store the caller did not ask for.
  The directory it sits in decides.

The self test asserts both properties and fails if either stops holding.

## Scoring

Ranking is computed and the reasons are shown next to the number. A priority with
no visible reason is an instruction; a priority with a reason is an argument that
can be rejected.

Rank rises with: overdue or near-due tasks, manual urgent and important flags,
blocking other projects, relations awaiting a verdict, an incomplete charter.
Rank falls when a project has no open tasks.

A project status of `blocked` does not lower rank. Blocked means the work cannot
proceed right now, not that it stops mattering, and there is nearly always a move
that attacks the block. A blocked project with at least one available move gains
25 points, because unblocking releases everything downstream and gets cheaper the
earlier it happens. Only a project with open work and no available move loses
anything, and then just 5 points, enough to break a tie and no more.

Live statuses are `active` and `blocked`. Everything else (`paused`, `done`,
`killed`) scores zero and is excluded from capacity.

A task lists prerequisites in `blocked_by`. A task waiting on an open sibling is
never offered as a focus candidate, since a candidate you cannot start costs a
decision and returns nothing.

Ranking reads the tasks that can be started today, not every open task. Urgent
and important flags are counted on those, and additional flagged tasks add less
than the first: five urgent tasks is worse than one, but not five times more
worth starting. The deadline that counts is the deadline on the next startable
task, because a deadline on a task waiting for a sibling is a deadline on the
sibling.

Size breaks ties, it does not set priority. Between two things due the same day,
a move of half an hour or less gains 6 and a move of four hours or more loses 4,
because the short one gets finished and an unfinished start on the long one
leaves the board where it was.

## Capacity

A fixed weekly hour budget against the sum of dated, estimated open tasks over a
28 day window. Fixed rather than calendar-derived on purpose: cruder, and it
always works.

Estimates are wrong at first. That is expected. Logged focus sessions produce
actual hours against tasks, so the correction is measured rather than guessed.

Undated effort is reported separately, because work with no date is invisible to
any projection and pretending otherwise makes the number worse than useless.

## Triage

The view that removes things. Live projects are listed worst first, because the
top of a board looks after itself and the bottom is where the cost hides.

Every row offers four verdicts and none of them is "leave it": kill, park, done,
keep. Each needs a one-line reason. The verdict rewrites the project's status and
appends to `decisions.jsonl` next to the project files, so the board keeps its
own history of what it stopped doing and why.

A project with no `kill_when` in its charter is called out here. Without one,
nothing on the board can ever fail, and a board that cannot lose an entry only
grows.

## Editing

The charter, tasks, artifacts and relations are editable from the project view.
The charter is editable in place rather than behind a form, because it is the
thing that stops drift and making it hard to correct guarantees it goes stale
and stops being believed.

Four rules are enforced rather than suggested:

- A task id is generated once from its title and never rewritten. `blocked_by`
  refers to ids, so a renamed id would silently break a dependency chain.
- A dependency that closes a loop is refused. Every task in a cycle is
  permanently unstartable, and the board would show a stalled project with no
  explanation.
- Tasks are dropped with a reason, never deleted. A deleted task takes its
  estimate with it and the capacity number quietly improves for no reason
  anyone can point at.
- A rejected relation stays on the record. Deleting it means the same suggestion
  arrives next month looking new.

A relation added by hand arrives confirmed. `suggested` is reserved for
relations a machine proposed, which is a claim that still needs a verdict.

## Tools

Tools are shared capabilities, declared once in `tools.toml` beside the project
files. A project references a tool by id in its `uses` list and never copies the
description, because a connector is not owned by whatever needed it first and
three copies of a description disagree within a month.

Each entry says what the tool does in one line, where it runs, its access mode
and its status. A tool nobody can describe in one line is a tool nobody can hand
over, so the registry view counts those separately.

The registry is sorted by dependant count ascending, so tools nothing depends on
are the first thing you see. That list is where unkilled work hides: it never
appeared on a project board because it was never a project.

Two states are worth separating. A tool **used by nothing** is either dead or
load-bearing and undeclared. A tool **declared but not registered** is a project
depending on something nothing describes, which is worse.

Retiring is refused while any project still declares the tool, and needs a
reason. Retiring something another project depends on is how a board loses a
capability it did not know it was using.

Shared libraries will always show as used by nothing. That is correct, not a
finding, and the registry says so in the note.

## Security

No secrets in this repo, in config, or in the page. Credentials for connectors
are resolved from the macOS Keychain at run time by the existing tools, which
HiveFrame calls rather than reimplements.

This repo contains no real project content. The example projects use invented
data. Sanitised data is not used, because sanitised data leaks.

## Status

Phase 4. Project model, project view with in-place editing, brief, triage with
verdicts, tool registry with a reverse dependency index, capacity, configurable
focus timer, interruption capture.

Not yet built: connector-fed brief, the relation graph, project-bound chat,
session logging and effort calibration, and sub-project rows so individual
hypotheses can be triaged rather than only whole projects.
