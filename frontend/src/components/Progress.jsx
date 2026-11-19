import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { inputClass, errorMessage, quietButtonClass } from './Modal';
import { money, toDateInput } from '../colors';

// Shared by the Progress and Tour wrap-up cards, so the dashboard asks once.
let pending = null;
const fetchProgress = (fresh = false) => {
  if (fresh || !pending) pending = axios.get('/api/progress', { params: { day: toDateInput(new Date()) } }).then(({ data }) => data).catch(() => ({ enabled: false }));
  return pending;
};

function useProgress() {
  const [data, setData] = useState(null);
  const load = useCallback((fresh) => { fetchProgress(fresh).then(setData); }, []);
  useEffect(() => { load(false); }, [load]);
  return [data, () => load(true)];
}

/** A ring that fills as a weekly goal is met. */
function Ring({ done, target, label }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const part = Math.min(done / target, 1);
  return (
    <div className="flex flex-col items-center w-20 text-center">
      <svg viewBox="0 0 56 56" className="w-14 h-14" role="img" aria-label={`${label}: ${done} of ${target}`}>
        <circle cx="28" cy="28" r={r} fill="none" stroke="currentColor" strokeWidth="6" className="text-gray-100" />
        <circle cx="28" cy="28" r={r} fill="none" stroke="currentColor" strokeWidth="6" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - part)} transform="rotate(-90 28 28)"
          className={part >= 1 ? 'text-emerald-500' : 'text-sworkr-500'} />
        <text x="28" y="32" textAnchor="middle" className="fill-gray-700" style={{ fontSize: 13, fontWeight: 600 }}>{done}/{target}</text>
      </svg>
      <span className="text-[11px] leading-tight text-gray-600 mt-1">{label}</span>
    </div>
  );
}

const WALLET_LEVELS = ['Getting started', '1 month covered', '3 months covered', '6 months covered'];

/** Everything else: bests, badges, choosing weekly goals, and the off switch. */
function ProgressMore({ data, onClose, onChanged }) {
  const [kind, setKind] = useState(Object.keys(data.goal_kinds)[0]);
  const [target, setTarget] = useState('3');
  const [error, setError] = useState('');
  const addGoal = async (e) => {
    e.preventDefault();
    try {
      await axios.post('/api/progress/goals', { kind, target: Number(target) });
      onChanged();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  const removeGoal = async (k) => { await axios.delete(`/api/progress/goals/${k}`).catch(() => {}); onChanged(); };
  const turnOff = async () => {
    if (!window.confirm('Turn off streaks, goals, bests and badges? You can turn them back on in Settings → Look.')) return;
    await axios.put('/api/progress/settings', { enabled: false }).catch(() => {});
    onClose();
    onChanged();
  };
  return (
    <Modal title="Progress" onClose={onClose} wide>
      <div className="space-y-5">
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">Your weekly goals</h3>
          <p className="text-xs text-gray-500 mb-2">Only the ones you choose. Counted Monday to Sunday.</p>
          <ul className="text-sm divide-y divide-gray-100 mb-2">
            {data.goals.map((g) => (
              <li key={g.kind} className="py-1.5 flex items-center gap-2">
                <span className="flex-1 text-gray-800">{g.label}: {g.target} a week</span>
                <button type="button" onClick={() => removeGoal(g.kind)} className="text-xs text-gray-400 hover:text-red-600">Remove</button>
              </li>
            ))}
          </ul>
          <form onSubmit={addGoal} className="flex flex-wrap gap-2">
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Goal" className={`${inputClass} !w-auto`}>
              {Object.entries(data.goal_kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <input type="number" min="1" max="100" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="How many a week" className={`${inputClass} !w-20`} />
            <button type="submit" className={quietButtonClass}>Set goal</button>
          </form>
          {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
        </section>
        {data.bests.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-gray-700 mb-1">Personal bests</h3>
            <ul className="grid sm:grid-cols-2 gap-2">
              {data.bests.map((b) => (
                <li key={b.title} className="rounded-lg border border-gray-100 px-3 py-2">
                  <span className="block text-xs text-gray-500">{b.title}</span>
                  <span className="block text-lg font-semibold text-gray-800">{b.money ? money(b.value) : b.value}</span>
                  <span className="block text-xs text-gray-500">{b.when}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">Badges</h3>
          <ul className="grid sm:grid-cols-2 gap-2">
            {data.badges.map((b) => (
              <li key={b.id} className={`rounded-lg border px-3 py-2 ${b.earned ? 'border-emerald-200 bg-emerald-50' : 'border-gray-100'}`}>
                <span className={`block text-sm font-medium ${b.earned ? 'text-emerald-800' : 'text-gray-500'}`}>{b.earned ? '★ ' : '☆ '}{b.title}</span>
                {!b.earned && <span className="block text-xs text-gray-500">{b.how}</span>}
              </li>
            ))}
          </ul>
        </section>
        <p className="text-xs text-gray-500">
          All of this stays on your computer, is never shown to anyone, and never suggests working more.{' '}
          <button type="button" onClick={turnOff} className="underline hover:text-red-600">Turn it all off</button>
        </p>
      </div>
    </Modal>
  );
}

/** Dashboard card: streaks, weekly goals, wallet level. */
export function ProgressCard() {
  const [data, reload] = useProgress();
  const [more, setMore] = useState(false);
  if (!data || !data.enabled) return null;
  const earned = data.badges.filter((b) => b.earned).length;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-gray-800">Progress</h2>
        <button onClick={() => setMore(true)} className="text-sm text-sworkr-600 hover:text-sworkr-800">More →</button>
      </div>
      <ul className="flex flex-wrap gap-2">
        {data.streaks.map((s) => (
          <li key={s.id} className={`text-xs rounded-full px-3 py-1 ${s.days ? 'bg-amber-50 text-amber-800' : 'bg-gray-50 text-gray-500'}`} title={s.title}>
            {s.days ? '🔥' : '·'} {s.title}: <b>{s.days}</b> day{s.days === 1 ? '' : 's'}{s.paused && ' (paused)'}
          </li>
        ))}
      </ul>
      {data.goals.length > 0 ? (
        <div className="flex flex-wrap gap-3">{data.goals.map((g) => <Ring key={g.kind} done={g.done} target={g.target} label={g.label} />)}</div>
      ) : (
        <p className="text-xs text-gray-500">Set a weekly goal of your own under More (like 3 posts, or logging money 5 days).</p>
      )}
      {data.wallet && (
        <div>
          <p className="text-xs text-gray-500">Wallet: {WALLET_LEVELS[data.wallet.level]} ({data.wallet.months} months of costs){data.wallet.next ? ` · next: ${data.wallet.next} months` : ' ✓'}</p>
          <div className="mt-1 h-2 rounded-full bg-gray-100 overflow-hidden">
            <div className="h-full bg-emerald-500" style={{ width: `${Math.min(data.wallet.months / 6, 1) * 100}%` }} />
          </div>
        </div>
      )}
      <p className="text-xs text-gray-500">Badges: {earned} of {data.badges.length}</p>
      {more && <ProgressMore data={data} onClose={() => setMore(false)} onChanged={reload} />}
    </div>
  );
}

/** Dashboard card: the highlights of a tour that just ended (two weeks after). */
export function TourWrapUp() {
  const [data] = useProgress();
  const w = data?.enabled && data.tour_wrapup;
  if (!w) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <h2 className="font-semibold text-gray-800 mb-2">✈ {w.name}: wrapped up</h2>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-gray-500">Came in</dt><dd className="text-gray-800 tabular-nums">{money(w.income)}</dd>
        <dt className="text-gray-500">Costs</dt><dd className="text-gray-800 tabular-nums">{money(w.expenses)}</dd>
        <dt className="text-gray-500">Kept</dt><dd className="font-semibold text-gray-800 tabular-nums">{money(w.profit)}</dd>
        {w.profit_per_day != null && <><dt className="text-gray-500">Per working day</dt><dd className="text-gray-800 tabular-nums">{money(w.profit_per_day)}</dd></>}
        {w.best_day && <><dt className="text-gray-500">Best day</dt><dd className="text-gray-800">{w.best_day.day} · {money(w.best_day.earned)}</dd></>}
        <dt className="text-gray-500">New clients</dt><dd className="text-gray-800">{w.new_clients}</dd>
      </dl>
    </div>
  );
}

/** Settings > Look: Progress on or off. */
export function ProgressSettings() {
  const [on, setOn] = useState(null);
  useEffect(() => { axios.get('/api/progress').then(({ data }) => setOn(data.enabled)).catch(() => setOn(false)); }, []);
  if (on === null) return null;
  const toggle = async (e) => {
    const { data } = await axios.put('/api/progress/settings', { enabled: e.target.checked });
    setOn(data.enabled);
    fetchProgress(true);
  };
  return (
    <label className="flex items-center gap-2 text-sm text-gray-700">
      <input type="checkbox" checked={on} onChange={toggle} /> Streaks, weekly goals, personal bests and badges
    </label>
  );
}
