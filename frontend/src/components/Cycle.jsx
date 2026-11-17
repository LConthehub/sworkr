import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { dayLabel, fromDateInput, toDateInput } from '../colors';


const today = () => toDateInput(new Date());
const nice = (iso) => dayLabel(fromDateInput(iso), { month: 'short', day: 'numeric' });
export const CYCLE_LABELS = { period: 'Period', predicted: 'Period (predicted)', fertile: 'Fertile (estimate)' };

/** A small marker for a cycle day: filled = logged period, outlined = predicted, green = estimated fertile. */
export function CycleDot({ kind, className = '' }) {
  if (!kind) return null;
  const look = kind === 'period' ? 'bg-rose-400' : kind === 'predicted' ? 'border-[1.5px] border-rose-400' : 'border-[1.5px] border-emerald-400';
  return <span className={`inline-block shrink-0 w-2 h-2 rounded-full ${look} ${className}`} title={CYCLE_LABELS[kind]} aria-label={CYCLE_LABELS[kind]} />;
}

/** Cycle tracking settings: opt-in. */
export function CycleSettings() {
  const [s, setS] = useState(null);
  const [message, setMessage] = useState(null);
  useEffect(() => { axios.get('/api/cycle/settings').then(({ data }) => setS(data)).catch(() => {}); }, []);
  if (!s) return null;
  const save = async (changes) => {
    const next = { ...s, ...changes };
    setS(next);
    setMessage(null);
    try {
      setS((await axios.put('/api/cycle/settings', next)).data);
      setMessage({ ok: 'Saved.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    }
  };
  return (
    <div className="space-y-3 text-sm text-gray-700">
      <label className="flex items-start gap-2">
        <input type="checkbox" className="mt-1" checked={s.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
        <span>Turn on the period tracker<span className="block text-xs text-gray-500">
          If you have periods and want to plan around them, log them to see the next ones predicted on your calendar and dashboard, and plan bookings and tours around them.
          It stays in sworkr: never synced to calendars, put in CSV exports, or shown to anyone else. Your encrypted backups include it.
        </span></span>
      </label>
      {s.enabled && (
        <>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={s.warn_on_booking} onChange={(e) => save({ warn_on_booking: e.target.checked })} />
            Ask me first when I book a client on a period day
          </label>
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={s.show_fertile} onChange={(e) => save({ show_fertile: e.target.checked })} />
            <span>Show estimated fertile days<span className="block text-xs text-amber-700">
              A rough guess from your average cycle. Never rely on it as contraception or to plan around it.</span></span>
          </label>
          <div className="grid grid-cols-2 gap-3 max-w-sm">
            <Field label="Usual cycle (days)">
              <input type="number" min="15" max="60" value={s.typical_cycle} onChange={(e) => setS({ ...s, typical_cycle: e.target.value })}
                onBlur={() => save({ typical_cycle: Number(s.typical_cycle) })} className={inputClass} />
            </Field>
            <Field label="Usual period (days)">
              <input type="number" min="1" max="14" value={s.typical_period} onChange={(e) => setS({ ...s, typical_period: e.target.value })}
                onBlur={() => save({ typical_period: Number(s.typical_period) })} className={inputClass} />
            </Field>
          </div>
          <p className="text-xs text-gray-500">Used until you've logged a few cycles; after that sworkr uses your own averages.</p>
        </>
      )}
      {message?.error && <p className="text-red-600">{message.error}</p>}
      {message?.ok && <p className="text-emerald-600">{message.ok}</p>}
    </div>
  );
}

/** The dashboard card: where you are in your cycle, and quick logging. Shows only when tracking is on. */
export function CycleCard({ onChanged }) {
  const [c, setC] = useState(null);
  const [history, setHistory] = useState(false);
  const load = useCallback(() => {
    axios.get('/api/cycle', { params: { today: today() } }).then(({ data }) => setC(data)).catch(() => setC(null));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!c || !c.settings.enabled) return null;
  const changed = () => { load(); onChanged?.(); };
  const started = async () => {
    try {
      await axios.post('/api/cycle/entries', { start_date: today() });
      changed();
    } catch (err) {
      window.alert(errorMessage(err, 'Could not save'));
    }
  };
  const ended = async () => {
    const e = c.entries[0];
    await axios.put(`/api/cycle/entries/${e.id}`, { ...e, end_date: today() }).catch(() => {});
    changed();
  };
  const t = c.today;
  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-5">
      <div className="flex items-center justify-between mb-2">
        <h2 className="font-semibold text-gray-800">Cycle</h2>
        <button onClick={() => setHistory(true)} className="text-sm text-sworkr-600 hover:text-sworkr-800">History & edit</button>
      </div>
      {c.entries.length === 0 ? (
        <p className="text-sm text-gray-500">Log your next period (or add past ones in History) and sworkr will start predicting.</p>
      ) : (
        <div className="text-sm text-gray-700 space-y-1">
          {t && <p>{t.on_period ? <span className="font-medium text-rose-600">On your period · </span> : null}Day {t.cycle_day} of about {c.average_cycle}</p>}
          {c.next_period && (
            <p>
              Next period {c.days_until_next <= 0 ? <b>due now</b> : <>in about <b>{c.days_until_next} day{c.days_until_next === 1 ? '' : 's'}</b></>}
              <span className="text-gray-500"> ({nice(c.next_period.start)}–{nice(c.next_period.end)})</span>
            </p>
          )}
          {c.irregular && <p className="text-xs text-amber-700">Your cycles vary a lot, so predictions are less certain.</p>}
        </div>
      )}
      <div className="flex flex-wrap gap-2 mt-3">
        {t?.open_entry ? (
          <button onClick={ended} className={quietButtonClass}>My period ended today</button>
        ) : (
          <button onClick={started} className="px-3 py-2 rounded-full text-sm bg-rose-500 text-white hover:bg-rose-600">My period started today</button>
        )}
      </div>
      {history && (
        <Modal title="Cycle history" onClose={() => setHistory(false)}>
          <CycleHistory summary={c} onChanged={changed} />
        </Modal>
      )}
    </div>
  );
}

function CycleHistory({ summary, onChanged }) {
  const [form, setForm] = useState({ id: null, start_date: today(), end_date: '', flow: '', notes: '' });
  const [error, setError] = useState('');
  const save = async (e) => {
    e.preventDefault();
    setError('');
    const body = { start_date: form.start_date, end_date: form.end_date || null, flow: form.flow || null, notes: form.notes || null };
    try {
      if (form.id) await axios.put(`/api/cycle/entries/${form.id}`, body);
      else await axios.post('/api/cycle/entries', body);
      setForm({ id: null, start_date: today(), end_date: '', flow: '', notes: '' });
      onChanged();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const remove = async (entry) => {
    if (!window.confirm(`Delete the period from ${nice(entry.start_date)}?`)) return;
    await axios.delete(`/api/cycle/entries/${entry.id}`).catch(() => {});
    onChanged();
  };
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Usual cycle {summary.average_cycle} days, period {summary.average_period} days
        {summary.cycles_counted ? ` (from your last ${summary.cycles_counted} cycle${summary.cycles_counted === 1 ? '' : 's'})` : ' (your settings, until you log more)'}.
      </p>
      <form onSubmit={save} className="rounded-xl bg-gray-50 p-3 space-y-2">
        <p className="text-sm font-medium text-gray-700">{form.id ? 'Change this period' : 'Add a period'}</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <Field label="Started"><input required type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} className={`${inputClass} bg-white`} /></Field>
          <Field label="Ended"><input type="date" value={form.end_date} min={form.start_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} className={`${inputClass} bg-white`} /></Field>
          <Field label="Flow">
            <select value={form.flow} onChange={(e) => setForm({ ...form, flow: e.target.value })} className={`${inputClass} bg-white`}>
              <option value="">—</option><option value="light">Light</option><option value="medium">Medium</option><option value="heavy">Heavy</option>
            </select>
          </Field>
        </div>
        <Field label="Notes"><input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Cramps, mood, anything" className={`${inputClass} bg-white`} /></Field>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-2 justify-end">
          {form.id && <button type="button" onClick={() => setForm({ id: null, start_date: today(), end_date: '', flow: '', notes: '' })} className={quietButtonClass}>Cancel</button>}
          <button type="submit" className={buttonClass}>{form.id ? 'Save' : 'Add'}</button>
        </div>
      </form>
      <ul className="divide-y divide-gray-100 text-sm">
        {summary.entries.map((e) => (
          <li key={e.id} className="flex items-center gap-3 py-2">
            <span className="w-40 text-gray-800">{nice(e.start_date)}{e.end_date ? ` – ${nice(e.end_date)}` : ' (ongoing)'}</span>
            <span className="flex-1 text-xs text-gray-500 truncate">{[e.flow, e.notes].filter(Boolean).join(' · ')}</span>
            <button onClick={() => setForm({ id: e.id, start_date: e.start_date, end_date: e.end_date || '', flow: e.flow || '', notes: e.notes || '' })} className="text-xs text-sworkr-600">Edit</button>
            <button onClick={() => remove(e)} className="text-xs text-red-500">Delete</button>
          </li>
        ))}
      </ul>
      {summary.predictions.length > 0 && (
        <p className="text-xs text-gray-500">Predicted: {summary.predictions.slice(0, 3).map((p) => `${nice(p.start)}–${nice(p.end)}`).join(' · ')}</p>
      )}
    </div>
  );
}

/** Cycle days in a date range, for the calendar and the tour form. Empty when tracking is off. */
export function useCycleDays(startKey, endKey) {
  const [days, setDays] = useState({});
  useEffect(() => {
    if (!startKey || !endKey || endKey <= startKey) { setDays({}); return; }
    axios.get('/api/cycle/days', { params: { start: startKey, end: endKey, today: today() } })
      .then(({ data }) => setDays(Object.fromEntries(data.map((d) => [d.date, d.kind])))).catch(() => setDays({}));
  }, [startKey, endKey]);
  return days;
}
