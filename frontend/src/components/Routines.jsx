import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

const WHEN = {
  morning: 'Morning', night: 'Night', before_booking: 'Before a booking', after_booking: 'After a booking', any: 'Any time',
};

/** Make or change a routine: its name, when it's for, and its steps (one per line). */
function RoutineForm({ routine, onDone }) {
  const [form, setForm] = useState({
    name: routine?.name || '', when: routine?.when || 'any',
    steps: (routine?.steps || []).map((s) => (typeof s === 'string' ? s : s.label)).join('\n'),
  });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = { name: form.name, when: form.when, steps: form.steps.split('\n') };
    try {
      if (routine?.id) await axios.put(`/api/routines/${routine.id}`, body);
      else await axios.post('/api/routines', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the routine"));
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete the routine "${routine.name}"?`)) return;
    await axios.delete(`/api/routines/${routine.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Name"><input required autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Morning, Before a booking" className={inputClass} /></Field>
        <Field label="When">
          <select value={form.when} onChange={set('when')} className={inputClass}>
            {Object.entries(WHEN).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Steps (one per line)">
        <textarea rows={7} value={form.steps} onChange={set('steps')} className={inputClass}
          placeholder={'e.g.\nWater and something to eat\nCheck today\'s bookings\nStretch'} />
      </Field>
      <p className="text-xs text-gray-500">
        Anything you do the same way each time: getting ready, winding down, safety steps before a booking, logging money
        after one, a weekly reset. Ticks start fresh each day.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {routine?.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save routine</button>
      </div>
    </form>
  );
}

/** Dashboard card: today's routines, ticked off step by step. */
export function RoutinesCard() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);        // the routine shown with its steps
  const [editing, setEditing] = useState(null);  // { routine } (routine may be a starter, or null for new)
  const load = useCallback(() => {
    axios.get('/api/routines').then(({ data: d }) => setData(d)).catch(() => setData({ routines: [], starters: [] }));
  }, []);
  useEffect(() => { load(); }, [load]);
  const tick = async (r, step) => {
    const { data: updated } = await axios.post(`/api/routines/${r.id}/check`, { step_id: step.id, done: !step.done });
    setData((d) => ({ ...d, routines: d.routines.map((x) => (x.id === r.id ? updated : x)) }));
  };
  if (!data) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h2 className="font-semibold text-gray-800">Routines</h2>
        <button onClick={() => setEditing({ routine: null })} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Routine</button>
      </div>
      {data.routines.length === 0 ? (
        <div className="space-y-2">
          <p className="text-sm text-gray-500">Checklists you go through again and again. Start from one of these and make it yours:</p>
          <div className="flex flex-wrap gap-2">
            {data.starters.map((s) => (
              <button key={s.name} onClick={() => setEditing({ routine: s })} className={quietButtonClass}>{s.name}</button>
            ))}
          </div>
        </div>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data.routines.map((r) => (
            <li key={r.id} className="py-2">
              <div className="flex items-center gap-2">
                <button onClick={() => setOpen(open === r.id ? null : r.id)} className="flex-1 text-left">
                  <span className="text-sm font-medium text-gray-800">{r.name}</span>
                  <span className="ml-2 text-xs text-gray-500">{WHEN[r.when]} · {r.done}/{r.total}{r.done === r.total && ' ✓'}</span>
                </button>
                <button onClick={() => setEditing({ routine: r })} className="text-xs text-gray-400 hover:text-sworkr-600">Edit</button>
              </div>
              {open === r.id && (
                <ul className="mt-1 space-y-1 pl-1">
                  {r.steps.map((s) => (
                    <li key={s.id}>
                      <label className="flex items-start gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={s.done} onChange={() => tick(r, s)} className="mt-1" />
                        <span className={s.done ? 'line-through text-gray-400' : ''}>{s.label}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <Modal title={editing.routine?.id ? 'Edit routine' : 'New routine'} onClose={() => setEditing(null)}>
          <RoutineForm routine={editing.routine} onDone={() => { setEditing(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}
