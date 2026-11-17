import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { inputClass, errorMessage, buttonClass } from './Modal';
import { dayLabel, money } from '../colors';

// Until the person's own kinds have loaded, the three everyone starts with.
const STARTERS = { weekly: 'Weekly test', monthly: 'Monthly test', yearly: 'Yearly test' };
let cache = null;
const listeners = new Set();
const fetchKinds = () => axios.get('/api/test-kinds').then(({ data }) => {
  cache = data;
  listeners.forEach((fn) => fn(data));
  return data;
}).catch(() => []);
/** Forget the kinds (after logging out, so the next person doesn't see them). */
export const clearTestKindCache = () => { cache = null; };

/**
 * The person's kinds of health test. `labels` names every kind, hidden ones too (for history);
 * `options` is only the ones in use (for choosing), plus `keep` if that's a hidden one already chosen.
 */
export function useTestKinds(keep) {
  const [kinds, setKinds] = useState(cache);
  useEffect(() => {
    listeners.add(setKinds);
    if (!cache) fetchKinds();
    return () => { listeners.delete(setKinds); };
  }, []);
  const list = kinds || [];
  const labels = kinds ? Object.fromEntries(list.map((k) => [k.key, k.label])) : STARTERS;
  const options = kinds ? Object.fromEntries(list.filter((k) => !k.archived || k.key === keep).map((k) => [k.key, k.label])) : STARTERS;
  return { kinds: list, labels, options, reload: fetchKinds };
}

const every = (days) => (days === 7 ? 'every week' : days === 14 ? 'every 2 weeks' : days === 30 ? 'every 30 days' : days === 365 ? 'every year' : `every ${days} days`);
const shortDay = (iso) => dayLabel(new Date(iso), { weekday: 'short', month: 'short', day: 'numeric' });

/** Account → Health tests: how often each test is due and what it costs, for the rules where you work. */
export function TestKindsSettings() {
  const { kinds, reload } = useTestKinds();
  const [rows, setRows] = useState(null);
  const [message, setMessage] = useState(null);
  useEffect(() => { reload(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setRows(kinds.map((k) => ({ id: k.id, label: k.label, every_days: k.every_days ?? '', cost: k.cost ?? '', archived: k.archived, starter: k.starter, tests: k.tests })));
  }, [kinds]);
  if (!rows) return null;
  const update = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const save = async (e) => {
    e.preventDefault();
    setMessage(null);
    try {
      for (const r of rows) {
        const body = { label: r.label, every_days: r.every_days === '' ? null : Number(r.every_days), cost: r.cost === '' ? null : Number(r.cost), archived: r.archived };
        if (r.id) await axios.put(`/api/test-kinds/${r.id}`, body);
        else if (r.label.trim()) await axios.post('/api/test-kinds', body);
      }
      await reload();
      setMessage({ ok: 'Saved.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    }
  };
  const remove = async (r, i) => {
    if (!r.id) return setRows(rows.filter((_, j) => j !== i));
    await axios.delete(`/api/test-kinds/${r.id}`).catch(() => {});
    return reload();
  };

  return (
    <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-gray-600">
        Testing rules differ from place to place, and so do prices. Set each test to how often <b>you</b> need it and what it costs you.
        sworkr then tells you when the next one is due and fills in the cost when you add one to the calendar.
      </p>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={r.id || `new-${i}`} className={`grid grid-cols-12 gap-2 items-end ${r.archived ? 'opacity-60' : ''}`}>
            <label className="col-span-12 sm:col-span-5 text-xs text-gray-500">Test
              <input value={r.label} onChange={(e) => update(i, { label: e.target.value })} placeholder="e.g. Full panel" maxLength={60} className={inputClass} />
            </label>
            <label className="col-span-4 sm:col-span-2 text-xs text-gray-500">Every (days)
              <input type="number" min="1" max="3650" value={r.every_days} onChange={(e) => update(i, { every_days: e.target.value })} placeholder="No schedule" className={inputClass} />
            </label>
            <label className="col-span-4 sm:col-span-2 text-xs text-gray-500">Cost ($)
              <input type="number" min="0" step="0.01" inputMode="decimal" value={r.cost} onChange={(e) => update(i, { cost: e.target.value })} className={inputClass} />
            </label>
            <span className="col-span-4 sm:col-span-3 flex items-center gap-3 pb-2 text-xs">
              {r.id && (
                <label className="flex items-center gap-1 text-gray-600">
                  <input type="checkbox" checked={!r.archived} onChange={(e) => update(i, { archived: !e.target.checked })} /> In use
                </label>
              )}
              {(!r.id || (!r.starter && !r.tests)) && <button type="button" onClick={() => remove(r, i)} className="text-gray-400 hover:text-red-500">Remove</button>}
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-gray-400">
        Examples: 7 for weekly, 14 for every two weeks, 30 for monthly, 90 for every three months. Leave "Every" empty for a test with no fixed schedule.
        Tests already on your calendar keep the name they had.
      </p>
      {message?.error && <p className="text-sm text-red-600">{message.error}</p>}
      {message?.ok && <p className="text-sm text-emerald-600">{message.ok}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={buttonClass}>Save</button>
        <button type="button" onClick={() => setRows([...rows, { label: '', every_days: '', cost: '', archived: false }])} className="px-4 py-2 border border-gray-200 rounded-full text-sm text-gray-600 hover:bg-gray-50">+ Add a test</button>
      </div>
    </form>
  );
}

/** On the dashboard: tests that are due soon or overdue and aren't booked yet. */
export function TestsDue() {
  const { kinds, reload } = useTestKinds();
  useEffect(() => { reload(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const due = kinds.filter((k) => k.state === 'overdue' || k.state === 'soon');
  if (due.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Health tests due</h2>
        <Link to="/calendar" className="text-sm text-sworkr-600 hover:text-sworkr-800">Calendar →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {due.map((k) => (
          <li key={k.id} className="py-2 flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-medium text-gray-800">{k.label}</span>
              <span className="text-xs text-gray-500"> · {every(k.every_days)}{k.cost != null ? ` · ${money(k.cost)}` : ''}</span>
            </span>
            <span className={`text-xs ${k.state === 'overdue' ? 'text-red-600' : 'text-amber-700'}`}>
              {k.due_in_days < 0 ? `${-k.due_in_days} day${k.due_in_days === -1 ? '' : 's'} overdue` : k.due_in_days === 0 ? 'Due today' : `Due ${shortDay(k.next_due)}`}
              {k.next_booked ? ` (next booked ${shortDay(k.next_booked)})` : ''}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-gray-400 mt-1">Change how often under <Link to="/account/work#tests" className="underline">Account → Health tests</Link>.</p>
    </div>
  );
}
