/* Shared model helpers and small components.
   Scoring and phrasing follow hiveframe/model.py: a rank always carries its reasons. */
const { PHASES, GOALS, ITEMS, SESSIONS, TODAY, WEEKLY_HOURS, DAILY_TARGET_SESSIONS } = window.HF;
const PHASE_IX = Object.fromEntries(PHASES.map((p, i) => [p.id, i]));
const ALL_KRS = GOALS.flatMap(g => g.krs.map(k => ({ ...k, goal: g })));
const KR_BY_ID = Object.fromEntries(ALL_KRS.map(k => [k.id, k]));
const LIVE = s => s === 'active' || s === 'blocked';
const isOpen = t => t.status !== 'done' && t.status !== 'dropped';

function useModel() {
  const [items, setItems] = React.useState(ITEMS);
  const [sessions, setSessions] = React.useState(SESSIONS);
  const api = React.useMemo(() => {
    const byId = Object.fromEntries(items.map(i => [i.id, i]));
    const childrenOf = id => items.filter(i => i.parent === id);
    const tasksOf = id => items.filter(i => i.tier === 'task' && i.parent === id);
    const openTasksOf = id => tasksOf(id).filter(isOpen);
    const actionable = t => {
      const openIds = new Set(items.filter(i => i.tier === 'task' && isOpen(i)).map(i => i.id));
      return isOpen(t) && !(t.blocked_by || []).some(d => openIds.has(d));
    };
    const path = item => {
      const out = [];
      let cur = item.parent ? byId[item.parent] : null;
      while (cur) { out.unshift(cur); cur = cur.parent ? byId[cur.parent] : null; }
      return out;
    };
    return { byId, childrenOf, tasksOf, openTasksOf, actionable, path };
  }, [items]);
  return { items, setItems, sessions, setSessions, ...api };
}

const days = due => due ? Math.round((new Date(due + 'T00:00') - new Date(TODAY + 'T00:00')) / 86400000) : null;
function dueLabel(due) {
  const d = days(due);
  if (d === null) return null;
  if (d < 0) return `${Math.abs(d)} day${Math.abs(d) === 1 ? '' : 's'} past its date`;
  if (d === 0) return 'due today';
  return `due in ${d} day${d === 1 ? '' : 's'}`;
}
const hrs = h => (h % 1 === 0 ? h : h.toFixed(2).replace(/0$/, '')) + 'h';

/* Rank a task, and say why. Mirrors model.score(): a priority with no visible
   reason is an instruction; with a reason it is an argument that can be rejected. */
function rankTask(task, model) {
  const why = [];
  let pts = 0;
  const parent = task.parent ? model.byId[task.parent] : null;
  if (!isOpen(task)) return { pts: 0, why: ['already closed'] };
  if (!model.actionable(task)) return { pts: -100, why: ['waiting on an open sibling'] };
  const d = days(task.due);
  if (d !== null) {
    if (d < 0) { pts += 40 + Math.min(Math.abs(d), 10); why.push(dueLabel(task.due)); }
    else if (d <= 7) { pts += 30 - d; why.push(dueLabel(task.due)); }
    else if (d <= 28) { pts += 8; why.push(dueLabel(task.due)); }
  }
  if (task.urgent) { pts += 20; why.push('flagged urgent'); }
  if (task.important) { pts += 10; why.push('flagged important'); }
  if (d !== null && d <= 2) {
    if (task.effort && task.effort <= 0.5) { pts += 6; why.push(`short, ${hrs(task.effort)} — it will get finished`); }
    else if (task.effort >= 4) { pts -= 4; why.push(`needs ${hrs(task.effort)}, too big for one sitting`); }
  }
  const w = (task.krs || []).reduce((s, k) => s + k.weight, 0);
  if (w) {
    pts += Math.min(w / 4, 12);
    const names = (task.krs || []).map(k => KR_BY_ID[k.id]).filter(Boolean);
    why.push(`carries ${w}% of ${names.length > 1 ? names.length + ' key results' : 'a key result'}`);
  } else {
    why.push('contributes to no key result');
  }
  if (parent && parent.status === 'blocked') { pts += 25; why.push('a move that attacks a blockage'); }
  if (parent && parent.tier === 'operation') { pts -= 8; why.push('running work, not a deliverable'); }
  return { pts, why };
}

function focusQueue(model) {
  return model.items.filter(i => i.tier === 'task' && isOpen(i))
    .map(t => ({ task: t, ...rankTask(t, model) }))
    .filter(r => r.pts > -50)
    .sort((a, b) => b.pts - a.pts);
}

/* KR arithmetic. realized comes from the measured value; planned is the declared
   weight of open work behind it; anything left is a share of the result with
   nothing behind it, which is the number worth seeing. */
function krState(kr, model) {
  const base = kr.lowerIsBetter ? (kr.start ?? kr.current) : 0;
  const span = kr.lowerIsBetter ? base - kr.target : kr.target;
  const moved = kr.lowerIsBetter ? base - kr.current : kr.current;
  const realized = Math.max(0, Math.min(100, Math.round((moved / span) * 100)));
  const contributors = model.items.filter(i => (i.krs || []).some(k => k.id === kr.id));
  const weightOf = i => (i.krs.find(k => k.id === kr.id) || {}).weight || 0;
  const openC = contributors.filter(isOpen);
  const doneC = contributors.filter(i => !isOpen(i));
  const planDone = doneC.reduce((s, i) => s + weightOf(i), 0);
  const planOpen = openC.reduce((s, i) => s + weightOf(i), 0);
  const planGap = Math.max(0, 100 - planDone - planOpen);
  return {
    realized, planDone: Math.min(100, planDone), planOpen: Math.min(100 - Math.min(100, planDone), planOpen), planGap,
    contributors: contributors.sort((a, b) => weightOf(b) - weightOf(a)),
    openC, doneC, weightOf,
    declared: contributors.reduce((s, i) => s + weightOf(i), 0)
  };
}

const TIER_TAG = { program: 'tag-accent', project: 'tag-accent-2', task: 'tag-neutral', operation: 'tag-neutral' };
const Tag = ({ kind = 'tag-neutral', children }) => <span className={'tag ' + kind}>{children}</span>;
const Bullet = () => <span className="dot" />;

function KrPill({ id, weight }) {
  const kr = KR_BY_ID[id];
  if (!kr) return null;
  const label = kr.title.length > 30 ? kr.title.slice(0, 28) + '…' : kr.title;
  return <span className="krpill" title={kr.title}>{weight + '% · ' + label}</span>;
}

function KrBar({ state }) {
  return (
    <div className="krbar" title="plan coverage: closed work, work in flight, and the share nothing is claiming">
      <div className="krfill" style={{ width: state.planDone + '%' }} />
      <div className="krplan" style={{ left: state.planDone + '%', width: state.planOpen + '%' }} />
      <div className="krgap" style={{ width: state.planGap + '%' }} />
    </div>
  );
}

Object.assign(window, {
  PHASES, PHASE_IX, GOALS, ALL_KRS, KR_BY_ID, TODAY, WEEKLY_HOURS, DAILY_TARGET_SESSIONS,
  LIVE, isOpen, useModel, days, dueLabel, hrs, rankTask, focusQueue, krState,
  TIER_TAG, Tag, Bullet, KrPill, KrBar
});
