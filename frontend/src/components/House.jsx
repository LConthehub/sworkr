import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const GUIDED = ['brothel', 'agency'];
const SHIFT_STARTERS = {
  'Two 12-hour shifts': [{ label: 'Days', start: '05:00', end: '17:00' }, { label: 'Nights', start: '17:00', end: '05:00' }],
  'Three 8-hour shifts': [{ label: 'Days', start: '07:00', end: '15:00' }, { label: 'Swing', start: '15:00', end: '23:00' }, { label: 'Nights', start: '23:00', end: '07:00' }],
};

/** Yes / No / not answered, as three buttons. */
function YesNo({ value, onChange, label }) {
  return (
    <span className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label={label}>
      {[[true, 'Yes'], [false, 'No']].map(([v, text]) => (
        <button key={text} type="button" aria-pressed={value === v} onClick={() => onChange(value === v ? null : v)}
          className={`px-4 py-1.5 ${value === v ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{text}</button>
      ))}
    </span>
  );
}

/** One place's rules, asked one plain question at a time. */
export function HouseRulesForm({ sourceId, onDone }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get(`/api/income-sources/${sourceId}/rules`).then(({ data }) => setForm({
      ...data, outdate_rules: data.outdate_rules || '', storage_rules: data.storage_rules || '', other_rules: data.other_rules || '',
      doctor_weekday: data.doctor_weekday ?? '', shifts: data.shifts.length ? data.shifts.map((s) => ({ ...s, label: s.label || '' })) : [],
    })).catch(() => setError("Couldn't open this place's rules"));
  }, [sourceId]);
  if (!form) return error ? <p className="text-sm text-red-600">{error}</p> : null;
  const guided = GUIDED.includes(form.kind);
  const set = (patch) => setForm({ ...form, ...patch });
  const setShift = (i, patch) => set({ shifts: form.shifts.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const pattern = (p) => set({
    shift_pattern: p,
    shifts: p === 'none' ? [] : p === 'fixed' ? [form.shifts[0] || { label: '', start: '05:00', end: '17:00' }]
      : form.shifts.length > 1 ? form.shifts : SHIFT_STARTERS['Two 12-hour shifts'],
  });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await axios.put(`/api/income-sources/${sourceId}/rules`, {
        outdates_allowed: form.outdates_allowed, outdate_rules: form.outdate_rules, shift_pattern: form.shift_pattern,
        shifts: form.shifts.map(({ label, start, end }) => ({ label, start, end })), storage_allowed: form.storage_allowed,
        storage_rules: form.storage_rules, other_rules: form.other_rules,
        doctor_weekday: form.doctor_weekday === '' || form.no_doctor ? null : Number(form.doctor_weekday), no_doctor: !!form.no_doctor,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5">
      <p className="text-sm text-gray-600">Every place does things its own way. Answer what you know; skip what you don't and come back.</p>

      {guided && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-gray-800">Which day does the doctor come?</legend>
          <div className="flex flex-wrap items-center gap-3">
            <select value={form.no_doctor ? '' : form.doctor_weekday} disabled={form.no_doctor} onChange={(e) => set({ doctor_weekday: e.target.value })} aria-label="The doctor's day" className={`${inputClass} !w-auto`}>
              <option value="">Not sure yet</option>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
            <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={!!form.no_doctor} onChange={(e) => set({ no_doctor: e.target.checked })} /> No doctor's day here</label>
          </div>
          <p className="text-xs text-gray-500">Tests on a stay here land on this day, and a party is warned about until the result is clear. {!form.has_doctor_charge && form.doctor_weekday !== '' && !form.no_doctor && 'A Doctor charge is added to this place; set its price on the place itself.'}</p>
        </fieldset>
      )}

      {guided && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-gray-800">Does this place allow outdates?</legend>
          <YesNo label="Outdates allowed" value={form.outdates_allowed} onChange={(v) => set({ outdates_allowed: v })} />
          {form.outdates_allowed && (
            <Field label="Its rules for them">
              <textarea rows={2} value={form.outdate_rules} onChange={(e) => set({ outdate_rules: e.target.value })} placeholder="e.g. Two hours at least. The house keeps half. Sign out at the office, back by midnight." className={inputClass} />
            </Field>
          )}
          <p className="text-xs text-gray-500">When a place allows them, each client's page gets an "Outdates" answer.</p>
        </fieldset>
      )}

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-gray-800">Are there shifts?</legend>
        <span className="inline-flex flex-wrap rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Shifts">
          {[['none', 'No shifts'], ['fixed', 'The same every day'], ['varied', 'A few to choose from']].map(([id, text]) => (
            <button key={id} type="button" aria-pressed={form.shift_pattern === id} onClick={() => pattern(id)}
              className={`px-3 py-1.5 ${form.shift_pattern === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{text}</button>
          ))}
        </span>
        {form.shift_pattern === 'varied' && (
          <p className="flex flex-wrap items-center gap-2 text-xs text-gray-500">Start from:
            {Object.entries(SHIFT_STARTERS).map(([name, shifts]) => <button key={name} type="button" onClick={() => set({ shifts })} className={quietButtonClass}>{name}</button>)}
          </p>
        )}
        {(form.shift_pattern === 'fixed' || form.shift_pattern === 'varied') && (
          <ul className="space-y-2">
            {form.shifts.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                {form.shift_pattern === 'varied' && <input value={s.label} onChange={(e) => setShift(i, { label: e.target.value })} placeholder="Name" aria-label="Shift name" className={`${inputClass} !w-28`} />}
                <input type="time" required value={s.start} onChange={(e) => setShift(i, { start: e.target.value })} aria-label="Starts" className={`${inputClass} !w-auto`} />
                <span className="text-sm text-gray-500">to</span>
                <input type="time" required value={s.end} onChange={(e) => setShift(i, { end: e.target.value })} aria-label="Ends" className={`${inputClass} !w-auto`} />
                {form.shift_pattern === 'varied' && form.shifts.length > 1 && <button type="button" onClick={() => set({ shifts: form.shifts.filter((_, j) => j !== i) })} className="text-xs text-gray-400 hover:text-red-600" aria-label="Remove this shift">✕</button>}
              </li>
            ))}
          </ul>
        )}
        {form.shift_pattern === 'varied' && form.shifts.length < 8 && <button type="button" onClick={() => set({ shifts: [...form.shifts, { label: '', start: '09:00', end: '17:00' }] })} className={quietButtonClass}>+ Another shift</button>}
        <p className="text-xs text-gray-500">A shift that ends before it starts runs past midnight. You choose your shift on each stay, and booking outside it is warned about.</p>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-gray-800">Will they store a bin for you while you're away?</legend>
        <YesNo label="Storage" value={form.storage_allowed} onChange={(v) => set({ storage_allowed: v })} />
        {form.storage_allowed && (
          <Field label="Its rules for storage">
            <textarea rows={2} value={form.storage_rules} onChange={(e) => set({ storage_rules: e.target.value })} placeholder="e.g. One bin with a lid, your name on it. Kept 60 days, then $20 a month." className={inputClass} />
          </Field>
        )}
      </fieldset>

      <BoardRules sourceId={sourceId} />

      <Field label="Anything else to remember about this place">
        <textarea rows={3} value={form.other_rules} onChange={(e) => set({ other_rules: e.target.value })} placeholder="e.g. Lineup rules, phones, visitors, when the kitchen closes" className={inputClass} />
      </Field>

      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save</button></div>
    </form>
  );
}

const NEW_RULE = { counts: 'party', reaches: '', basis: 'price', frees: 'day', starts_on: '', ends_on: '' };

/** A place's deals for free room and board. Each rule is saved as soon as it's added or removed, and your stays
 * there are worked out again: room & board on a free day shows as $0, with the reason. */
function BoardRules({ sourceId }) {
  const [rules, setRules] = useState([]);
  const [draft, setDraft] = useState(NEW_RULE);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/income-sources/${sourceId}/board-rules`).then(({ data }) => setRules(data)).catch(() => setError("Couldn't load these rules"));
  }, [sourceId]);
  useEffect(() => { load(); }, [load]);
  const set = (patch) => setDraft({ ...draft, ...patch });
  const add = async () => {
    setError('');
    if (!(Number(draft.reaches) > 0)) { setError('Say how much it takes'); return; }
    try {
      await axios.post(`/api/income-sources/${sourceId}/board-rules`, {
        ...draft, reaches: Number(draft.reaches), starts_on: draft.starts_on || null, ends_on: draft.ends_on || null,
      });
      setDraft(NEW_RULE);
      load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't add the rule"));
    }
  };
  const remove = async (id) => {
    try { await axios.delete(`/api/board-rules/${id}`); load(); } catch (err) { setError(errorMessage(err, "Couldn't remove the rule")); }
  };
  const small = `${inputClass} !w-auto`;
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-semibold text-gray-800">Do you ever get room and board free?</legend>
      {rules.length > 0 && (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-100">
          {rules.map((r) => (
            <li key={r.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="flex-1 text-gray-800">{r.words}
                {(r.starts_on || r.ends_on) && <span className="block text-xs text-gray-500">{[r.starts_on && `From ${r.starts_on}`, r.ends_on && `${r.starts_on ? 'until' : 'Until'} ${r.ends_on}`].filter(Boolean).join(' ')}</span>}
              </span>
              <button type="button" onClick={() => remove(r.id)} className="text-xs text-gray-400 hover:text-red-600" aria-label="Remove this rule">✕</button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
        <span>When</span>
        <select value={draft.counts} onChange={(e) => set({ counts: e.target.value })} aria-label="What counts" className={small}>
          <option value="party">one party</option>
          <option value="day">a day's earnings</option>
          <option value="week">a week's earnings</option>
        </select>
        <span>reach $</span>
        <input type="number" min="1" step="any" inputMode="decimal" value={draft.reaches} onChange={(e) => set({ reaches: e.target.value })} aria-label="Amount" placeholder="1000" className={`${inputClass} !w-24`} />
        <span>of</span>
        <select value={draft.basis} onChange={(e) => set({ basis: e.target.value })} aria-label="Measured on" className={small}>
          <option value="price">what the client paid</option>
          <option value="her_share">what I keep</option>
        </select>
        <select value={draft.frees} onChange={(e) => set({ frees: e.target.value })} aria-label="What's free" className={small}>
          <option value="day">that day is free</option>
          <option value="week">that whole week is free</option>
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
        <span>The house's deal from</span>
        <input type="date" value={draft.starts_on} onChange={(e) => set({ starts_on: e.target.value })} aria-label="From" className={small} />
        <span>until</span>
        <input type="date" value={draft.ends_on} onChange={(e) => set({ ends_on: e.target.value })} aria-label="Until" className={small} />
        <button type="button" onClick={add} className={quietButtonClass}>+ Add this rule</button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <p className="text-xs text-gray-500">Leave the dates empty if it's always been the deal. Weeks count from the first day of a stay, tips don't count towards what the client paid, and only what you log at this place counts.</p>
    </fieldset>
  );
}

function useHouseRules() {
  const [data, setData] = useState(null);
  const load = useCallback(() => { axios.get('/api/house-rules').then(({ data: d }) => setData(d)).catch(() => setData({ places: [], to_set_up: [] })); }, []);
  useEffect(() => { load(); }, [load]);
  return [data, load];
}

/** On the dashboard: a nudge to finish setting up a house or agency. Gone once every question has an answer. */
export function HouseGuide() {
  const [data, load] = useHouseRules();
  const [open, setOpen] = useState(null);
  if (!data || data.to_set_up.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 space-y-2">
      <h2 className="font-semibold text-gray-800">Set up your workplace</h2>
      <p className="text-sm text-gray-600">A few questions about how each place works, so the calendar can plan around it.</p>
      <ul className="divide-y divide-gray-100">
        {data.to_set_up.map((p) => (
          <li key={p.source_id} className="py-2 flex flex-wrap items-center gap-2">
            <span className="flex-1 min-w-40 text-sm text-gray-800">{p.name} <span className="block text-xs text-gray-500">Still to answer: {p.todo.join(', ')}</span></span>
            <button type="button" onClick={() => setOpen(p)} className="text-sm px-3 py-1.5 rounded-lg bg-sworkr-500 text-white hover:bg-sworkr-600">Set up</button>
          </li>
        ))}
      </ul>
      {open && (
        <Modal title={`${open.name}: how it works`} onClose={() => setOpen(null)} wide>
          <HouseRulesForm sourceId={open.source_id} onDone={() => { setOpen(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}

/** Settings > My work > House rules: every house, agency, club and studio, with its rules in a line. */
export function HouseRulesSettings() {
  const [data, load] = useHouseRules();
  const [open, setOpen] = useState(null);
  if (!data) return null;
  if (data.places.length === 0) return <p className="text-sm text-gray-500">Add a brothel, agency, club or studio under Workplaces &amp; platforms and its rules show here.</p>;
  const line = (p) => [
    p.doctor_weekday != null && `Doctor: ${WEEKDAYS[p.doctor_weekday]}`,
    p.outdates_allowed != null && (p.outdates_allowed ? 'Outdates allowed' : 'No outdates'),
    p.shifts.length > 0 && `Shifts: ${p.shifts.map((s) => s.text).join(', ')}`,
    p.shift_pattern === 'none' && 'No shifts',
    p.storage_allowed != null && (p.storage_allowed ? 'Stores a bin' : 'No storage'),
  ].filter(Boolean).join(' · ');
  return (
    <ul className="divide-y divide-gray-100">
      {data.places.map((p) => (
        <li key={p.source_id} className="py-2 flex flex-wrap items-center gap-2">
          <span className="flex-1 min-w-40">
            <span className="block text-sm font-medium text-gray-800">{p.name}</span>
            <span className="block text-xs text-gray-500">{line(p) || 'Nothing set yet'}</span>
            {p.todo.length > 0 && <span className="block text-xs text-amber-700">Still to answer: {p.todo.join(', ')}</span>}
          </span>
          <button type="button" onClick={() => setOpen(p)} className={quietButtonClass}>{p.todo.length ? 'Set up' : 'Edit'}</button>
        </li>
      ))}
      {open && (
        <Modal title={`${open.name}: how it works`} onClose={() => setOpen(null)} wide>
          <HouseRulesForm sourceId={open.source_id} onDone={() => { setOpen(null); load(); }} />
        </Modal>
      )}
    </ul>
  );
}

/**
 * In the tour form: which shift you're on for a stay at a place that has shifts.
 * `value` is { label, start, end } or null; the tour form saves it after the tour itself.
 */
export function StayShiftPicker({ sourceId, value, onChange }) {
  const [rules, setRules] = useState(null);
  useEffect(() => {
    setRules(null);
    if (sourceId) axios.get(`/api/income-sources/${sourceId}/rules`).then(({ data }) => setRules(data)).catch(() => {});
  }, [sourceId]);
  if (!sourceId || !rules || rules.shifts.length === 0) return null;
  const same = (s) => value && s.start === value.start && s.end === value.end;
  return (
    <Field label="Your shift on this stay">
      <select value={rules.shifts.findIndex(same)} onChange={(e) => onChange(e.target.value === '-1' ? null : rules.shifts[Number(e.target.value)])} className={inputClass}>
        <option value="-1">Not set</option>
        {rules.shifts.map((s, i) => <option key={s.text} value={i}>{s.text}</option>)}
      </select>
    </Field>
  );
}
