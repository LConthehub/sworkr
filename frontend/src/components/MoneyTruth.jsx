import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage, quietButtonClass } from './Modal';
import { money } from '../colors';

/** What an hour really pays, by kind of work, and after all your costs. */
export function PerHour() {
  const [days, setDays] = useState(90);
  const [data, setData] = useState(null);
  const load = useCallback(() => {
    axios.get('/api/per-hour', { params: { days } }).then(({ data: d }) => setData(d)).catch(() => setData(null));
  }, [days]);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const savePrep = async (e) => {
    const value = Number(e.target.value);
    if (Number.isNaN(value) || value === data.prep_minutes) return;
    await axios.put('/api/per-hour/prep', { prep_minutes: value }).catch(() => {});
    load();
  };
  const best = Math.max(1, ...data.rows.map((r) => r.per_hour || 0));
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-gray-800">What an hour really pays</h2>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period" className={`${inputClass} !w-auto !py-1.5`}>
          {[30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>
      {data.rows.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing to go on yet. Finished bookings count, and so do the quick logs on the dashboard (a shift, a stream, a sale) when you add the hours.</p>
      ) : (
        <>
          <ul className="space-y-2">
            {data.rows.map((r) => (
              <li key={r.label}>
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="text-gray-800">{r.label} <span className="text-xs text-gray-500">· {r.count} · {r.hours} h · {money(r.net)}</span></span>
                  <span className="font-semibold tabular-nums text-gray-800">{r.per_hour != null ? `${money(r.per_hour)}/h` : 'add hours'}</span>
                </div>
                <div className="h-2 rounded-full bg-gray-100 overflow-hidden"><div className="h-full bg-sworkr-500" style={{ width: `${((r.per_hour || 0) / best) * 100}%` }} /></div>
                {r.note && <p className="text-xs text-gray-500">{r.note}</p>}
              </li>
            ))}
          </ul>
          <p className="text-sm text-gray-700 border-t border-gray-100 pt-2">
            All of that, less all your costs ({money(data.overall.costs)}): <b>{data.overall.per_hour != null ? `${money(data.overall.per_hour)} an hour` : '–'}</b> over {data.overall.hours} hours.
          </p>
        </>
      )}
      <label className="flex items-center gap-2 text-xs text-gray-500">
        Getting ready and travel per booking
        <input type="number" min="0" max="600" step="5" defaultValue={data.prep_minutes} onBlur={savePrep} className={`${inputClass} !w-20 !py-1`} /> minutes
      </label>
    </div>
  );
}

/** Steady pay for uneven months: the same amount each week, out of a buffer envelope. */
export function SteadyPay() {
  const [data, setData] = useState(null);
  const [goals, setGoals] = useState([]);
  const [form, setForm] = useState({ weekly: '', goal_id: '' });
  const [message, setMessage] = useState('');
  const load = useCallback(() => {
    axios.get('/api/steady-pay').then(({ data: d }) => {
      setData(d);
      setForm({ weekly: d.weekly ?? '', goal_id: d.buffer?.goal_id ?? '' });
    }).catch(() => {});
    axios.get('/api/goals').then(({ data: g }) => setGoals(g.filter((x) => !x.archived))).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const save = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const { data: d } = await axios.put('/api/steady-pay', { weekly: form.weekly === '' ? null : Number(form.weekly), goal_id: form.goal_id === '' ? null : Number(form.goal_id) });
      setData(d);
      setMessage('Saved.');
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't save"));
    }
  };
  const top = Math.max(1, ...data.months.map((m) => Math.abs(m)));
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
      <h2 className="font-semibold text-gray-800">Steady pay</h2>
      <p className="text-sm text-gray-600">
        For uneven months: put what comes in into a buffer envelope, and pay yourself the same amount every week. Good months fill
        the buffer, slow months draw on it.
      </p>
      <div className="flex items-end gap-1 h-16" aria-label="What was left each of the last six months">
        {[...data.months].reverse().map((m, i) => (
          <div key={i} className="flex-1 flex flex-col justify-end items-center" title={money(m)}>
            <div className={`w-full rounded-t ${m >= 0 ? 'bg-emerald-500' : 'bg-red-400'}`} style={{ height: `${(Math.abs(m) / top) * 100}%`, minHeight: 2 }} />
          </div>
        ))}
      </div>
      <p className="text-xs text-gray-500">
        Left after costs, last six months: about {money(data.average_month)} a month.
        {data.suggested_weekly > 0 && <> A careful weekly amount would be around <b>{money(data.suggested_weekly)}</b>.</>}
      </p>
      <form onSubmit={save} className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-500">I pay myself each week
          <input type="number" min="0" step="10" value={form.weekly} onChange={(e) => setForm({ ...form, weekly: e.target.value })} placeholder={data.suggested_weekly || ''} className={`${inputClass} !w-28 block`} />
        </label>
        <label className="text-xs text-gray-500">My buffer is
          <select value={form.goal_id} onChange={(e) => setForm({ ...form, goal_id: e.target.value })} className={`${inputClass} !w-44 block`}>
            <option value="">Choose an envelope</option>
            {goals.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        </label>
        <button type="submit" className={quietButtonClass}>Save</button>
        {message && <span className="text-xs text-gray-600">{message}</span>}
      </form>
      {data.buffer && data.weekly && (
        <p className="text-sm text-gray-700">
          {data.buffer.name} holds {money(data.buffer.balance)}: that's <b>{data.buffer.weeks} weeks</b> of pay.
          {data.buffer.weeks < 4 ? ' Aim for at least 4 weeks before leaning on it.' : ''}
        </p>
      )}
      {goals.length === 0 && <p className="text-xs text-gray-500">Make an envelope called "Buffer" under Money → Wallet first.</p>}
    </div>
  );
}
