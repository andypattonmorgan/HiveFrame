/* Files, chat threads, carry-forward items — the parts of HiveFrame that reach
   outside the board: named directories only, one thread per project. */
Object.assign(window.HF, {
  STORE: { name: 'work', root: '~/OneDrive/hiveframe/projects', classification: 'KP internal' },
  GRANTED_DIRS: ['~/OneDrive/hiveframe/projects', '~/OneDrive/KaiserKM', '/opt/homebrew/bin'],
  DENIED_TOOLS: ['curl', 'wget', 'ssh', 'scp', 'rsync', 'git push', 'git reset --hard', 'rm -rf'],
  MODELS: [
    { id: 'gpt-5.4-mini', tier: 'light', rel: 1.5 },
    { id: 'claude-sonnet-4.5', tier: 'standard', rel: 2.8 },
    { id: 'gpt-5.4', tier: 'standard', rel: 5.0 },
    { id: 'claude-opus-5', tier: 'heavy', rel: 20.8 }
  ],

  FOLDERS: {
    brief: [
      { label: 'Project folder', path: '~/OneDrive/hiveframe/projects/brief' },
      { label: 'Working notes', path: '~/OneDrive/KaiserKM/brief-notes' }
    ],
    graph: [{ label: 'Project folder', path: '~/OneDrive/hiveframe/projects/graph' }],
    calib: [{ label: 'Project folder', path: '~/OneDrive/hiveframe/projects/calib' }],
    charters: [{ label: 'Project folder', path: '~/OneDrive/hiveframe/projects/charters' }],
    keychain: [{ label: 'Project folder', path: '~/OneDrive/hiveframe/projects/keychain' }],
    retire: [{ label: 'Project folder', path: '~/OneDrive/hiveframe/projects/retire' }],
    triage2: [{ label: 'Project folder', path: '~/OneDrive/hiveframe/projects/triage2' }]
  },

  FILES: [
    { id: 'f-brief-toml', project: 'brief', folder: 0, name: 'brief.toml', kind: 'toml', bytes: 2140, editable: true, contract: true,
      body: `[project]
id = "brief"
name = "Connector-fed brief"
tier = "project"
parent = "p-lab"
kind = "experiment"
status = "active"
phase = "execute"
store = "work"
folder = "~/OneDrive/hiveframe/projects/brief"
started = 2026-07-14
uses = [ "concerto-read", "warehouse-view" ]

[charter]
problem = "The morning brief is assembled by hand and so it is skipped."
hypothesis = "Read-only connectors can fill 80% of it with no new access."
goal = "A brief that is worth reading before the first meeting."
kill_when = "Two weeks where the generated brief is edited more than it is read."
done_when = "Five consecutive working days generated with no manual edit."

[[task]]
id = "t-brief-2"
title = "Render the brief from cached responses"
status = "doing"
due = 2026-08-28
effort_h = 3.0
urgent = true

[[task]]
id = "t-brief-3"
title = "Five-day unedited trial"
status = "open"
due = 2026-09-08
effort_h = 1.5
blocked_by = [ "t-brief-2" ]
important = true

[[relation]]
to = "graph"
type = "informs"
status = "suggested"
note = "Proposed by the assistant on 2026-08-19. Needs a yes or no."
` },
    { id: 'f-brief-notes', project: 'brief', folder: 1, name: 'cache-shape.md', kind: 'md', bytes: 860, editable: true,
      body: `# Cache shape

Four GETs, all read-only, none of them new access:

- Concerto: open requests assigned to me
- Warehouse view: yesterday's volumes
- Calendar: today, first three blocks
- inbox.jsonl: anything parked since the last brief

Cached responses live for the working day. A brief that re-fetches on every
render is a brief that fails when the VPN drops, and the VPN drops.
` },
    { id: 'f-brief-sample', project: 'brief', folder: 0, name: 'sample-2026-08-26.txt', kind: 'txt', bytes: 410, editable: false,
      body: `Generated 06:40. Edited 0 times.

Overdue: decide the edge vocabulary with Priya (2 days).
Due today: pull 30 logged sessions against their estimates.
Parked yesterday: "warehouse view read-only?" — still unanswered.
Capacity: 20h dated against 12.9h available in the next four weeks.
` },
    { id: 'f-brief-missing', project: 'brief', folder: 1, name: 'brief-mock-v2.sketch', kind: 'missing', bytes: 0, editable: false, missing: true,
      body: '' },
    { id: 'f-decisions', project: 'brief', folder: 0, name: 'decisions.jsonl', kind: 'jsonl', bytes: 1290, editable: false, appendOnly: true,
      body: `{"at":"2026-08-04T09:12:04","project":"ledger","verdict":"done","reason":"first readout written and read"}
{"at":"2026-08-11T16:02:41","project":"inbox-digest","verdict":"killed","reason":"nobody opened it twice"}
{"at":"2026-08-18T08:31:19","project":"graph","verdict":"keep","reason":"blocks two other threads"}
{"at":"2026-08-25T17:44:02","project":"sms-nudges","verdict":"parked","reason":"needs a write path we will not build"}
` },
    { id: 'f-graph-toml', project: 'graph', folder: 0, name: 'graph.toml', kind: 'toml', bytes: 1180, editable: true, contract: true,
      body: `[project]
id = "graph"
name = "Relation graph"
tier = "project"
parent = "p-lab"
status = "blocked"
phase = "design"

[charter]
problem = "Links between projects exist only as inference, and a wrong one looks like a right one."
hypothesis = "Drawing declared relations makes the missing ones obvious."
goal = "Every confirmed relation visible in one view."
kill_when = "Nobody opens it twice in a fortnight."
done_when = "Suggested links can be resolved from the graph itself."

[[task]]
id = "t-graph-1"
title = "Decide the edge vocabulary with Priya"
status = "open"
due = 2026-08-25
effort_h = 0.5
urgent = true
note = "Waiting on Priya since the 19th."
` },
    { id: 'f-calib-toml', project: 'calib', folder: 0, name: 'calib.toml', kind: 'toml', bytes: 940, editable: true, contract: true,
      body: `[project]
id = "calib"
name = "Capacity calibration from logged sessions"
tier = "project"
parent = "p-surface"
status = "active"
phase = "discover"

[charter]
problem = "Estimates are wrong and nothing corrects them."
goal = "A correction factor per kind of work."
done_when = "The projection uses measured hours, not entered ones."
` },
    { id: 'f-calib-csv', project: 'calib', folder: 0, name: 'sessions-export.csv', kind: 'csv', bytes: 2310, editable: false,
      body: `task,estimate_h,logged_h,kind
t-brief-1,2.0,2.4,build
t-calib-1,1.0,1.4,analysis
t-charter-1,1.5,0.2,writing
t-retire-1,1.0,,admin
`}
  ],

  CARRY: [
    { id: 'c-9f2a', heading: 'From the 24th', title: 'Warehouse view access', text: 'Confirm the warehouse view is still read-only before the brief depends on it. Dana owns it.', due: '2026-08-27' },
    { id: 'c-4b71', heading: 'From the 24th', title: 'Estimate calibration sample', text: 'Agreed to hold the correction factor until thirty sessions are logged, not twenty.', due: '' },
    { id: 'c-c803', heading: 'From the 19th', title: 'Priya on edge vocabulary', text: 'Priya to come back on whether "informs" and "feeds" are worth separating. Chase if nothing by the 26th.', due: '2026-08-26' }
  ],

  THREADS: {
    brief: [
      { role: 'user', at: '08:41', text: 'What is actually blocking the five-day trial?' },
      { role: 'assistant', at: '08:41', model: 'gpt-5.4-mini', seconds: 11.4, credits: 0.021,
        steps: [
          { glyph: '●', title: 'Read brief.toml', detail: 'projects/brief/brief.toml · 2.1 kB' },
          { glyph: '●', title: 'Read cache-shape.md', detail: 'KaiserKM/brief-notes/cache-shape.md' },
          { glyph: '✗', title: 'shell(curl) refused', detail: 'denied tool — nothing leaves the machine' }
        ],
        text: 'The trial is waiting on one sibling: “Render the brief from cached responses”, which is still doing and due tomorrow. Nothing else in brief.toml blocks it.\n\nThe trial itself carries 30% of “hypotheses resolved with a written verdict”, so it is the only open task on this project that moves that result. If the render slips past the 28th the trial cannot start until September and the verdict lands after the quarter closes.' },
      { role: 'user', at: '08:44', text: 'Does the suggested link to the relation graph matter here?' },
      { role: 'assistant', at: '08:44', model: 'gpt-5.4-mini', seconds: 7.2, credits: 0.014,
        steps: [{ glyph: '●', title: 'Read brief.toml', detail: 'relation table' }],
        text: 'It is still suggested, proposed on the 19th, so it affects nothing until you confirm or reject it. The note says “informs”, which does not block either project. Leaving it unresolved does cost you: it keeps counting as a pending link on both boards.' }
    ],
    graph: [
      { role: 'user', at: '14:02', text: 'Priya has not replied. What can I do on this today?' },
      { role: 'assistant', at: '14:02', model: 'claude-sonnet-4.5', seconds: 14.9, credits: 0.048,
        steps: [
          { glyph: '●', title: 'Read graph.toml', detail: 'projects/graph/graph.toml' },
          { glyph: '●', title: 'List projects with pending relations', detail: '9 suggested links across 4 projects' }
        ],
        text: 'One move, and it is not the one you are waiting on. “Resolve the nine suggested links” needs no vocabulary decision for seven of them — only two use the informs/feeds distinction Priya is holding.\n\nDoing the seven now takes the project from blocked to moving and drops the pending count from nine to two, which is most of the key result. The two contested edges can wait for her without holding the rest.' }
    ]
  },

  DAILY: {
    date: 'Thursday 27 August',
    yesterday: { blocks: 5, logged: 2.1, closed: 1 },
    lost: { at: 'the 25th', project: 'SMS nudges', verdict: 'parked', reason: 'needs a write path we will not build' }
  }
});
