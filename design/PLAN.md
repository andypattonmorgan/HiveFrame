# Adoption plan: the HiveFrame UI redesign

Status: proposal, not started. Written 2026-08-31 against `design/README.md`,
`design/COPILOT.md` and the current `hiveframe/` source.

The handoff is good and specific. This plan does not restate it. It records
what the design assumes that the code does not yet do, the three decisions that
have to be made before any screen is built, and an order of work that keeps a
working tool on the desk the whole way through.

## 1. What already lines up

More than the handoff claims. These need porting, not designing.

| Design needs | Already in the repo |
|---|---|
| Charter fields per tier | `model.py` has `problem`, `hypothesis`, `goal`, `kill_when`, `done_when`, `stop_when`, and already varies required fields by tier. Exact match. |
| Rank reasons shown with the rank | `score()` returns `(points, reasons)` and the docstring gives the same argument the design does. Same idea, independently arrived at. |
| Three carry exits with a written reason | `carry.py` has `OUTCOMES = ("task", "project", "drop")` and `resolve(item_id, outcome, note)`. Wire it, do not rebuild it. |
| Files view semantics | `edit.py` already distinguishes a single-line rewrite that refuses itself from a structural regeneration that writes `.bak`. |
| Chat provenance, one thread per project | `chat.py` does per-project sessions, step lists, denied tools, and per-turn credit measurement. |
| Board, tree, verdict, log, capture | Endpoints exist: `/api/board`, `/api/tree`, `/api/verdict`, `/api/log`, `/api/carry`, `/api/file`, `/api/edit`, `/api/chat/*`. |

Roughly four of the six screens are backed by working code today. Today, Files
and Chat are mostly a re-skin plus wiring. Board is half. Goals and Focus are new.

## 2. What does not line up

Five gaps. The first is the one that decides the size of this job.

### 2.1 The design ranks tasks; the model ranks projects

`model.score()` takes a `Project`. It returns 0 for operations ("not in this
contest") and reads the due date off `next_actionable()`, the project's first
workable task. The design's `rankTask()` takes a task, and its table includes
terms the project scorer has no equivalent for: parent status blocked `+25`,
parent tier operation `-8`, KR weight `+min(w/4, 12)`, and the two effort-shape
terms at `+6` and `-4`.

These are not the same function at two altitudes. They answer different
questions. The project scorer answers "which project deserves attention", and
the board is built on it. The task scorer answers "what do I do in the next 25
minutes", and Focus, Today's first move, and the drawer's rank reasons all need
it.

**Both are wanted.** The decision is not which to keep, it is where the new one
lives and whether the old one is re-expressed in terms of it. Cheapest honest
option: add `score_task()` beside `score()`, leave the project scorer alone, and
accept that two ranking functions exist with different jobs. Say so in the
docstrings so the next reader does not try to unify them.

### 2.2 There is no `phase`, and no `task` tier

`TIERS = ("program", "project", "operation")`. The design's items also have tier
`task`, and every item carries one of seven ordered phases distinct from status.

The design is right that phase and status are different axes and should not be
collapsed. The seven phases are also a real opinion about how work moves, and
adopting them changes what the board means. This is a model change, not a UI
change, and it should be made deliberately.

Note the interaction the handoff flags: advancing to `done` sets status `done`,
and moving back off it reopens the item. That is one rule in two places, so it
belongs in the model, not in the drawer's click handler.

### 2.3 Status vocabularies disagree

| Where | Values |
|---|---|
| `Task.status` | `open`, `doing`, `validate`, `done`, `dropped` |
| Project `LIVE_STATUSES` | `active`, `blocked` |
| Design item status | `open`, `active`, `doing`, `blocked`, `done`, `dropped` |

The design unions them into one vocabulary across tiers. The model deliberately
keeps two, and `validate` exists in the model and nowhere in the design. Decide
whether tasks and projects share a status vocabulary before writing the store,
because it is a data migration afterwards.

### 2.4 There is no goals or key-result store

The handoff names this. It drives the Goals view, the KR pills, one rank term,
and Today's "where the plan is thin". Nothing in `hiveframe/` has a counterpart.

The `krState` arithmetic is the most interesting thing in the design: separating
what actually moved (`realized`) from whether anything on the board is even
trying (`planDone`/`planOpen`/`planGap`), and calling out declared weight over
100% as two tasks claiming the same ground. That is worth building carefully and
worth unit-testing first.

### 2.5 The stack

This is the largest hidden cost and the handoff does not price it.

| | Now | Prototype |
|---|---|---|
| Rendering | Vanilla JS, `document.createElement`, template strings | React 18 + Babel standalone |
| Files | One 5,446-line `index.html` | 8 `.jsx` files plus a vendored design system |
| Build step | None | None in the prototype (in-browser Babel), but a real one for production |
| Network at runtime | **Zero external references** | React, ReactDOM and Babel from `unpkg.com` |

Two things follow. In-browser Babel is a prototype technique and is not shippable,
so "React" means adopting Node, npm and a bundler. And the current app has no
external references at all, which is a property worth keeping on a KP-managed
machine where `unpkg.com` may well be blocked and a `node_modules` tree is its
own supply-chain conversation.

The design does not actually require React. What it requires is the token sheet,
the class names, the arithmetic and the copy. Those are framework-free.

## 3. Three decisions before any screen is built

Nothing below step 1 should start until these are answered, because each one
changes the shape of the store.

1. **Framework.** React plus a build step, or the existing vanilla renderer
   split into modules. Recommendation below.
2. **Phases and KR weights: model or side store.** If they go in `model.py` they
   are in the TOML and versioned with the project. If they go in a side store
   they are easier to revert and harder to trust. The handoff says decide this
   at step 1 and it is right.
3. **One status vocabulary or two.** See 2.3.

### Recommendation on the framework

Port the design onto the existing vanilla renderer, in modules, and keep the
zero-dependency property.

The argument is not that React is worse. It is that the value in this handoff is
the design system, the arithmetic and the copy, none of which is React-specific,
and the cost of a build step here is not just the setup: it is a toolchain on a
managed workstation, a `node_modules` tree to keep current, and a second way to
run the app that has to stay working. The current app already renders a board, a
drawer, a chat transcript with streaming, and a file editor without any of it.

Two things this costs, stated plainly. `index.html` is already 5,446 lines and
six views will make it worse, so it has to be split into modules regardless.
And the prototype's `.jsx` will need translating by hand rather than copying,
which is slower per screen and is where the copy and the reason strings get
dropped if nobody is watching.

If the answer is React, decide it now and at step 1. Deciding it after Goals is
built means building Goals twice.

## 4. Order of work

The handoff's order is sound. This changes it in two places: the arithmetic
moves ahead of the CSS, because three screens depend on it and none depend on
the CSS; and each phase ends with something usable, so the tool on the desk is
never broken for a week.

| Step | Work | Ends with |
|---|---|---|
| 0 | Answer the three decisions. Write them into `design/DECISIONS.md`. | A settled shape |
| 1 | Model: phases, task tier, KR weights, goals store. Migrate the 16 existing projects. Extend `--selftest`. | `--selftest` green on real data |
| 2 | Arithmetic: `score_task()` and `kr_state()` in Python, with the reason strings verbatim. Unit tests per the handoff: each rank term, and `krState` for normal, `lowerIsBetter`, no contributors, and declared weight over 100. | Tested functions, no UI |
| 3 | API: `/api/goals`, `/api/phase`, `/api/sessions`, extend `/api/board` with phase and KR rollups. | Endpoints returning real JSON |
| 4 | Design system: vendor `styles.css` untouched, port the app `<style>` block, verify all three grounds switch. | The old UI in the new skin |
| 5 | Shell and nav, then Board and drawer. | Board usable, old views still reachable |
| 6 | Goals. | The plan-gap view, the new capability |
| 7 | Focus, including the timer and session logging. | Blocks logged against tasks |
| 8 | Today, wired to `carry.py`. | Morning routine on the new surface |
| 9 | Files and Chat, ported to the new skin over the existing endpoints. | Old UI retired |

Step 2 is the one to get exactly right. It is also the only step whose output can
be verified without looking at a screen, which is why it comes before the CSS.

## 5. Things this design is right about, worth not losing under time pressure

Recorded because these are the first things dropped when a screen is running late,
and each one is the reason a screen exists.

- **A rank without visible reasons is an instruction, not an argument.** The
  model already says this. The UI must not quietly show a number alone.
- **Empty states stay visible.** Unwritten charter fields read "not written down
  yet". Unclaimed plan share is shown. Missing files say "declared, but not
  there". A UI that hides what is absent is how a board stops being true.
- **Nothing leaves without a written exit.** The three carry exits, each needing
  a reason, each kept on the record.
- **Phase is not status, and seven is not three.** Collapsing to todo/doing/done
  throws away the whole point.
- **`realized` and `planGap` are different numbers.** One is what moved, the
  other is whether anything is even trying. Conflating them produces a
  reassuring chart that means nothing.

## 6. Open questions for the designer

1. `validate` exists as a task status in the model and nowhere in the design. Was
   it dropped deliberately, or not seen?
2. Focus sessions: memory only in the prototype. Should a completed block persist
   to the backend, and if so, against the task or a separate session log?
3. The project scorer and the task scorer differ by more than altitude (2.1).
   Is the project ranking meant to be rebuilt on top of task scores, or to stay
   as it is?
4. The prototype targets 1280px and wider with no breakpoints. Is that the real
   target, or untreated scope?

## 7. Sizing

No estimate is offered yet, because step 0 changes it by more than an estimate's
worth. What can be said: steps 1 to 3 are backend work that can be tested without
a UI, steps 4 to 9 are six screens of which two are new capability and four are
substantially backed by working endpoints today.
