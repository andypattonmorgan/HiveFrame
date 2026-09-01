function Today({ model, onFocus, onSelect, goTo }) {
  const D = window.HF.DAILY;
  const [carry, setCarry] = React.useState(window.HF.CARRY);
  const [archive, setArchive] = React.useState([]);
  const [resolving, setResolving] = React.useState(null);
  const [reason, setReason] = React.useState('');

  const openTasks = model.items.filter(i => i.tier === 'task' && isOpen(i));
  const overdue = openTasks.filter(t => t.due && days(t.due) < 0).sort((a, b) => days(a.due) - days(b.due));
  const dueToday = openTasks.filter(t => t.due && days(t.due) === 0);
  const soon = openTasks.filter(t => t.due && days(t.due) > 0 && days(t.due) <= 3);
  const stalled = openTasks.filter(t => !model.actionable(t));
  const committed = openTasks.reduce((s, t) => s + (t.due && days(t.due) <= 28 ? t.effort || 0 : 0), 0);
  const available = Math.round((WEEKLY_HOURS * 4 - openTasks.filter(t => (model.byId[t.parent] || {}).tier === 'operation').reduce((s, t) => s + (t.effort || 0), 0)) * 10) / 10;
  const queue = focusQueue(model);
  const movers = ALL_KRS.map(kr => ({ kr, st: krState(kr, model) })).sort((a, b) => b.st.planGap - a.st.planGap);

  const resolve = outcome => {
    const item = carry.find(c => c.id === resolving);
    setArchive(a => [...a, { ...item, outcome, reason: reason.trim() || 'no reason given', at: window.HF.DAILY.date }]);
    setCarry(c => c.filter(x => x.id !== resolving));
    setResolving(null); setReason('');
  };

  return (
    <div className="page">
      <div style={{ padding: 'var(--space-2) 0 var(--space-4)' }}>
        <h1 className="pt">{D.date}</h1>
        <p className="lede">Yesterday: {D.yesterday.blocks} focus blocks, {D.yesterday.logged}h logged, {D.yesterday.closed} task closed. Today has {overdue.length} thing{overdue.length === 1 ? '' : 's'} already past its date.</p>
      </div>

      <div className="todaygrid">
        <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card elev-sm">
            <div className="spread">
              <span className="h6">Past its date</span>
              <span className="wmeta">{overdue.length + ' of ' + openTasks.length + ' open'}</span>
            </div>
            <div className="tasklist">
              {overdue.length === 0 && <p className="lede" style={{ margin: 0 }}>Nothing overdue.</p>}
              {overdue.concat(dueToday).map(t => (
                <div className="taskrow" key={t.id}>
                  <span className="grow">
                    <button className="linkish" onClick={() => onSelect(t.id)}>{t.title}</button>
                    <span className="wmeta">
                      <span>{model.path(t).map(p => p.title).join(' › ') || 'unfiled'}</span><Bullet />
                      <span className={days(t.due) < 1 ? 'late' : ''}>{dueLabel(t.due)}</span>
                      {t.effort ? <><Bullet /><span>{hrs(t.effort)}</span></> : null}
                    </span>
                  </span>
                  <button className="btn btn-ghost" onClick={() => onFocus(t.id)}>Focus</button>
                </div>
              ))}
            </div>
            {soon.length > 0 && <p className="lede" style={{ margin: 0 }}>{soon.length} more inside three days. {stalled.length} open task{stalled.length === 1 ? '' : 's'} cannot be started at all: {stalled.length === 1 ? 'it is' : 'they are'} waiting on a sibling.</p>}
          </div>

          <div className="card elev-sm">
            <div className="spread"><span className="h6">Carry forward</span><span className="wmeta">{carry.length} left from the last session</span></div>
            <p className="lede" style={{ margin: 0 }}>Three exits, no fourth. Nineteen items printed every morning is not a reminder, it is wallpaper.</p>
            <div className="tasklist">
              {carry.map(c => (
                <div className="taskrow" key={c.id} style={{ display: 'block' }}>
                  <div className="spread">
                    <span className="grow"><strong>{c.title}</strong><span className="wmeta"><span>{c.heading}</span>{c.due ? <><Bullet /><span className={days(c.due) < 1 ? 'late' : ''}>{dueLabel(c.due)}</span></> : null}</span></span>
                    <button className="btn btn-ghost" onClick={() => { setResolving(r => r === c.id ? null : c.id); setReason(''); }}>{resolving === c.id ? 'Cancel' : 'Resolve'}</button>
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: 13 }}>{c.text}</p>
                  {resolving === c.id && (
                    <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
                      <input className="input" placeholder="One line on what happened to it" value={reason} onChange={e => setReason(e.target.value)} />
                      <div className="row">
                        <button className="btn btn-secondary" onClick={() => resolve('became a task')}>Make it a task</button>
                        <button className="btn btn-secondary" onClick={() => resolve('became a project')}>Make it a project</button>
                        <button className="btn btn-secondary" onClick={() => resolve('dropped')}>Drop it</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {carry.length === 0 && <p className="lede" style={{ margin: 0 }}>The list is empty. Everything on it went somewhere.</p>}
            </div>
            {archive.length > 0 && (
              <div>
                <div className="h6">Archived today</div>
                <div className="log">
                  {archive.map((a, i) => (
                    <div className="logrow" key={i}><span className="mono">✓</span><span>{a.title}<div className="wmeta">{a.outcome} — {a.reason}</div></span><span className="mono">kept on the record</span></div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card elev-sm">
            <div className="h6">First move</div>
            {queue[0] ? (
              <>
                <div className="wtitle">{queue[0].task.title}</div>
                <div className="crumb">{model.path(queue[0].task).map(p => p.title).join(' › ') || 'unfiled'}</div>
                <div className="why">{queue[0].why.slice(0, 3).map((w, i) => <div className="whyrow" key={i}>{w}</div>)}</div>
                <button className="btn btn-primary btn-block" onClick={() => onFocus(queue[0].task.id)}>Start a block on it</button>
              </>
            ) : <p className="lede" style={{ margin: 0 }}>Nothing startable.</p>}
          </div>

          <div className="card elev-sm">
            <div className="h6">Capacity</div>
            <div className="spread">
              <span style={{ fontFamily: 'var(--font-heading)', fontSize: 30, lineHeight: 1 }}>{Math.round(committed * 10) / 10}h</span>
              <span className="wmeta">{'dated against ' + available + 'h available, four weeks'}</span>
            </div>
            <p className="lede" style={{ margin: 0 }}>{committed > available
              ? 'Overcommitted by ' + (Math.round((committed - available) * 10) / 10) + 'h. Visible now rather than in the miss.'
              : 'Inside the budget, with running work already taken off the top.'}</p>
          </div>

          <div className="card elev-sm">
            <div className="spread"><span className="h6">Where the plan is thin</span><button className="btn btn-ghost" onClick={() => goTo('goals')}>Goals</button></div>
            <div className="log">
              {movers.slice(0, 3).map(({ kr, st }) => (
                <div className="logrow" key={kr.id}>
                  <span className="mono">{st.realized + '%'}</span>
                  <span>{kr.title}<div className="wmeta">{kr.goal.title}</div></span>
                  <span className={'mono ' + (st.planGap > 0 ? 'late' : '')}>{st.planGap > 0 ? st.planGap + '% unclaimed' : 'covered'}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card elev-sm">
            <div className="h6">What the board last lost</div>
            <p style={{ margin: 0, fontSize: 13 }}>{D.lost.project} was {D.lost.verdict} on {D.lost.at} — {D.lost.reason}.</p>
            <p className="lede" style={{ margin: 0 }}>A board that cannot lose an entry only grows.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Today });
