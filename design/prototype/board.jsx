function Board({ model, filter, setFilter, selected, onSelect }) {
  const programs = model.items.filter(i => i.tier === 'program');
  const inProgram = item => {
    if (filter.program === 'all') return true;
    if (filter.program === 'unfiled') return !item.parent && item.tier !== 'program';
    return item.id === filter.program || model.path(item).some(p => p.id === filter.program);
  };
  const cards = model.items.filter(i => {
    if (i.tier === 'program') return false;
    if (i.tier === 'task' && !filter.tasks && i.parent) return false;
    if (!filter.done && i.status === 'done') return false;
    return inProgram(i);
  });
  return (
    <div className="pane">
      <div style={{ padding: 'var(--space-2) var(--space-6) var(--space-3)' }}>
        <h1 className="pt">Board</h1>
        <p className="lede">Every request and idea sits in exactly one phase. Nesting is loose: a task can hang off a project, a program, or nothing at all.</p>
      </div>
      <div className="subbar">
        <span className="h6" style={{ marginRight: 4 }}>Program</span>
        <button className="chip" aria-pressed={filter.program === 'all'} onClick={() => setFilter({ ...filter, program: 'all' })}>All work</button>
        {programs.map(p => (
          <button key={p.id} className="chip" aria-pressed={filter.program === p.id} onClick={() => setFilter({ ...filter, program: p.id })}>{p.title}</button>
        ))}
        <button className="chip" aria-pressed={filter.program === 'unfiled'} onClick={() => setFilter({ ...filter, program: 'unfiled' })}>Unfiled</button>
        <span style={{ flex: 1 }} />
        <button className="chip" aria-pressed={filter.tasks} onClick={() => setFilter({ ...filter, tasks: !filter.tasks })}>Show tasks</button>
        <button className="chip" aria-pressed={filter.done} onClick={() => setFilter({ ...filter, done: !filter.done })}>Show done</button>
      </div>
      <div className="board">
        {PHASES.map(ph => {
          const col = cards.filter(c => c.phase === ph.id);
          const effort = col.reduce((s, c) => s + (c.effort || model.openTasksOf(c.id).reduce((n, t) => n + (t.effort || 0), 0)), 0);
          return (
            <div className="col" key={ph.id} data-active={col.length > 0}>
              <div className="colhead">
                <div className="colname">{ph.label}<span className="colcount">{col.length}{effort ? ' · ' + hrs(Math.round(effort * 4) / 4) : ''}</span></div>
                <div className="colhint">{ph.hint}</div>
                <div className="colrule" />
              </div>
              <div className="stack">
                {col.map(c => <WorkCard key={c.id} item={c} model={model} selected={selected === c.id} onSelect={onSelect} />)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WorkCard({ item, model, selected, onSelect }) {
  const trail = model.path(item);
  const tasks = model.tasksOf(item.id);
  const openT = tasks.filter(isOpen);
  const next = openT.filter(t => model.actionable(t)).sort((a, b) => (days(a.due) ?? 99) - (days(b.due) ?? 99))[0];
  const due = item.tier === 'task' ? item.due : next && next.due;
  const late = due !== undefined && due !== null && days(due) !== null && days(due) < 1;
  const krs = item.tier === 'task' ? (item.krs || [])
    : Object.entries(tasks.reduce((acc, t) => {
        (t.krs || []).forEach(k => { acc[k.id] = (acc[k.id] || 0) + k.weight; }); return acc;
      }, {})).map(([id, weight]) => ({ id, weight }));
  return (
    <button className="card elev-sm wcard" aria-selected={selected} onClick={() => onSelect(item.id)}>
      <div className="wcard-top">
        <Tag kind={TIER_TAG[item.tier]}>{item.tier}</Tag>
        {item.status === 'blocked' && <Tag kind="tag-outline">blocked</Tag>}
        {item.status === 'doing' && <Tag kind="tag-outline">in the timer</Tag>}
      </div>
      {trail.length > 0 && <div className="crumb">{trail.map(t => t.title).join(' › ')}</div>}
      <div className="wtitle">{item.title}</div>
      {item.tier !== 'task' && next && <div className="wnext">Next: {next.title}</div>}
      <div className="wmeta">
        {item.tier !== 'task' && <span>{openT.length + ' open of ' + tasks.length}</span>}
        {due && <><Bullet /><span className={late ? 'late' : ''}>{dueLabel(due)}</span></>}
        {item.tier === 'task' && item.effort && <><Bullet /><span>{hrs(item.effort)}</span></>}
        {item.tier === 'task' && (item.blocked_by || []).length > 0 && !model.actionable(item) && <><Bullet /><span>waiting on a sibling</span></>}
      </div>
      {krs.length > 0 && <div className="wcard-top">{krs.map(k => <KrPill key={k.id} {...k} />)}</div>}
    </button>
  );
}

const CHARTER_FIELDS = [
  ['problem', 'Problem'], ['hypothesis', 'Hypothesis'], ['goal', 'Goal'],
  ['kill_when', 'Kill when'], ['done_when', 'Done when'], ['stop_when', 'Stop when']
];

function Drawer({ id, model, onClose, onFocus, onGoal }) {
  const item = model.byId[id];
  if (!item) return null;
  const trail = model.path(item);
  const tasks = model.tasksOf(item.id);
  const kids = model.childrenOf(item.id).filter(k => k.tier !== 'task');
  const ix = PHASE_IX[item.phase];
  const wanted = item.tier === 'program' ? ['problem', 'goal', 'stop_when']
    : item.tier === 'operation' ? ['problem', 'goal']
    : ['problem', 'hypothesis', 'goal', 'kill_when', 'done_when'];
  const move = dir => {
    const to = PHASES[Math.max(0, Math.min(PHASES.length - 1, ix + dir))].id;
    model.setItems(items => items.map(i => i.id === item.id ? { ...i, phase: to, status: to === 'done' ? 'done' : (i.status === 'done' ? 'active' : i.status) } : i));
  };
  const toggleTask = t => model.setItems(items => items.map(i => i.id === t.id
    ? { ...i, status: isOpen(i) ? 'done' : 'open', phase: isOpen(i) ? 'done' : i.phase } : i));
  const krRoll = Object.entries((item.tier === 'task' ? [item] : tasks).reduce((acc, t) => {
    (t.krs || []).forEach(k => {
      acc[k.id] = acc[k.id] || { done: 0, open: 0 };
      acc[k.id][isOpen(t) ? 'open' : 'done'] += k.weight;
    }); return acc;
  }, {}));
  const rank = item.tier === 'task' ? rankTask(item, model) : null;
  return (
    <aside className="drawer">
      <div className="row">
        <Tag kind={TIER_TAG[item.tier]}>{item.tier}</Tag>
        {item.kind && <span className="crumb">{item.kind}</span>}
        <span className="grow" />
        <button className="btn btn-secondary" onClick={onClose}>Close</button>
      </div>
      {trail.length > 0 && <div className="crumb">{trail.map(t => t.title).join(' › ')}</div>}
      <h3 style={{ margin: 0 }}>{item.title}</h3>
      <div>
        <div className="spread">
          <span className="h6">Phase · {PHASES[ix].label}</span>
          <span className="row">
            <button className="btn btn-secondary" disabled={ix === 0} onClick={() => move(-1)}>Back</button>
            <button className="btn btn-primary" disabled={ix === PHASES.length - 1} onClick={() => move(1)}>Advance</button>
          </span>
        </div>
        <div className="stepper" style={{ marginTop: 8 }}>
          {PHASES.map((p, i) => <div key={p.id} className="step" data-on={i <= ix} title={p.label} />)}
        </div>
      </div>
      <div>
        <div className="h6">Charter</div>
        <dl className="charter">
          {CHARTER_FIELDS.filter(([k]) => wanted.includes(k)).map(([k, label]) => (
            <div key={k}>
              <dt>{label}</dt>
              <dd className={(item.charter || {})[k] ? '' : 'missing'}>{(item.charter || {})[k] || 'not written down yet'}</dd>
            </div>
          ))}
        </dl>
      </div>
      {kids.length > 0 && (
        <div>
          <div className="h6">Contains</div>
          <div className="tasklist">
            {kids.map(k => (
              <div className="taskrow" key={k.id}>
                <span className="grow">{k.title}</span>
                <span className="mono">{PHASES[PHASE_IX[k.phase]].label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {tasks.length > 0 && (
        <div>
          <div className="h6">Tasks</div>
          <div className="tasklist">
            {tasks.map(t => (
              <div className="taskrow" key={t.id} data-done={!isOpen(t)}>
                <input type="checkbox" checked={!isOpen(t)} onChange={() => toggleTask(t)} style={{ marginTop: 3, accentColor: 'var(--color-accent)' }} />
                <span className="grow">
                  {t.title}
                  <span className="wmeta">
                    {t.due && <span className={days(t.due) < 1 ? 'late' : ''}>{dueLabel(t.due)}</span>}
                    {t.effort && <><Bullet /><span>{hrs(t.effort)}</span></>}
                    {!model.actionable(t) && isOpen(t) && <><Bullet /><span>waiting on a sibling</span></>}
                  </span>
                </span>
                <button className="btn btn-ghost" onClick={() => onFocus(t.id)}>Focus</button>
              </div>
            ))}
          </div>
        </div>
      )}
      {item.tier === 'task' && (
        <div>
          <div className="h6">Why it ranks where it does</div>
          <div className="why">{rank.why.map((w, i) => <div className="whyrow" key={i}>{w}</div>)}</div>
          <button className="btn btn-primary btn-block" onClick={() => onFocus(item.id)}>Take this into the timer</button>
        </div>
      )}
      <div>
        <div className="h6">Contributes to</div>
        {krRoll.length === 0 && <p className="lede" style={{ margin: '4px 0 0' }}>Nothing here is declared against a key result. Work with no declared contribution is the first thing to question at close out.</p>}
        <div className="tasklist">
          {krRoll.map(([kid, w]) => {
            const kr = KR_BY_ID[kid];
            return (
              <button className="taskrow" key={kid} onClick={() => onGoal(kid)} style={{ textAlign: 'left', border: 0, cursor: 'pointer', font: 'inherit', fontSize: 13 }}>
                <span className="grow">
                  {kr.title}
                  <span className="wmeta">{kr.goal.title}</span>
                </span>
                <span className="mono" title="closed % · in flight %">{w.done + '% closed · ' + w.open + '% in flight'}</span>
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

Object.assign(window, { Board, WorkCard, Drawer });
