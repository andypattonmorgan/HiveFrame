const HFX = window.HF;

function Files({ model, projectId, setProjectId }) {
  const projects = model.items.filter(i => (i.tier === 'project' || i.tier === 'program') && HFX.FOLDERS[i.id]);
  const pid = HFX.FOLDERS[projectId] ? projectId : projects[0].id;
  const project = model.byId[pid];
  const folders = HFX.FOLDERS[pid] || [];
  const files = HFX.FILES.filter(f => f.project === pid);
  const [bodies, setBodies] = React.useState({});
  const [openId, setOpenId] = React.useState(files[0] && files[0].id);
  const [receipt, setReceipt] = React.useState(null);
  React.useEffect(() => { setOpenId(files[0] && files[0].id); setReceipt(null); }, [pid]);
  const file = files.find(f => f.id === openId) || files[0];
  const body = file ? (bodies[file.id] ?? file.body) : '';
  const dirty = file && body !== file.body;

  const save = () => {
    const before = file.body.split('\n'), after = body.split('\n');
    const statusOnly = before.length === after.length &&
      before.every((l, i) => l === after[i] || (l.startsWith('status =') && after[i].startsWith('status =')));
    setReceipt(statusOnly
      ? { kind: 'status', text: `One status line rewritten in ${file.name}. The write refuses itself if it cannot find exactly one match, so nothing else in the file can move.` }
      : { kind: 'structural', text: `${file.name} regenerated from the model. ${file.name}.bak written first. Hand-written TOML comments do not survive a structural edit — keep notes in a task note or a charter field, where they are data.` });
    file.body = body;
  };

  return (
    <div className="page filespage">
      <div style={{ padding: 'var(--space-2) 0 var(--space-4)' }}>
        <h1 className="pt">Files</h1>
        <p className="lede">Only the directories a project has named. A tree that lists the whole store is the same context bleed the charter exists to stop.</p>
      </div>
      <div className="filesview">
        <div className="railcol">
          <div className="h6">Projects with folders</div>
          {projects.map(p => (
            <button key={p.id} className="railrow" aria-pressed={p.id === pid} onClick={() => setProjectId(p.id)}>
              <span className="grow">{p.title}</span>
              <span className="mono">{(HFX.FILES.filter(f => f.project === p.id)).length}</span>
            </button>
          ))}
          <div className="h6" style={{ marginTop: 'var(--space-4)' }}>Store</div>
          <p className="lede" style={{ margin: 0 }}>{HFX.STORE.name} · {HFX.STORE.classification}<br />{HFX.STORE.root}</p>
        </div>

        <div className="railcol">
          {folders.map((fo, ix) => (
            <div key={fo.path} style={{ marginBottom: 'var(--space-3)' }}>
              <div className="h6">{fo.label}</div>
              <div className="path" style={{ marginBottom: 6 }}>{fo.path}</div>
              <div className="tree">
                {files.filter(f => f.folder === ix).map(f => (
                  <button key={f.id} className="railrow" aria-pressed={f.id === (file && file.id)} onClick={() => { setOpenId(f.id); setReceipt(null); }}>
                    <span className="grow">
                      {f.name}
                      <span className="wmeta">
                        {f.missing ? <span className="late">the path does not exist</span> : <span>{f.bytes >= 1000 ? (f.bytes / 1000).toFixed(1) + ' kB' : f.bytes + ' B'}</span>}
                        {f.contract && <><Bullet /><span>the contract</span></>}
                        {f.appendOnly && <><Bullet /><span>append only</span></>}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="editorcol">
          {file && (
            <>
              <div className="spread">
                <div>
                  <div className="wtitle">{file.name}</div>
                  <div className="path">{project.title + ' · ' + ((folders[file.folder] || {}).path || '')}</div>
                </div>
                <div className="row">
                  <button className="btn btn-secondary" onClick={() => setReceipt({ kind: 'reveal', text: 'Finder opened at the path. HiveFrame reveals a location, it never launches the file.' })}>Reveal</button>
                  {file.editable && <button className="btn btn-primary" disabled={!dirty} onClick={save}>Save</button>}
                </div>
              </div>
              {file.missing ? (
                <div className="card" style={{ gap: 6 }}>
                  <div className="wtitle">Declared, but not there</div>
                  <p className="lede" style={{ margin: 0 }}>The artifact is listed in the project file and the path does not resolve. Nothing is repaired silently: either the file moved, or the artifact should be dropped with a reason.</p>
                </div>
              ) : (
                <textarea className="input editor" spellCheck="false" readOnly={!file.editable}
                  value={body} onChange={e => setBodies(b => ({ ...b, [file.id]: e.target.value }))} />
              )}
              <div className="wmeta">
                {file.editable ? <span>editable · every save keeps a .bak</span> : <span>read only{file.appendOnly ? ' · appended to by verdicts, never rewritten' : ''}</span>}
                {dirty && <><Bullet /><span className="late">unsaved</span></>}
              </div>
              {receipt && (
                <div className="card" style={{ background: 'color-mix(in srgb, var(--color-accent-2) 16%, transparent)', gap: 4 }}>
                  <div className="h6">{receipt.kind === 'status' ? 'One line rewritten' : receipt.kind === 'structural' ? 'File regenerated' : 'Revealed'}</div>
                  <p style={{ margin: 0, fontSize: 13 }}>{receipt.text}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Files });
