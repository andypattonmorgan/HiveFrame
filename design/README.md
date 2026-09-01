# Handoff: HiveFrame UI

## Overview

A six-view work-tracking interface for a single IC: **Today, Board, Goals, Focus, Files, Chat**. It puts every request and idea in exactly one of seven named phases, ranks what to do next and always shows the reasons for the rank, ties tasks to key results by declared weight, and forces every carried-over item to a written exit.

Target repository: `andypattonmorgan/HiveFrame` (branch `main`). HiveFrame today is a Python model + CLI (`hiveframe/model.py`, `carry.py`, `writer.py`, `edit.py`, `verdict.py`, `chat.py`). **This design is a new front-end surface over that existing model, not a restyle of the CLI.** Nothing in the Python model needs to change to render these screens, except where "New concepts" below says otherwise.

## About the design files

`prototype/` contains **design references written in HTML/JSX** — a running prototype of the intended look and behavior, not production code to copy. React + Babel are loaded from a CDN and compiled in the browser; all data is seeded in `data.js` / `data-extra.js`. The job is to **recreate these screens in whatever front-end environment HiveFrame adopts** (a React/Vite SPA over a small JSON API is the natural fit for a Python backend), using that environment's patterns — reading these files for exact layout, copy, arithmetic, and interaction rules.

Open `prototype/HiveFrame.html` in a browser to see it run. Everything is clickable.

## Fidelity

**High-fidelity.** Final colors, type, spacing, radii, copy and interaction states. Recreate it closely. The one deliberately loose part is responsive behavior — the prototype targets a desktop window ~1280px and wider and does not define breakpoints.

## Design system

The **Organic** design system, vendored at `prototype/_ds/organic-.../`:

- `styles.css` — the token sheet (`:root` custom properties) plus a component layer (`.btn`, `.card`, `.tag`, `.input`, `.nav`, `.table`, elevation utilities). Port this file as-is; it is the source of truth for every value.
- `_ds_bundle.js` — React components on `window.Organic_organi`. The prototype does not use these; it uses the CSS classes. You can ignore the bundle.

Character: warm cream ground, terracotta accent, sage second accent, Caprasimo headings over Figtree, 16px radii growing to pills, no sharp corners, no greys.

### Tokens (from `styles.css`)

Colors
```
--color-bg        #f5ead8    --color-accent    #c67139
--color-surface   #ebddc5    --color-accent-2  #7a8a5e
--color-text      #201e1d    --color-divider   color-mix(in srgb,#201e1d 16%,transparent)
```
Three tonal ramps at steps 100–900, generated in OKLCH on one shared lightness scale: `--color-neutral-*` (`#f9f4ed` → `#2e2b25`), `--color-accent-*` (`#fff2eb` → `#402310`, base 500 `#d67f48`), `--color-accent-2-*` (`#f0fae1` → `#272e1b`, base 500 `#8fa073`). Use 100–300 for tinted fills, 700–900 for text on tints and pressed states.

Type — `--font-heading: "Caprasimo"`, `--font-body: "Figtree"`, base 15px / 1.55. Headings: h1 42px, line-height 1.12, letter-spacing −0.015em. The `.h6` label style in the app CSS is 11px, uppercase, 0.08em tracking, weight 700, body font, at 55% text opacity.

Spacing (density 1.10×) — `--space-1` 4.4 · `--space-2` 8.8 · `--space-3` 13.2 · `--space-4` 17.6 · `--space-6` 26.4 · `--space-8` 35.2 px.

Radii — `--radius-sm` 8 · `--radius-md` 16 · `--radius-lg` 28 px; buttons, chips and pills are `999px`.

Shadows — `--shadow-sm/md/lg`, ink-tinted, defined in `styles.css`.

States — hover tints one ramp step, `:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px }`, disabled 45% opacity. Already in `styles.css`; do not restyle per component.

### App-level CSS

Everything app-specific lives in the `<style>` block of `prototype/HiveFrame.html` (~120 rules). Port it wholesale — it is written entirely against the tokens above. Key classes: `.shell/.main/.pane/.page` (layout), `.navlink`, `.chip`, `.col/.colhead/.colrule` (board columns), `.wcard/.wtitle/.wmeta/.crumb` (work cards), `.krbar/.krfill/.krplan/.krgap` (coverage bar), `.ring/.ringin/.clock/.pip` (timer), `.taskrow`, `.logrow`, `.railrow`, `.msg`, `.h6`, `.lede`, `.late`, `.missing`.

### Three grounds

`document.body[data-look]` switches ground: `warm` (#f5ead8, default), `sand` (#ebddc5), `ink` (#2e2b25 with light text and lifted accents). The overrides are the first block of rules in the HTML `<style>`. The nav's three colored dots set it. If you ship only one, ship `warm`; keep `ink` as the dark theme.

## Data model

`prototype/data.js` seeds `window.HF` and mirrors `hiveframe/model.py`.

**Item** (one flat array, `ITEMS`, self-nesting via `parent`):
```
id, tier: 'program'|'project'|'task'|'operation', parent: id|null,
title, phase: phase id, status: 'open'|'active'|'doing'|'blocked'|'done'|'dropped',
kind?, due?: 'YYYY-MM-DD', effort?: hours (float), urgent?: bool, important?: bool,
blocked_by?: [task id], charter?: { problem, hypothesis, goal, kill_when, done_when, stop_when },
krs?: [{ id: kr id, weight: 0-100 }]
```
Nesting is loose on purpose: a task may hang off a project, off a program, or off nothing.

**Phases** (`PHASES`, ordered — id, label, hint):
`idea` Idea "written down, not yet examined" · `discover` Discover "what is actually true" · `design` Design "the shape of the move" · `execute` Execute "building it" · `implement` Implement "in someone else's hands" · `closeout` Close out "verdict written, loose ends" · `done` Done "off the board".

**Goals** (`GOALS`) — `{ id, title, note, krs: [{ id, title, current, target, unit, start?, lowerIsBetter? }] }`.

Also in `window.HF`: `SESSIONS`, `TODAY` (the date the prototype treats as today), `WEEKLY_HOURS`, `DAILY_TARGET_SESSIONS`, and in `data-extra.js`: `DAILY`, `CARRY`, `FOLDERS`, `FILES`, `STORE`, `THREADS`, `GRANTED_DIRS`, `DENIED_TOOLS`, `MODELS`.

## The arithmetic (port exactly — `prototype/lib.jsx`)

**`isOpen(t)`** — status is neither `done` nor `dropped`.
**`actionable(t)`** — open, and no id in `blocked_by` belongs to an open task.
**`days(due)`** — whole days from `TODAY`; `dueLabel` renders "3 days past its date" / "due today" / "due in 5 days".

**`rankTask(task)`** mirrors `model.score()`. Every rank carries its reasons; a priority with no visible reason is an instruction, with one it is an argument that can be rejected. Not open → 0. Not actionable → −100, "waiting on an open sibling". Otherwise sum:

| Condition | Points | Reason string |
|---|---|---|
| overdue by *n* days | +40 + min(n,10) | the due label |
| due within 7 days | +30 − days | the due label |
| due within 28 days | +8 | the due label |
| `urgent` | +20 | "flagged urgent" |
| `important` | +10 | "flagged important" |
| due ≤2 days and effort ≤0.5h | +6 | "short, 0.5h — it will get finished" |
| due ≤2 days and effort ≥4h | −4 | "needs 4h, too big for one sitting" |
| declared KR weight *w* > 0 | +min(w/4, 12) | "carries 30% of a key result" |
| no KR weight | 0 | "contributes to no key result" |
| parent status `blocked` | +25 | "a move that attacks a blockage" |
| parent tier `operation` | −8 | "running work, not a deliverable" |

`focusQueue()` = open tasks, ranked, those above −50, sorted descending.

**`krState(kr)`** — the goals arithmetic:
- `realized` = measured progress, 0–100, clamped. Normal: `current / target`. `lowerIsBetter`: `(start − current) / (start − target)`.
- `planDone` = summed weights of closed contributors; `planOpen` = summed weights of open contributors (clamped so the two never exceed 100); `planGap` = `100 − planDone − planOpen`, floored at 0.
- `declared` = total declared weight. If it exceeds 100, say so: two tasks are claiming the same ground.

The gap is the readable part. `realized` is what actually moved; the bar underneath is whether anything on the board is even trying.

## Screens

Chrome on every screen: a top `.nav` (48px-ish, `--space-3`/`--space-6` padding, baseline-aligned) with the wordmark **HiveFrame**, six nav links (`Today Board Goals Focus Files Chat` — Caprasimo 15px, 55% opacity, current one full-opacity with a 2px accent underline), then right-aligned meta: "*n* open tasks", "*n*h dated in the next four weeks of a 12h week", and the three ground dots (20px circles, 2px accent outline when pressed).

### 1. Today (default view)

Two columns, `minmax(360px,1fr)` and `minmax(280px,360px)`, gap `--space-6`, max-width 1120.

H1 is the date. Lede: yesterday's blocks / hours logged / tasks closed, then the count of things already past their date.

Left column, two cards:
- **Past its date** — overdue tasks (soonest-overdue first) then tasks due today. Each row: title as a link button (opens it on the Board), a meta line of breadcrumb · due label · effort, and a ghost **Focus** button. Footer sentence counts items inside three days and open tasks that cannot be started at all.
- **Carry forward** — items left from the last session. "Three exits, no fourth. Nineteen items printed every morning is not a reminder, it is wallpaper." Each: title, heading, due, body text, and a **Resolve** toggle that reveals a one-line reason field and three buttons — *Make it a task / Make it a project / Drop it*. Resolving moves it to an **Archived today** list showing the outcome and the reason ("no reason given" if left empty), marked "kept on the record". Nothing vanishes without a written exit.

Right column, four cards:
- **First move** — top of the focus queue: title, breadcrumb, its top three reasons as accent-dotted bullets, and a full-width primary **Start a block on it**.
- **Capacity** — committed hours (open tasks dated within 28 days) in Caprasimo 30px against available hours (4 × weekly hours, less running/operation work). Overcommitted → "Overcommitted by *n*h. Visible now rather than in the miss."
- **Where the plan is thin** — the three key results with the largest `planGap`: realized %, title, goal, and "*n*% unclaimed" in the late color. Ghost **Goals** button jumps to that view.
- **What the board last lost** — the most recent killed/parked project with its verdict, date and reason. "A board that cannot lose an entry only grows."

### 2. Board

H1 **Board**, lede on loose nesting. A filter bar of pill chips: `All work`, one per program, `Unfiled`, then right-aligned `Show tasks` and `Show done` toggles. Pressed chips are solid accent with `--color-bg` text.

Below, seven horizontally scrolling phase columns, 250px each, gap `--space-3`. Each column header (sticky) is the phase label + count + summed effort in the small mono style, then the phase hint at 11px/45%, then a 3px rounded rule that turns accent when the column has cards.

**Work card** (`.card.elev-sm.wcard`, a button, `--space-3` padding, hover lifts 1px with `--shadow-md`, selected gets a 1px accent border): a tier tag (`program` accent, `project` sage, `task`/`operation` neutral) plus outline tags for `blocked` / `in the timer`; the ancestor breadcrumb in 10px uppercase; the title in Caprasimo 15px; for non-tasks "Next: *first actionable child task*"; a meta row of open/total tasks · due label (accent-700 and semibold when late) · effort · "waiting on a sibling"; and KR pills — sage-tinted 10px capsules reading "30% · key result title" (truncated at 28 chars, full title on hover). A project's pills are its tasks' weights summed per KR.

**Drawer** — 430px, left-bordered, opens on card click, closes on the same card or the Close button:
- Tier tag, kind, Close.
- Breadcrumb, title.
- **Phase** row: current label, Back / Advance buttons (disabled at the ends), and a seven-segment stepper filled to the current phase. Advancing to `done` sets status `done`; leaving `done` reopens it to `active`.
- **Charter** as a definition list; the fields shown depend on tier — program: problem, goal, stop when; operation: problem, goal; project: problem, hypothesis, goal, kill when, done when. Missing fields read "not written down yet" in italic accent-700. Never hide an unwritten field.
- **Contains** — non-task children with their phase.
- **Tasks** — checkbox (accent), title, due/effort/blocked meta, ghost **Focus**. Checking completes the task and moves it to the done phase.
- For a task: **Why it ranks where it does** (all reasons) and a full-width **Take this into the timer**.
- **Contributes to** — per KR, "*n*% closed · *n*% in flight", clickable through to Goals. Empty state: "Nothing here is declared against a key result. Work with no declared contribution is the first thing to question at close out."

### 3. Goals and key results

Single column, max-width 1020. H1, lede, then a legend of three swatches: solid accent **closed work**, sage 115° diagonal hatch **in flight**, faint text-colored dotted hatch **unclaimed**.

Each goal: title, note, then a card per key result:
- Left: KR title (15px Caprasimo) and the value line — "12 of 18 projects", or for `lowerIsBetter` "9 → 4 pending · lower is better, from 14".
- Right: realized percentage in Caprasimo 26px with the label "delivered".
- The **coverage bar**: 16px tall, fully rounded, faint track. Solid accent fill from the left for `planDone`; the sage hatch immediately after it for `planOpen`; the dotted hatch pinned right for `planGap`. Title attribute: "plan coverage: closed work, work in flight, and the share nothing is claiming".
- Under it: "*n*% in flight across *n* open items" · "*n*% of the plan is unclaimed" (in the late color) or "fully covered". A ghost **Contributions** toggle expands every contributing item — title, breadcrumb, phase, effort, and its weight with a ✓ when closed — each clickable to the Board. Empty: "No task anywhere on the board is declared against this result." Over 100%: "Declared weight totals *n*%. Two tasks are claiming the same ground; one of them is not needed."

Arriving here from a drawer's "Contributes to" highlights that KR with a 2px accent outline and auto-expands its contributions.

### 4. Focus

Two columns, `minmax(340px,1fr)` and `minmax(300px,420px)`, gap `--space-6`, max-width 1080.

Left, the **timer card** (`elev-md`, centered): mode label ("Focus block · 25 min" / "Break · 5 min"); a 210px conic-gradient ring filled by elapsed percentage with a 186px surface-colored inner disc holding the clock — Caprasimo 76px, tabular numerals, `mm:ss` — and a state word (running / paused / step away from it). Under it the current task: breadcrumb, title (clickable to the Board), due and estimate, and its KR pills or "contributes to no key result". Then **Start/Pause/Resume** (primary), **Stop and log**, **Break / Back to work**. Then a one-line note input, "One line on what happened in this block". Then a chip: **Run at 30× to watch a block finish** — a demo affordance that ticks 30 seconds per real second; keep it or drop it, but it is how the flow is demonstrated.

Behavior: 25/5. A work block reaching zero logs a session and starts the break; a break reaching zero returns to work. **Stop and log** writes a partial session of the elapsed whole minutes (≥1) with the note or "cut short", then resets. Logging a session flips the task's status from `open` to `doing`. Remaining time and mode persist to `localStorage` under `hf.focus`.

Below it, **Suggested next, and why** — the top four of the queue, each with its score in mono, title, breadcrumb, top three reasons, and a ghost **Swap in** (which resets the timer). The current task's row is tinted 12% accent.

Right column, three cards:
- **Today's target** — completed blocks (`logged minutes / 25`) as "2.4 of 6 blocks" in Caprasimo 34px, hours logged, and a row of 12px pips: filled for whole blocks, half-filled for a partial. Footnote ties it to the weekly budget.
- **Session log** — a 44px/1fr/auto grid: time, task title with the note beneath, minutes.
- **Estimate against logged** — per task, hours logged, the estimate, and the variance as ±%, the overrun in the late color. "Logged time is the only thing that corrects an estimate. Until a task has blocks against it, its number is a guess."

### 5. Files

Three columns — 200px, 250px, `minmax(360px,1fr)` — gap `--space-6`, max-width 1240.

Rail 1: projects that have named folders, with file counts; then the store's name, classification and root path.
Rail 2: per folder, its label, its path in 11px monospace, and its files. Each file shows size, or "the path does not exist" in the late color, plus badges "the contract" / "append only".
Column 3: filename, project · folder path, **Reveal** ("Finder opened at the path. HiveFrame reveals a location, it never launches the file."), **Save** (enabled only when dirty), and a monospace textarea (12.5px/1.6, min-height 420, `white-space: pre`, read-only for non-editable files). A missing file shows a card instead: "Declared, but not there" — nothing is repaired silently.

Saving produces a receipt card in a sage tint, and the distinction matters:
- **One line rewritten** when only `status = …` lines differ: "The write refuses itself if it cannot find exactly one match, so nothing else in the file can move."
- **File regenerated** otherwise: a `.bak` is written first, and hand-written TOML comments do not survive a structural edit.

Footer meta: "editable · every save keeps a .bak" or "read only · appended to by verdicts, never rewritten", plus "unsaved" in the late color when dirty.

### 6. Chat

Two columns — 230px and `minmax(380px,1fr)` — gap `--space-6`, max-width 1100.

Rail: **Threads**, one per project, with turn counts — switching project switches thread, so a question about one project is never answered out of another's history. **Reach**: the granted directories as monospace paths, noting the shared reference libraries are not among them. **Denied**: outline tags for the denied tools, noting nothing leaves the machine.

Main: header with project title, store name, turn count and credits spent this thread; a model `select`; **New thread**, which archives the transcript to `transcript.<thread>.<yyyymmdd>.jsonl` and says the session is forgotten here, not deleted.

Transcript (max-height 52vh, auto-scrolled to the bottom): user messages right-aligned in solid accent with `--color-bg` text and an optional "[screen, not typed] board state was sent with this" line; assistant messages on `--color-surface` with a step list above the answer (● for a step taken, ✗ in the late color for a refused tool, each with a monospace detail line), and a footer of model · seconds · "0.019 credits, measured as the difference between readings". Every answer carries its provenance.

Composer: textarea (⌘/Ctrl+Enter sends), a **Send what is on screen** chip, and a primary **Ask**.

## State

Held in `App`: `view`, `selected` (drawer item), `filter` `{program, tasks, done}`, `focusTask`, `krHighlight`, `fileProject`, `look`. In `useModel`: `items`, `sessions` plus derived helpers (`byId`, `childrenOf`, `tasksOf`, `openTasksOf`, `actionable`, `path`). Locally: timer state in Focus, edited bodies and receipts in Files, threads and drafts in Chat, carry/archive in Today.

Cross-view navigation: drawer → Focus (sets task, switches view), drawer "Contributes to" → Goals (highlights KR), Goals/Today rows → Board (opens drawer), Today "Where the plan is thin" → Goals.

## New concepts (not yet in the repo)

Two things the prototype assumes that `hiveframe/` has no counterpart for. Both need a model decision before they can be persisted:

1. **Weighted KR contribution** — `krs: [{id, weight}]` on tasks, rolled up to projects and programs, and a `GOALS`/key-result store. This drives the whole Goals view, the KR pills, the +min(w/4,12) rank term and Today's "where the plan is thin".
2. **The seven phases** — a named, ordered `phase` per item, distinct from `status`. Status says whether an item is live; phase says how far through the work it is.

If either should take a different shape in the model, decide that before implementing Goals or the Board columns.

## Assets

None. No images, no icon files. The design system nominates Lucide at stroke-width 2.75 for icons; the prototype uses none. Fonts are Caprasimo and Figtree, loaded by `styles.css`.

## Files in this bundle

```
prototype/HiveFrame.html   shell, script loading, and all app-level CSS
prototype/data.js          PHASES, GOALS, ITEMS, SESSIONS, TODAY, WEEKLY_HOURS
prototype/data-extra.js    DAILY, CARRY, FOLDERS, FILES, STORE, THREADS, reach, models
prototype/lib.jsx          useModel, days/dueLabel/hrs, rankTask, focusQueue, krState, Tag/KrPill/KrBar
prototype/app.jsx          shell, nav, view switching, ground switching
prototype/today.jsx        Today
prototype/board.jsx        Board, WorkCard, Drawer
prototype/goals.jsx        Goals, KrRow
prototype/focus.jsx        Focus
prototype/files.jsx        Files
prototype/chat.jsx         Chat
prototype/_ds/organic-…/   styles.css (port this) and _ds_bundle.js (unused)
COPILOT.md                 a suggested order of work, as prompts
```
