/* Seed data. Invented content, shaped after the HiveFrame project model:
   tiers (program / project / task / operation), a charter per project,
   tasks with effort + flags + blocked_by, and weighted KR contributions. */
window.HF = (function () {
  const PHASES = [
    { id: 'idea', label: 'Idea', hint: 'written down, not yet examined' },
    { id: 'discover', label: 'Discover', hint: 'what is actually true' },
    { id: 'design', label: 'Design', hint: 'the shape of the move' },
    { id: 'execute', label: 'Execute', hint: 'building it' },
    { id: 'implement', label: 'Implement', hint: 'in someone else’s hands' },
    { id: 'closeout', label: 'Close out', hint: 'verdict written, loose ends' },
    { id: 'done', label: 'Done', hint: 'off the board' }
  ];

  const GOALS = [
    {
      id: 'g-bleed', title: 'Stop context bleed across threads',
      note: 'A dozen threads in one head means direction changes before anyone notices.',
      krs: [
        { id: 'kr-charter', title: 'Every live project carries a complete charter', current: 12, target: 18, unit: 'projects' },
        { id: 'kr-relations', title: 'Relations awaiting a verdict', current: 9, target: 4, unit: 'pending', start: 14, lowerIsBetter: true }
      ]
    },
    {
      id: 'g-capacity', title: 'Make capacity honest before a date slips',
      note: 'Overcommitment should be visible in the projection, not in the miss.',
      krs: [
        { id: 'kr-estimate', title: 'Estimate error on logged tasks', current: 34, target: 18, unit: '%', start: 45, lowerIsBetter: true },
        { id: 'kr-lose', title: 'Entries the board loses this quarter', current: 4, target: 6, unit: 'killed or parked' }
      ]
    },
    {
      id: 'g-lab', title: 'Resolve the first two lab hypotheses',
      note: 'A hypothesis that never resolves is a program pretending to be a project.',
      krs: [
        { id: 'kr-resolved', title: 'Hypotheses resolved with a written verdict', current: 1, target: 2, unit: 'resolved' },
        { id: 'kr-hours', title: 'Focus hours logged against lab work', current: 26, target: 40, unit: 'hours' }
      ]
    }
  ];

  const ITEMS = [
    { id: 'p-lab', tier: 'program', title: 'Next-Gen Delivery Lab', phase: 'execute', status: 'active',
      charter: { problem: 'Delivery ideas are argued rather than tested.', goal: 'A standing place to run small hypotheses to a verdict.', stop_when: 'Two consecutive quarters where no hypothesis is promoted.' } },
    { id: 'p-surface', tier: 'program', title: 'Working surface', phase: 'execute', status: 'active',
      charter: { problem: 'The board is held in a conversation and a head.', goal: 'One surface that holds threads without them bleeding.', stop_when: 'The file format is stable and the UI stops earning its upkeep.' } },

    { id: 'brief', tier: 'project', parent: 'p-lab', title: 'Connector-fed brief', phase: 'execute', status: 'active', kind: 'experiment',
      charter: { problem: 'The morning brief is assembled by hand and so it is skipped.', hypothesis: 'Read-only connectors can fill 80% of it with no new access.', goal: 'A brief that is worth reading before the first meeting.', kill_when: 'Two weeks where the generated brief is edited more than it is read.', done_when: 'Five consecutive working days generated with no manual edit.' } },
    { id: 'graph', tier: 'project', parent: 'p-lab', title: 'Relation graph', phase: 'design', status: 'blocked', kind: 'deliverable',
      charter: { problem: 'Links between projects exist only as inference, and a wrong one looks like a right one.', hypothesis: 'Drawing declared relations makes the missing ones obvious.', goal: 'Every confirmed relation visible in one view.', kill_when: 'Nobody opens it twice in a fortnight.', done_when: 'Suggested links can be resolved from the graph itself.' } },
    { id: 'calib', tier: 'project', parent: 'p-surface', title: 'Capacity calibration from logged sessions', phase: 'discover', status: 'active', kind: 'analysis',
      charter: { problem: 'Estimates are wrong and nothing corrects them.', hypothesis: 'Logged focus time against tasks measures the error rather than guessing it.', goal: 'A correction factor per kind of work.', kill_when: 'Fewer than twenty logged sessions after a month.', done_when: 'The projection uses measured hours, not entered ones.' } },
    { id: 'triage2', tier: 'project', parent: 'p-surface', title: 'Sub-project rows in triage', phase: 'idea', status: 'active', kind: 'deliverable',
      charter: { problem: 'Only whole projects can be triaged, so a dead hypothesis survives inside a live project.', goal: 'A verdict at the altitude the work actually sits.', done_when: 'A hypothesis can be killed without touching its parent.' } },
    { id: 'charters', tier: 'project', parent: 'p-surface', title: 'Charter completion sweep', phase: 'implement', status: 'active', kind: 'admin',
      charter: { problem: 'Six live projects have no kill_when, so nothing on the board can fail.', goal: 'Every live project answers problem, goal and its ending.', done_when: 'The incomplete-charter count reads zero for a full week.' } },
    { id: 'keychain', tier: 'project', title: 'Keychain connector audit', phase: 'implement', status: 'active', kind: 'tool',
      charter: { problem: 'Credentials are resolved at run time and nobody has checked which still resolve.', goal: 'A list of connectors that work, with the ones that do not named.', done_when: 'Every connector in the registry has a dated check.' } },
    { id: 'retire', tier: 'project', title: 'Retire dead tool entries', phase: 'closeout', status: 'active', kind: 'admin',
      charter: { problem: 'Nine tools are used by nothing and it is not known which are load-bearing.', goal: 'The registry lists only tools something depends on, or says why not.', done_when: 'Every used-by-nothing entry has a retirement reason or a declared dependant.' } },
    { id: 'review', tier: 'operation', title: 'Weekly review', phase: 'implement', status: 'active', kind: 'admin',
      charter: { problem: 'Without a standing review the board only grows.', goal: 'One pass a week that removes something.' } },
    { id: 'ledger', tier: 'project', parent: 'p-lab', title: 'Decision ledger readout', phase: 'done', status: 'done', kind: 'analysis',
      charter: { problem: 'Verdicts are appended and never read back.', goal: 'A quarterly readout of what the board stopped doing and why.', done_when: 'The first readout is written.' } },

    // Tasks. Flexible nesting: a task sits under a project, a program, or nothing.
    // A weight is the share of a KR's plan this one task is meant to close.
    { id: 't-brief-1', tier: 'task', parent: 'brief', title: 'Map the four GET calls the brief needs', phase: 'execute', status: 'done', effort: 2, krs: [{ id: 'kr-hours', weight: 10 }] },
    { id: 't-brief-2', tier: 'task', parent: 'brief', title: 'Render the brief from cached responses', phase: 'execute', status: 'doing', due: '2026-08-28', effort: 3, urgent: true, krs: [{ id: 'kr-resolved', weight: 20 }, { id: 'kr-hours', weight: 15 }] },
    { id: 't-brief-3', tier: 'task', parent: 'brief', title: 'Five-day unedited trial', phase: 'implement', status: 'open', due: '2026-09-08', effort: 1.5, blocked_by: ['t-brief-2'], important: true, krs: [{ id: 'kr-resolved', weight: 30 }, { id: 'kr-hours', weight: 10 }] },
    { id: 't-brief-4', tier: 'task', parent: 'brief', title: 'Write the verdict, kept or killed', phase: 'closeout', status: 'open', due: '2026-09-15', effort: 0.5, blocked_by: ['t-brief-3'], krs: [{ id: 'kr-resolved', weight: 30 }] },
    { id: 't-graph-1', tier: 'task', parent: 'graph', title: 'Decide the edge vocabulary with Priya', phase: 'design', status: 'open', due: '2026-08-25', effort: 0.5, urgent: true, note: 'Waiting on Priya since the 19th.', krs: [{ id: 'kr-relations', weight: 25 }] },
    { id: 't-graph-2', tier: 'task', parent: 'graph', title: 'Resolve the nine suggested links', phase: 'design', status: 'open', due: '2026-09-02', effort: 2, important: true, krs: [{ id: 'kr-relations', weight: 45 }, { id: 'kr-hours', weight: 15 }] },
    { id: 't-calib-1', tier: 'task', parent: 'calib', title: 'Pull 30 logged sessions against their estimates', phase: 'discover', status: 'doing', due: '2026-08-27', effort: 1, important: true, krs: [{ id: 'kr-estimate', weight: 30 }, { id: 'kr-hours', weight: 10 }] },
    { id: 't-calib-2', tier: 'task', parent: 'calib', title: 'Write the correction factor into the projection', phase: 'design', status: 'open', due: '2026-09-11', effort: 4, blocked_by: ['t-calib-1'], krs: [{ id: 'kr-estimate', weight: 50 }] },
    { id: 't-charter-1', tier: 'task', parent: 'charters', title: 'Write kill_when for the six live projects missing it', phase: 'implement', status: 'open', due: '2026-08-26', effort: 1.5, urgent: true, important: true, krs: [{ id: 'kr-charter', weight: 35 }] },
    { id: 't-charter-2', tier: 'task', parent: 'charters', title: 'Fill goal and done_when on the four lab hypotheses', phase: 'implement', status: 'open', due: '2026-09-04', effort: 2, krs: [{ id: 'kr-charter', weight: 30 }] },
    { id: 't-key-1', tier: 'task', parent: 'keychain', title: 'Check each connector still resolves its credential', phase: 'implement', status: 'open', due: '2026-08-31', effort: 2, krs: [] },
    { id: 't-retire-1', tier: 'task', parent: 'retire', title: 'Write a retirement reason for each used-by-nothing tool', phase: 'closeout', status: 'open', due: '2026-08-29', effort: 1, krs: [{ id: 'kr-lose', weight: 20 }] },
    { id: 't-ledger-1', tier: 'task', parent: 'ledger', title: 'First quarterly readout of what the board stopped', phase: 'done', status: 'done', effort: 1.5, krs: [{ id: 'kr-lose', weight: 20 }] },
    { id: 't-loose-1', tier: 'task', title: 'Ask Dana whether the warehouse view is still read-only', phase: 'discover', status: 'open', due: '2026-08-27', effort: 0.25, urgent: true, krs: [] },
    { id: 't-loose-2', tier: 'task', title: 'Note the two ideas from Thursday’s call before they rot', phase: 'idea', status: 'open', effort: 0.5, krs: [] },
    { id: 't-review-1', tier: 'task', parent: 'review', title: 'Friday pass: remove one entry', phase: 'implement', status: 'open', due: '2026-08-28', effort: 0.75, krs: [{ id: 'kr-lose', weight: 15 }] },
    { id: 't-triage-1', tier: 'task', parent: 'triage2', title: 'Sketch the row-level verdict control', phase: 'idea', status: 'open', effort: 1, krs: [{ id: 'kr-lose', weight: 25 }] }
  ];

  const SESSIONS = [
    { id: 's1', item: 't-calib-1', minutes: 25, at: '09:12', note: 'pulled 18 of 30' },
    { id: 's2', item: 't-calib-1', minutes: 25, at: '09:45', note: '' },
    { id: 's3', item: 't-brief-2', minutes: 25, at: '11:03', note: 'cache layer works' },
    { id: 's4', item: 't-charter-1', minutes: 12, at: '13:40', note: 'cut short — Dana call' }
  ];

  const TODAY = '2026-08-27';
  return { PHASES, GOALS, ITEMS, SESSIONS, TODAY, WEEKLY_HOURS: 10, DAILY_TARGET_SESSIONS: 6 };
})();
