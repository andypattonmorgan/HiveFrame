const WORK_MIN = 25, BREAK_MIN = 5;
const mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

function Focus({ model, taskId, setTaskId, onSelect }) {
  const queue = focusQueue(model);
  const current = model.byId[taskId] && isOpen(model.byId[taskId]) ? model.byId[taskId] : (queue[0] && queue[0].task);
  const [mode, setMode] = React.useState('work');
  const [left, setLeft] = React.useState(WORK_MIN * 60);
  const [running, setRunning] = React.useState(false);
  const [fast, setFast] = React.useState(false);
  const [note, setNote] = React.useState('');

  React.useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem('hf.focus') || 'null');
      if (s && typeof s.left === 'number') { setLeft(s.left); setMode(s.mode || 'work'); }
    } catch (e) {}
  }, []);
  React.useEffect(() => {
    localStorage.setItem('hf.focus', JSON.stringify({ left, mode }));
  }, [left, mode]);

  React.useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setLeft(l => Math.max(0, l - (fast ? 30 : 1))), 1000);
    return () => clearInterval(id);
  }, [running, fast]);

  React.useEffect(() => {
    if (left > 0) return;
    setRunning(false);
    if (mode === 'work' && current) {
      logSession(WORK_MIN);
      setMode('break'); setLeft(BREAK_MIN * 60);
    } else if (mode === 'break') {
      setMode('work'); setLeft(WORK_MIN * 60);
    }
  }, [left]);

  const logSession = (minutes, endNote) => {
    if (!current) return;
    const at = new Date();
    model.setSessions(s => [...s, {
      id: 's' + (s.length + 1), item: current.id, minutes,
      at: `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`,
      note: endNote || note
    }]);
    setNote('');
    model.setItems(items => items.map(i => i.id === current.id && i.status === 'open' ? { ...i, status: 'doing' } : i));
  };

  const stop = () => {
    const spent = Math.round((WORK_MIN * 60 - left) / 60);
    setRunning(false);
    if (mode === 'work' && spent >= 1) logSession(spent, note || 'cut short');
    setMode('work'); setLeft(WORK_MIN * 60);
  };

  const total = (mode === 'work' ? WORK_MIN : BREAK_MIN) * 60;
  const pct = ((total - left) / total) * 100;
  const today = model.sessions;
  const doneSessions = today.reduce((s, x) => s + x.minutes / WORK_MIN, 0);
  const loggedMin = today.reduce((s, x) => s + x.minutes, 0);

  return (
    <div className="page">
      <div style={{ padding: 'var(--space-2) 0 var(--space-4)' }}>
        <h1 className="pt">Focus</h1>
        <p className="lede">One deliverable at a time, chosen by rank and shown with its reasons. Every finished block is logged against the task, which is what later corrects the estimates.</p>
      </div>
      <div className="focus">
        <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card elev-md timer">
            <div className="h6">{mode === 'work' ? 'Focus block' : 'Break'} · {mode === 'work' ? WORK_MIN : BREAK_MIN} min</div>
            <div className="ring" style={{ '--pct': pct }}>
              <div className="ringin">
                <div className="clock">{mmss(left)}</div>
                <div className="wmeta">{mode === 'work' ? (running ? 'running' : 'paused') : 'step away from it'}</div>
              </div>
            </div>
            {current ? (
              <div>
                <div className="crumb">{model.path(current).map(p => p.title).join(' › ') || 'unfiled'}</div>
                <button className="wtitle" onClick={() => onSelect(current.id)} style={{ background: 'none', border: 0, font: 'inherit', fontFamily: 'var(--font-heading)', cursor: 'pointer', color: 'inherit', padding: 0 }}>{current.title}</button>
                <div className="wmeta" style={{ justifyContent: 'center' }}>
                  {current.due && <span className={days(current.due) < 1 ? 'late' : ''}>{dueLabel(current.due)}</span>}
                  {current.effort ? <><Bullet /><span>{'estimated ' + hrs(current.effort)}</span></> : null}
                </div>
                <div className="wcard-top" style={{ justifyContent: 'center', marginTop: 6 }}>
                  {(current.krs || []).map(k => <KrPill key={k.id} {...k} />)}
                  {(current.krs || []).length === 0 && <span className="wmeta">contributes to no key result</span>}
                </div>
              </div>
            ) : <div className="wtitle">Nothing startable on the board.</div>}
            <div className="row">
              <button className="btn btn-primary" onClick={() => setRunning(r => !r)} disabled={!current}>{running ? 'Pause' : left === total ? 'Start' : 'Resume'}</button>
              <button className="btn btn-secondary" onClick={stop}>Stop and log</button>
              {mode === 'work'
                ? <button className="btn btn-secondary" onClick={() => { setMode('break'); setLeft(BREAK_MIN * 60); setRunning(false); }}>Break</button>
                : <button className="btn btn-secondary" onClick={() => { setMode('work'); setLeft(WORK_MIN * 60); setRunning(false); }}>Back to work</button>}
            </div>
            <input className="input" style={{ maxWidth: 320 }} placeholder="One line on what happened in this block" value={note} onChange={e => setNote(e.target.value)} />
            <button className="chip" aria-pressed={fast} onClick={() => setFast(f => !f)}>Run at 30× to watch a block finish</button>
          </div>

          <div className="card elev-sm">
            <div className="spread"><span className="h6">Suggested next, and why</span><span className="wmeta">{queue.length} startable</span></div>
            {queue.slice(0, 4).map(({ task, pts, why }) => (
              <div className="taskrow" key={task.id} style={{ alignItems: 'flex-start', background: task.id === (current && current.id) ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)' : undefined }}>
                <span className="mono" style={{ width: 30 }}>{Math.round(pts)}</span>
                <span className="grow">
                  <div>{task.title}</div>
                  <div className="crumb">{model.path(task).map(p => p.title).join(' › ') || 'unfiled'}</div>
                  <div className="why" style={{ marginTop: 4 }}>{why.slice(0, 3).map((w, i) => <div className="whyrow" key={i}>{w}</div>)}</div>
                </span>
                <button className="btn btn-ghost" onClick={() => { setTaskId(task.id); setMode('work'); setLeft(WORK_MIN * 60); setRunning(false); }}>Swap in</button>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
          <div className="card elev-sm">
            <div className="h6">Today’s target</div>
            <div className="spread">
              <div style={{ fontFamily: 'var(--font-heading)', fontSize: 34, lineHeight: 1 }}>
                {Math.floor(doneSessions * 10) / 10} <span style={{ fontSize: 16 }}>of {DAILY_TARGET_SESSIONS} blocks</span>
              </div>
              <span className="wmeta">{Math.round(loggedMin / 6) / 10 + 'h logged'}</span>
            </div>
            <div className="pips">
              {Array.from({ length: DAILY_TARGET_SESSIONS }).map((_, i) => (
                <div className="pip" key={i} data-on={i < Math.floor(doneSessions)} data-partial={i === Math.floor(doneSessions) && doneSessions % 1 > 0.1} />
              ))}
            </div>
            <p className="lede" style={{ margin: 0 }}>{WEEKLY_HOURS}h a week is the standing budget. Six blocks is what a day of it looks like.</p>
          </div>

          <div className="card elev-sm">
            <div className="h6">Session log</div>
            <div className="log">
              {today.map(s => {
                const t = model.byId[s.item];
                return (
                  <div className="logrow" key={s.id}>
                    <span className="mono">{s.at}</span>
                    <span>
                      {t ? t.title : s.item}
                      {s.note && <div className="wmeta">{s.note}</div>}
                    </span>
                    <span className="mono">{s.minutes}m</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card elev-sm">
            <div className="h6">Estimate against logged</div>
            <div className="log">
              {Object.entries(today.reduce((acc, s) => { acc[s.item] = (acc[s.item] || 0) + s.minutes; return acc; }, {})).map(([id, min]) => {
                const t = model.byId[id];
                if (!t) return null;
                const est = (t.effort || 0) * 60;
                const over = est ? Math.round(((min - est) / est) * 100) : null;
                return (
                  <div className="logrow" key={id}>
                    <span className="mono">{Math.round(min / 6) / 10}h</span>
                    <span>{t.title}<div className="wmeta">{'estimated ' + hrs(t.effort || 0)}</div></span>
                    <span className={'mono ' + (over !== null && over > 0 ? 'late' : '')}>{over === null ? '—' : (over > 0 ? '+' : '') + over + '%'}</span>
                  </div>
                );
              })}
            </div>
            <p className="lede" style={{ margin: 0 }}>Logged time is the only thing that corrects an estimate. Until a task has blocks against it, its number is a guess.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Focus });
