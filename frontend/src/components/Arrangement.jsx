import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { money } from '../colors';

const CADENCES = { per_meet: 'Each time we meet', weekly: 'Weekly', biweekly: 'Every two weeks', monthly: 'Monthly' };
const dateText = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

/** A contact's arrangement: their regular allowance, when it's next due, and "Received" to log it. */
export default function Arrangement({ clientId, onChanged }) {
  const [a, setA] = useState(undefined);   // undefined loading, null none
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ amount: '', cadence: 'monthly', next_due: '', notes: '' });
  const [message, setMessage] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/clients/${clientId}/arrangement`).then(({ data }) => setA(data)).catch(() => setA(null));
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  const edit = () => {
    setForm({ amount: a?.amount ?? '', cadence: a?.cadence || 'monthly', next_due: a?.next_due || '', notes: a?.notes || '' });
    setEditing(true);
  };
  const save = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const { data } = await axios.put(`/api/clients/${clientId}/arrangement`, {
        amount: form.amount === '' ? null : Number(form.amount), cadence: form.cadence,
        next_due: form.next_due || null, notes: form.notes || null, active: true,
      });
      setA(data);
      setEditing(false);
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't save"));
    }
  };
  const received = async () => {
    setMessage('');
    try {
      const { data } = await axios.post(`/api/clients/${clientId}/arrangement/received`, {});
      setA(data.arrangement);
      setMessage(`Logged ${money(a.amount)} as income.`);
      onChanged?.();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't log it"));
    }
  };
  const stop = async () => {
    if (!window.confirm('End this arrangement? Allowances already logged stay in your income.')) return;
    await axios.delete(`/api/clients/${clientId}/arrangement`).catch(() => {});
    setA(null);
  };

  if (a === undefined) return null;
  if (editing) {
    return (
      <form onSubmit={save} className="bg-white rounded-2xl border border-line shadow-sm p-4 space-y-3">
        <h2 className="font-semibold text-gray-800">Arrangement</h2>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Allowance ($)">
            <input type="number" min="0" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={inputClass} />
          </Field>
          <Field label="How often">
            <select value={form.cadence} onChange={(e) => setForm({ ...form, cadence: e.target.value })} className={inputClass}>
              {Object.entries(CADENCES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          {form.cadence !== 'per_meet' && (
            <Field label="Next due">
              <input type="date" value={form.next_due} onChange={(e) => setForm({ ...form, next_due: e.target.value })} className={inputClass} />
            </Field>
          )}
        </div>
        <Field label="Notes">
          <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="e.g. Paid by app, plus dinners" className={inputClass} />
        </Field>
        {message && <p className="text-sm text-red-600">{message}</p>}
        <div className="flex gap-2">
          <button type="submit" className={buttonClass}>Save</button>
          <button type="button" onClick={() => setEditing(false)} className={quietButtonClass}>Cancel</button>
        </div>
      </form>
    );
  }
  if (!a) {
    return (
      <button type="button" onClick={edit} className="text-sm text-muted hover:text-sworkr-600 underline-offset-2 hover:underline">
        + Set up an arrangement (a regular allowance)
      </button>
    );
  }
  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 flex flex-wrap items-center gap-3">
      <div className="flex-1 min-w-48">
        <h2 className="font-semibold text-gray-800">Arrangement</h2>
        <p className="text-sm text-gray-600">
          {a.amount != null ? money(a.amount) : 'Amount not set'} · {CADENCES[a.cadence].toLowerCase()}
          {a.next_due && <> · next due <strong>{dateText(a.next_due)}</strong></>}
        </p>
        {a.notes && <p className="text-xs text-gray-500">{a.notes}</p>}
        {message && <p className="text-xs text-emerald-700 mt-1">{message}</p>}
      </div>
      {a.amount != null && <button type="button" onClick={received} className={buttonClass}>Received</button>}
      <button type="button" onClick={edit} className={quietButtonClass}>Edit</button>
      <button type="button" onClick={stop} className="text-xs text-red-500 hover:text-red-700">End</button>
    </div>
  );
}
