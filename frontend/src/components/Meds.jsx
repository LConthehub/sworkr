import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { toDateInput } from '../colors';

const METHODS = {
  pill: 'Pill (daily)', patch: 'Patch (weekly)', ring: 'Ring (3 weeks in, 1 out)', shot: 'Shot (every 12 weeks)',
  injection: 'Injection I give myself (GLP-1, hormones…)',
  implant: 'Implant', iud: 'IUD', condoms: 'Condoms', daily: 'Other daily med (PrEP, hormones…)',
  as_needed: 'As needed (doxyPEP…)', other: 'Other',
};
// What "changed" means for each method, as a button.
const CHANGE_LABEL = { patch: 'New patch on', ring: 'Ring in/out', shot: 'Had the shot', implant: 'New implant', iud: 'New IUD', injection: 'Injected' };
const DEFAULT_SITES = 'Left belly, Right belly, Left thigh, Right thigh, Left arm, Right arm';
const BLANK = { name: '', method: 'pill', started_on: toDateInput(new Date()), replace_by: '', refill_every_days: '', cost: '', discreet: true, active: true, notes: '' };

const dateText = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });

/** Birth control and regular meds: what you take, what's due next, and one-tap logging. */
export default function MedsSettings() {
  const [meds, setMeds] = useState(null);
  const [editing, setEditing] = useState(null);   // a med, or BLANK for a new one
  const [error, setError] = useState('');

  const load = useCallback(() => {
    axios.get('/api/meds').then(({ data }) => setMeds(data)).catch(() => setMeds([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const log = async (m, kind) => {
    setError('');
    try {
      await axios.post(`/api/meds/${m.id}/log`, { kind });
      load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't log it"));
    }
  };

  if (meds === null) return <p className="text-sm text-gray-400">Loading…</p>;
  if (editing) return <MedForm med={editing} onDone={() => { setEditing(null); load(); }} />;

  return (
    <div className="space-y-3">
      {meds.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing yet. Add your birth control, PrEP or anything else you take on a schedule.</p>
      ) : (
        <ul className="space-y-2">
          {meds.map((m) => {
            const s = m.status;
            const daily = ['pill', 'daily'].includes(m.method);
            return (
              <li key={m.id} className={`rounded-xl border border-gray-100 p-3 ${m.active ? '' : 'opacity-60'}`}>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-gray-800">{m.name}</span>
                  <span className="text-xs text-gray-500">{METHODS[m.method]}{m.active ? '' : ' · stopped'}</span>
                  <button type="button" onClick={() => setEditing(m)} className="ml-auto text-xs text-sworkr-600 hover:text-sworkr-800">Edit</button>
                </div>
                {m.active && (
                  <p className="text-sm text-gray-600 mt-1">
                    {daily && (s.taken_today ? '✓ Taken today.' : 'Not logged today.')}
                    {!daily && s.next && `${s.next.what}: ${dateText(s.next.on)}.`}
                    {s.ring && ` Ring is ${s.ring}.`}
                    {s.refill_on && ` Refill by ${dateText(s.refill_on)}.`}
                    {m.method === 'injection' && (s.next_site || s.dose) && (
                      <span className="block">{[s.next_site && `Next site: ${s.next_site}`, s.dose && `dose ${s.dose}`].filter(Boolean).join(' · ')}{s.last_site && ` (last: ${s.last_site})`}</span>
                    )}
                  </p>
                )}
                {m.active && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {daily && !s.taken_today && <button type="button" onClick={() => log(m, 'taken')} className={buttonClass}>Took it</button>}
                    {daily && <button type="button" onClick={() => log(m, 'missed')} className={quietButtonClass}>Missed one</button>}
                    {CHANGE_LABEL[m.method] && <button type="button" onClick={() => log(m, 'changed')} className={quietButtonClass}>{CHANGE_LABEL[m.method]} today</button>}
                    {m.refill_every_days && <button type="button" onClick={() => log(m, 'refilled')} className={quietButtonClass}>Refilled today</button>}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <button type="button" onClick={() => setEditing(BLANK)} className={quietButtonClass}>+ Add</button>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <p className="text-xs text-gray-500">
        sworkr adds a reminder task for the next change, shot, replacement or refill (not for daily pills: a phone alarm does that
        better). Reminder titles just say “Health reminder” unless you turn that off.
      </p>
    </div>
  );
}

function MedForm({ med, onDone }) {
  const [form, setForm] = useState({
    ...BLANK, ...med,
    started_on: med.started_on || '', replace_by: med.replace_by || '',
    refill_every_days: med.refill_every_days ?? '', cost: med.cost ?? '', notes: med.notes || '',
    every_days: med.every_days ?? 7,
    sites_text: (med.sites && med.sites.length ? med.sites : []).join(', ') || DEFAULT_SITES,
    doses: (med.doses || []).map((d) => ({ dose: d.dose, weeks: d.weeks ?? '' })),
  });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const body = {
      name: form.name.trim() || METHODS[form.method].replace(/ \(.*$/, ''), method: form.method,
      started_on: form.started_on || null, replace_by: form.replace_by || null,
      refill_every_days: form.refill_every_days === '' ? null : Number(form.refill_every_days),
      cost: form.cost === '' ? null : Number(form.cost), discreet: form.discreet, active: form.active, notes: form.notes || null,
      ...(form.method === 'injection' ? {
        every_days: Number(form.every_days) || 7,
        sites: form.sites_text.split(',').map((x) => x.trim()).filter(Boolean),
        doses: form.doses.filter((d) => d.dose.trim()).map((d) => ({ dose: d.dose.trim(), weeks: d.weeks === '' ? null : Number(d.weeks) })),
      } : {}),
    };
    try {
      if (med.id) await axios.put(`/api/meds/${med.id}`, body); else await axios.post('/api/meds', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete ${med.name} and its log?`)) return;
    await axios.delete(`/api/meds/${med.id}`).catch(() => {});
    onDone();
  };
  const firstDayLabel = { ring: 'First day the ring went in', patch: 'Last patch change', shot: 'Last shot', implant: 'Put in on', iud: 'Put in on', injection: 'First injection (the plan counts from here)' }[form.method] || 'Started on';
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="What it is">
          <select value={form.method} onChange={set('method')} className={inputClass}>
            {Object.entries(METHODS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Name">
          <input value={form.name} onChange={set('name')} placeholder="e.g. Pill, PrEP, Depo" className={inputClass} />
        </Field>
        <Field label={firstDayLabel}>
          <input type="date" value={form.started_on} onChange={set('started_on')} className={inputClass} />
        </Field>
        {['implant', 'iud'].includes(form.method) && (
          <Field label="Replace by">
            <input type="date" value={form.replace_by} onChange={set('replace_by')} className={inputClass} />
          </Field>
        )}
        {form.method === 'injection' && (
          <>
            <Field label="Every (days)">
              <input type="number" min="1" max="120" value={form.every_days} onChange={set('every_days')} placeholder="7 = weekly" className={inputClass} />
            </Field>
            <Field label="Sites to rotate through (in order)">
              <input value={form.sites_text} onChange={set('sites_text')} className={inputClass} />
            </Field>
            <div className="sm:col-span-2 space-y-1.5">
              <p className="text-sm text-gray-700">Dose steps <span className="text-xs text-gray-500">(from your prescriber's plan; leave the last one's weeks empty to stay on it)</span></p>
              {form.doses.map((d, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <input value={d.dose} onChange={(e) => setForm({ ...form, doses: form.doses.map((x, j) => (j === i ? { ...x, dose: e.target.value } : x)) })} placeholder="e.g. 0.25 mg" aria-label="Dose" className={`${inputClass} w-32`} />
                  <span className="text-gray-500">for</span>
                  <input type="number" min="1" max="520" value={d.weeks} onChange={(e) => setForm({ ...form, doses: form.doses.map((x, j) => (j === i ? { ...x, weeks: e.target.value } : x)) })} aria-label="Weeks" className={`${inputClass} w-20`} />
                  <span className="text-gray-500">weeks</span>
                  <button type="button" onClick={() => setForm({ ...form, doses: form.doses.filter((_, j) => j !== i) })} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                </div>
              ))}
              <button type="button" onClick={() => setForm({ ...form, doses: [...form.doses, { dose: '', weeks: '' }] })} className="text-xs text-sworkr-600 hover:text-sworkr-800">+ A dose step</button>
            </div>
          </>
        )}
        <Field label="Refill every (days, optional)">
          <input type="number" min="1" max="400" value={form.refill_every_days} onChange={set('refill_every_days')} placeholder="e.g. 28 or 90" className={inputClass} />
        </Field>
        <Field label="A refill costs ($, optional)">
          <input type="number" min="0" step="0.01" value={form.cost} onChange={set('cost')} className={inputClass} />
        </Field>
      </div>
      <label className="flex items-start gap-2 text-sm text-gray-700">
        <input type="checkbox" className="mt-1" checked={form.discreet} onChange={set('discreet')} />
        <span>Discreet<span className="block text-xs text-gray-500">Reminders and refill expenses just say “Health reminder” / “Health refill”.</span></span>
      </label>
      {med.id && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.active} onChange={set('active')} /> Still taking it
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center gap-2">
        <button type="submit" className={buttonClass}>{med.id ? 'Save' : 'Add'}</button>
        <button type="button" onClick={onDone} className={quietButtonClass}>Cancel</button>
        {med.id && <button type="button" onClick={remove} className="ml-auto text-sm text-red-500 hover:text-red-700">Delete</button>}
      </div>
    </form>
  );
}
