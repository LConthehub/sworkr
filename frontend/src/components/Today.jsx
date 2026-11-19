import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass } from './Modal';
import { useFeatures } from '../features';
import { money, toDateInput } from '../colors';

const LOGS = [
  ['log_shift', 'shift', 'Shift done', 'dances or bookings'],
  ['log_stream', 'stream', 'Stream done', 'tokens'],
  ['log_call', 'call', 'Calls done', 'minutes'],
  ['log_scene', 'scene', 'Scene done', null],
  ['log_sale', 'sale', 'Sold something', 'items'],
];

/** The five-second log: what you did, how long, what came in. Makes the income entry for you. */
function QuickLog({ kind, title, unit, onClose }) {
  const [sources, setSources] = useState([]);
  const [form, setForm] = useState({ source_id: '', hours: '', gross: '', fees: '', units: '', pending: false, note: '' });
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(null);
  useEffect(() => {
    axios.get('/api/income-sources').then(({ data }) => setSources(data.filter((s) => !s.archived))).catch(() => {});
  }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const num = (v) => (v === '' ? null : Number(v));
  const submit = async (e) => {
    e.preventDefault();
    try {
      const { data } = await axios.post('/api/worklog', {
        kind, day: toDateInput(new Date()), source_id: num(form.source_id), hours: num(form.hours), units: num(form.units),
        gross: num(form.gross) || 0, fees: num(form.fees) || 0, pending: form.pending, note: form.note,
      });
      setSaved(data);
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  if (saved) {
    const kept = (saved.gross || 0) - (saved.fees || 0);
    return (
      <Modal title="Logged" onClose={onClose}>
        <p className="text-sm text-gray-700">
          You kept {money(kept)}{saved.hours ? `, about ${money(kept / saved.hours)} an hour` : ''}. It's in your income.
        </p>
        <div className="flex justify-end mt-3"><button onClick={onClose} className={buttonClass}>Done</button></div>
      </Modal>
    );
  }
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {sources.length > 0 && (
          <Field label="Where">
            <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
              <option value="">Not saying</option>
              {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Hours"><input type="number" inputMode="decimal" min="0" max="24" step="0.25" value={form.hours} onChange={set('hours')} className={inputClass} /></Field>
          {unit && <Field label={`How many ${unit}`}><input type="number" inputMode="decimal" min="0" step="1" value={form.units} onChange={set('units')} className={inputClass} /></Field>}
          <Field label="What came in ($)"><input type="number" inputMode="decimal" min="0" step="1" value={form.gross} onChange={set('gross')} autoFocus className={inputClass} /></Field>
          <Field label="Their cut and fees ($)"><input type="number" inputMode="decimal" min="0" step="1" value={form.fees} onChange={set('fees')} className={inputClass} /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={form.pending} onChange={set('pending')} /> Not paid out to me yet</label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end"><button type="submit" className={`${buttonClass} !py-3 !px-6`}>Log it</button></div>
      </form>
    </Modal>
  );
}

/** A safety timer for anything: "tell my contact if I haven't tapped I'm safe in 20 minutes". */
function SafetyTimer() {
  const [state, setState] = useState(null);     // { timer, armed }
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get('/api/safety/timer').then(({ data }) => setState(data)).catch(() => setState({ timer: null, armed: false }));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!state?.timer) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [state?.timer]);
  if (!state) return null;
  const start = async (minutes) => {
    setError('');
    const note = window.prompt(`Your contact is told if you haven't tapped "I'm safe" in ${minutes} minutes.\nA note for them (optional), like where you are:`, '');
    if (note === null) return;
    try {
      const { data } = await axios.post('/api/safety/timer', { minutes, note });
      setState({ ...state, timer: data.timer });
    } catch (err) {
      setError(errorMessage(err, "Couldn't start the timer"));
    }
  };
  const safe = async () => {
    await axios.post('/api/safety/timer/safe').catch(() => {});
    load();
  };
  if (state.timer) {
    const left = Math.round((new Date(state.timer.due_at).getTime() - now) / 1000);
    const late = left <= 0;
    return (
      <div className={`rounded-xl p-3 ${late ? 'bg-red-600 text-white' : 'bg-amber-50 text-amber-900'}`} role="status">
        <p className="text-sm">
          {state.timer.alert_sent_at ? 'Your contact has been told.' : late ? 'Time is up: your contact is being told.'
            : `Safety timer: ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} left`}
        </p>
        <button onClick={safe} className="mt-2 w-full py-3 rounded-lg bg-emerald-600 text-white text-base font-semibold hover:bg-emerald-700">✓ I'm safe</button>
      </div>
    );
  }
  if (!state.armed) {
    return <p className="text-xs text-gray-500">Safety timer: <Link to="/account/safety" className="underline text-sworkr-600">add a trusted contact</Link> to use it.</p>;
  }
  return (
    <div>
      <p className="text-xs text-gray-500 mb-1">Safety timer: tell my contact if I don't tap "I'm safe" in</p>
      <div className="flex flex-wrap gap-2">
        {[20, 30, 60, 120].map((m) => (
          <button key={m} onClick={() => start(m)} className="px-3 py-2 rounded-lg border border-gray-200 text-sm text-gray-700 hover:bg-gray-50">{m < 60 ? `${m} min` : `${m / 60} h`}</button>
        ))}
      </div>
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </div>
  );
}

/** Top of the dashboard, made for a phone: quick logs for your kind of work, the safety timer, what's running low. */
export default function Today({ onLogged }) {
  const has = useFeatures();
  const [log, setLog] = useState(null);
  const [low, setLow] = useState([]);
  useEffect(() => {
    axios.get('/api/supplies').then(({ data }) => setLow(data.supplies.filter((s) => s.low))).catch(() => {});
  }, []);
  const logs = LOGS.filter(([feature]) => has(feature));
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 space-y-3">
      {logs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {logs.map(([, kind, title, unit]) => (
            <button key={kind} onClick={() => setLog({ kind, title, unit })}
              className="flex-1 min-w-[8rem] py-3 rounded-xl bg-sworkr-500 text-white text-sm font-semibold hover:bg-sworkr-600">{title}</button>
          ))}
        </div>
      )}
      <SafetyTimer />
      {low.length > 0 && (
        <p className="text-sm text-amber-800 bg-amber-50 rounded-lg px-3 py-2">
          Running low: {low.map((s) => `${s.name} (${s.have})`).join(', ')}.
        </p>
      )}
      {log && <QuickLog {...log} onClose={() => { setLog(null); onLogged?.(); }} />}
    </div>
  );
}
