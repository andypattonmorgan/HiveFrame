const LOOKS = [
  { id: 'warm', label: 'Cream ground', color: '#f5ead8' },
  { id: 'sand', label: 'Sand ground', color: '#ebddc5' },
  { id: 'ink', label: 'Ink ground', color: '#2e2b25' }
];

function App() {
  const model = useModel();
  const [view, setView] = React.useState('today');
  const [fileProject, setFileProject] = React.useState('brief');
  const [selected, setSelected] = React.useState(null);
  const [filter, setFilter] = React.useState({ program: 'all', tasks: false, done: false });
  const [focusTask, setFocusTask] = React.useState('t-charter-1');
  const [krHighlight, setKrHighlight] = React.useState(null);
  const [look, setLook] = React.useState('warm');
  React.useEffect(() => { document.body.dataset.look = look; }, [look]);

  const committed = model.items.reduce((s, i) => s + (i.tier === 'task' && isOpen(i) && i.due && days(i.due) <= 28 ? i.effort || 0 : 0), 0);
  const openTaskCount = model.items.filter(i => i.tier === 'task' && isOpen(i)).length;

  const openItem = id => { setSelected(id); setView('board'); };
  const openKr = id => { setKrHighlight(id); setView('goals'); };

  return (
    <div className="shell">
      <nav className="nav">
        <span className="nav-brand">HiveFrame</span>
        <div className="navlinks">
          {[['today', 'Today'], ['board', 'Board'], ['goals', 'Goals'], ['focus', 'Focus'], ['files', 'Files'], ['chat', 'Chat']].map(([id, label]) => (
            <button key={id} className="navlink" aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}>{label}</button>
          ))}
        </div>
        <div className="navmeta">
          <span>{openTaskCount} open tasks</span>
          <span>{Math.round(committed * 10) / 10}h dated in the next four weeks of a {WEEKLY_HOURS}h week</span>
          <div className="look" role="group" aria-label="Ground">
            {LOOKS.map(l => (
              <button key={l.id} className="lookdot" style={{ background: l.color }} aria-pressed={look === l.id} title={l.label} onClick={() => setLook(l.id)} />
            ))}
          </div>
        </div>
      </nav>
      <div className="main">
        {view === 'today' && <Today model={model} onFocus={id => { setFocusTask(id); setView('focus'); }} onSelect={openItem} goTo={setView} />}
        {view === 'files' && <Files model={model} projectId={fileProject} setProjectId={setFileProject} />}
        {view === 'chat' && <Chat model={model} />}
        {view === 'board' && <Board model={model} filter={filter} setFilter={setFilter} selected={selected} onSelect={id => setSelected(s => s === id ? null : id)} />}
        {view === 'goals' && <Goals model={model} highlight={krHighlight} onSelect={openItem} />}
        {view === 'focus' && <Focus model={model} taskId={focusTask} setTaskId={setFocusTask} onSelect={openItem} />}
        {view === 'board' && selected && (
          <Drawer id={selected} model={model} onClose={() => setSelected(null)}
            onFocus={id => { setFocusTask(id); setView('focus'); }} onGoal={openKr} />
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
