function Goals({ model, highlight, onSelect }) {
  return (
    <div className="page">
      <div style={{ padding: 'var(--space-2) 0 0' }}>
        <h1 className="pt">Goals and key results</h1>
        <p className="lede">The number is what has actually moved. The bar underneath is the plan: work already closed against this result, work in flight, and the share of it nothing on the board is claiming.</p>
        <div className="legend" style={{ marginBottom: 'var(--space-6)' }}>
          <span><span className="swatch" style={{ background: 'var(--color-accent)' }} />closed work</span>
          <span><span className="swatch" style={{ background: 'repeating-linear-gradient(115deg,var(--color-accent-2) 0 4px,transparent 4px 8px)' }} />in flight</span>
          <span><span className="swatch" style={{ background: 'repeating-linear-gradient(115deg,color-mix(in srgb,var(--color-text) 30%,transparent) 0 2px,transparent 2px 6px)' }} />unclaimed</span>
        </div>
      </div>
      <div className="goalgrid">
        {GOALS.map(g => (
          <section key={g.id} style={{ marginTop: 'var(--space-2)' }}>
            <h3 style={{ marginBottom: 2 }}>{g.title}</h3>
            <p className="lede" style={{ marginBottom: 'var(--space-3)' }}>{g.note}</p>
            <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
              {g.krs.map(kr => <KrRow key={kr.id} kr={kr} model={model} highlight={highlight === kr.id} onSelect={onSelect} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function KrRow({ kr, model, highlight, onSelect }) {
  const st = krState(kr, model);
  const [open, setOpen] = React.useState(highlight);
  React.useEffect(() => { if (highlight) setOpen(true); }, [highlight]);
  const value = kr.lowerIsBetter
    ? `${kr.current} → ${kr.target} ${kr.unit}`
    : `${kr.current} of ${kr.target} ${kr.unit}`;
  return (
    <div className="card elev-sm" style={{ gap: 'var(--space-3)', outline: highlight ? '2px solid var(--color-accent)' : 'none', outlineOffset: 3 }}>
      <div className="spread">
        <div>
          <div className="wtitle">{kr.title}</div>
          <div className="wmeta">{value}{kr.lowerIsBetter ? <> <Bullet /> <span>lower is better, from {kr.start}</span></> : null}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 26, lineHeight: 1 }}>{st.realized}%</div>
          <div className="wmeta" style={{ justifyContent: 'flex-end' }}>delivered</div>
        </div>
      </div>
      <KrBar state={st} />
      <div className="spread">
        <span className="wmeta">
          <span>{st.planOpen + '% in flight across ' + st.openC.length + (st.openC.length === 1 ? ' open item' : ' open items')}</span>
          <Bullet />
          <span className={st.planGap > 0 ? 'late' : ''}>{st.planGap > 0 ? st.planGap + '% of the plan is unclaimed' : 'fully covered'}</span>
        </span>
        <button className="btn btn-ghost" onClick={() => setOpen(o => !o)}>{open ? 'Hide contributions' : 'Contributions'}</button>
      </div>
      {open && (
        <div className="tasklist">
          {st.contributors.length === 0 && <p className="lede" style={{ margin: 0 }}>No task anywhere on the board is declared against this result.</p>}
          {st.contributors.map(c => (
            <button className="taskrow" key={c.id} onClick={() => onSelect(c.id)} data-done={!isOpen(c)} style={{ textAlign: 'left', border: 0, cursor: 'pointer', font: 'inherit', fontSize: 13 }}>
              <span className="grow">
                {c.title}
                <span className="wmeta">
                  <span>{(model.path(c).map(p => p.title).join(' › ')) || 'unfiled'}</span>
                  <Bullet />
                  <span>{PHASES[PHASE_IX[c.phase]].label}</span>
                  {c.effort ? <><Bullet /><span>{hrs(c.effort)}</span></> : null}
                </span>
              </span>
              <span className="mono">{st.weightOf(c)}%{isOpen(c) ? '' : ' ✓'}</span>
            </button>
          ))}
          {st.declared > 100 && <p className="lede" style={{ margin: 0 }}>Declared weight totals {st.declared}%. Two tasks are claiming the same ground; one of them is not needed.</p>}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Goals, KrRow });
