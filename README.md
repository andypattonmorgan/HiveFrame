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
says why. Runs a focus timer bound to a real task.

**What it must never do.** Write to any system of record. HiveFrame reads local
files and calls existing read-only connectors. It has no write path into Jira,
ServiceNow, Concerto or the warehouse, and it adds no new access.

**Read-only in this phase.** Every endpoint is a GET. Editing tasks and confirming
relations arrive in phase 2, and they write to local project files only.

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
| `hiveframe/server.py` | Local read-only HTTP service and self test |
| `hiveframe/web/index.html` | The interface: project rail, project view, brief, capacity, focus timer |
| `example/projects/*.toml` | Example projects with invented data, so the shape is obvious |

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

## Capacity

A fixed weekly hour budget against the sum of dated, estimated open tasks over a
28 day window. Fixed rather than calendar-derived on purpose: cruder, and it
always works.

Estimates are wrong at first. That is expected. Logged focus sessions produce
actual hours against tasks, so the correction is measured rather than guessed.

Undated effort is reported separately, because work with no date is invisible to
any projection and pretending otherwise makes the number worse than useless.

## Security

No secrets in this repo, in config, or in the page. Credentials for connectors
are resolved from the macOS Keychain at run time by the existing tools, which
HiveFrame calls rather than reimplements.

This repo contains no real project content. The example projects use invented
data. Sanitised data is not used, because sanitised data leaks.

## Status

Phase 1. Project model, project view, brief, capacity, focus timer.

Not yet built: writing task edits and relation verdicts, connector-fed brief,
the relation graph, project-bound chat, session logging and effort calibration.
