# Working with GitHub Copilot

A suggested order for turning `prototype/` into a real front end in `andypattonmorgan/HiveFrame`. Each step is a prompt you can paste into Copilot Chat with the named files open or attached. Read `README.md` first — it holds every value and rule these prompts refer to.

## Setup

Copy this whole folder into the repo (e.g. `design/`) so Copilot can see the prototype and the README alongside the Python source. Attach `design/README.md` to the chat for every step; it is the spec.

Repository context worth stating once in the chat:

> HiveFrame is a Python work-tracking model and CLI. I'm adding a browser front end. `design/README.md` specifies it; `design/prototype/` is a running HTML/JSX reference prototype, not production code. Recreate the design in the front-end stack we choose, reading the prototype for exact layout, copy and arithmetic.

## 1. Decide the stack and the seam

> Read `hiveframe/model.py`, `carry.py` and `verdict.py`. Propose the smallest API that would let a browser front end render the six screens in `design/README.md`: the endpoints, their JSON shapes, and which existing functions back each one. Don't write the front end yet.

Decide here whether the two new concepts in the README — weighted KR contribution and the seven phases — go into `model.py` or into a side store.

## 2. Port the design system and app CSS

> Copy `design/prototype/_ds/organic-*/styles.css` into the front end untouched, and port the `<style>` block from `design/prototype/HiveFrame.html` into an app stylesheet. Keep every class name. Every value must come from a `var(--*)` token; do not substitute hex codes or px values.

Check: the three `body[data-look]` grounds still switch correctly.

## 3. Port the model helpers with tests

> Port `design/prototype/lib.jsx` — `isOpen`, `actionable`, `days`, `dueLabel`, `hrs`, `rankTask`, `focusQueue`, `krState`. Keep the reason strings verbatim; a rank must always carry its reasons. Write unit tests for `rankTask` covering each scoring term in the README table, and for `krState` covering a normal KR, a `lowerIsBetter` KR, one with no contributors, and one whose declared weight exceeds 100.

This is the part most worth getting exactly right — three screens depend on it.

## 4. Shell, nav and grounds

> Build the app shell from `design/prototype/app.jsx`: the `.nav` bar with the wordmark, six view links, the open-task and committed-hours meta, and the three ground dots writing `document.body.dataset.look`.

## 5. Board and drawer

> Build the Board and its drawer from `design/prototype/board.jsx`. Seven phase columns from `PHASES`, the program/tasks/done filter chips, the work card with its tier tags, breadcrumb, next-task line, meta row and KR pills, and the 430px drawer with the phase stepper, the tier-dependent charter fields, the task list, the rank reasons and the "contributes to" rollup.

Watch for: unwritten charter fields must render as "not written down yet", not be hidden. Advancing to the `done` phase sets status `done`; moving back off it reopens the item.

## 6. Goals

> Build the Goals view from `design/prototype/goals.jsx`, including the three-band coverage bar (`.krbar` / `.krfill` / `.krplan` / `.krgap`) and the legend. The delivered percentage and the plan coverage are separate numbers and must not be conflated.

## 7. Focus

> Build the Focus view from `design/prototype/focus.jsx`: the 25/5 timer with the conic ring, session logging on completion and on stop, the ranked "suggested next, and why" list, the daily target pips, the session log and the estimate-against-logged table. Persist remaining time and mode to `localStorage` under `hf.focus`.

Decide whether sessions post to the backend on completion; the prototype only holds them in memory.

## 8. Today

> Build the Today view from `design/prototype/today.jsx`. The carry-forward card must keep its three exits — task, project, drop — each requiring a one-line reason, and each resolution must land in the archive with its reason kept on the record.

Wire this to `hiveframe/carry.py`; the three exits already exist there.

## 9. Files and Chat

> Build the Files view from `design/prototype/files.jsx`, backed by `hiveframe/writer.py` and `edit.py`. Preserve the distinction between a one-line status rewrite (which refuses itself unless it matches exactly once) and a structural regeneration (which writes a `.bak` first and loses hand-written comments).

> Build the Chat view from `design/prototype/chat.jsx`, backed by `hiveframe/chat.py`. One thread per project, the reach panel showing granted directories and denied tools, and per-answer provenance: steps taken, refused tools, model, seconds, credits.

## What not to let Copilot do

- Invent colors, spacing or radii. Everything comes from the tokens.
- Drop the reason strings. A ranked list without visible reasons is the thing this design exists to avoid.
- Silently hide empty states — unwritten charter fields, unclaimed plan share, missing files, and lost projects are all deliberately visible.
- Round the phases down into a generic todo/doing/done. Seven phases, and phase is not status.
- Reflow the layout into cards-in-a-grid responsiveness. It targets a desktop window; if you need breakpoints, add them without changing the desktop composition.
