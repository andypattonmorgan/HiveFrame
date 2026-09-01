const CANNED = [
  { steps: [{ glyph: '●', title: 'Read the project file', detail: 'only the directories this project named' }, { glyph: '●', title: 'Ranked its open tasks', detail: 'startable today, prerequisites cleared' }],
    text: 'Answered from this project’s files only. The thread for another project holds its own history, so nothing from it is in this answer.' },
  { steps: [{ glyph: '●', title: 'Read decisions.jsonl', detail: '4 verdicts since the 4th' }, { glyph: '✗', title: 'shell(git push) refused', detail: 'denied tool — nothing is published from here' }],
    text: 'The record is local and append-only. I can read it and write beside it; I cannot publish it anywhere, and no system of record is reachable from this thread.' }
];

function Chat({ model }) {
  const threads = [{ id: 'brief', label: 'Connector-fed brief' }, { id: 'graph', label: 'Relation graph' }, { id: 'board', label: 'Whole board' }];
  const [tid, setTid] = React.useState('brief');
  const [msgs, setMsgs] = React.useState(window.HF.THREADS);
  const [draft, setDraft] = React.useState('');
  const [ctx, setCtx] = React.useState(true);
  const [model_, setModel_] = React.useState('gpt-5.4-mini');
  const [archived, setArchived] = React.useState(null);
  const thread = msgs[tid] || [];
  const project = model.byId[tid];
  const turns = thread.filter(m => m.role === 'assistant');
  const spend = turns.reduce((s, m) => s + (m.credits || 0), 0);
  const bodyRef = React.useRef(null);
  React.useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; }, [thread.length, tid]);

  const send = () => {
    if (!draft.trim()) return;
    const now = new Date();
    const at = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const reply = CANNED[thread.length % CANNED.length];
    setMsgs(m => ({ ...m, [tid]: [...(m[tid] || []),
      { role: 'user', at, text: draft.trim(), context: ctx },
      { role: 'assistant', at, model: model_, seconds: 9.6, credits: 0.019, ...reply }] }));
    setDraft('');
  };

  return (
    <div className="page chatpage">
      <div style={{ padding: 'var(--space-2) 0 var(--space-4)' }}>
        <h1 className="pt">Chat</h1>
        <p className="lede">One thread per project. Switching project switches thread, so a question about one is never answered out of another’s history. Tools are broad; reach is narrow.</p>
      </div>
      <div className="chatview">
        <div className="railcol">
          <div className="h6">Threads</div>
          {threads.map(t => (
            <button key={t.id} className="railrow" aria-pressed={t.id === tid} onClick={() => setTid(t.id)}>
              <span className="grow">{t.label}<span className="wmeta">{(() => { const n = (msgs[t.id] || []).filter(m => m.role === 'assistant').length; return n ? n + (n === 1 ? ' turn' : ' turns') : 'no history yet'; })()}</span></span>
            </button>
          ))}
          <div className="h6" style={{ marginTop: 'var(--space-4)' }}>Reach</div>
          <div className="tree">
            {window.HF.GRANTED_DIRS.map(d => <div key={d} className="path">{d}</div>)}
          </div>
          <p className="lede" style={{ margin: '6px 0 0' }}>Named directories only. The shared reference libraries are not among them.</p>
          <div className="h6" style={{ marginTop: 'var(--space-4)' }}>Denied</div>
          <div className="wcard-top">{window.HF.DENIED_TOOLS.map(d => <Tag key={d} kind="tag-outline">{d}</Tag>)}</div>
          <p className="lede" style={{ margin: '6px 0 0' }}>Nothing leaves the machine and nothing is published from here.</p>
        </div>

        <div className="chatmain">
          <div className="spread">
            <div>
              <div className="wtitle">{project ? project.title : 'Whole board'}</div>
              <div className="wmeta">
                <span>{window.HF.STORE.name} store</span><Bullet />
                <span>{turns.length + (turns.length === 1 ? ' turn' : ' turns')}</span><Bullet />
                <span>{spend.toFixed(3)} credits this thread</span>
              </div>
            </div>
            <div className="row">
              <select className="input" style={{ width: 'auto' }} value={model_} onChange={e => setModel_(e.target.value)}>
                {window.HF.MODELS.map(m => <option key={m.id} value={m.id}>{m.id} · {m.tier} · ×{m.rel}</option>)}
              </select>
              <button className="btn btn-secondary" onClick={() => { setArchived(`transcript.${tid}.${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.jsonl`); setMsgs(m => ({ ...m, [tid]: [] })); }}>New thread</button>
            </div>
          </div>
          {archived && <p className="lede" style={{ margin: 0 }}>Previous thread archived to {archived}. The session is forgotten here, not deleted, so it is still resumable from the terminal.</p>}

          <div className="chatbody" ref={bodyRef}>
            {thread.length === 0 && <p className="lede">Empty thread. It carries no history from any other project.</p>}
            {thread.map((m, i) => m.role === 'user' ? (
              <div className="msg msg-user" key={i}>
                {m.context && <div className="crumb">[screen, not typed] board state was sent with this</div>}
                <div>{m.text}</div>
                <div className="wmeta">{m.at}</div>
              </div>
            ) : (
              <div className="msg msg-a" key={i}>
                {m.steps && m.steps.length > 0 && (
                  <div className="steplist">
                    {m.steps.map((s, j) => (
                      <div className="steprow" key={j}>
                        <span className={'glyph' + (s.glyph === '✗' ? ' late' : '')}>{s.glyph}</span>
                        <span className="grow">{s.title}{s.detail && <div className="path">{s.detail}</div>}</span>
                      </div>
                    ))}
                  </div>
                )}
                {m.text.split('\n\n').map((p, j) => <p key={j} style={{ margin: j ? 'var(--space-2) 0 0' : 0, fontSize: 14 }}>{p}</p>)}
                <div className="wmeta">
                  <span>{m.model}</span><Bullet /><span>{m.seconds}s</span><Bullet />
                  <span>{m.credits} credits, measured as the difference between readings</span>
                </div>
              </div>
            ))}
          </div>

          <div className="composer">
            <textarea className="input" placeholder={'Ask about ' + (project ? project.title : 'the board')} value={draft}
              onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); }} />
            <div className="spread">
              <button className="chip" aria-pressed={ctx} onClick={() => setCtx(c => !c)}>Send what is on screen</button>
              <button className="btn btn-primary" onClick={send} disabled={!draft.trim()}>Ask</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Chat });
