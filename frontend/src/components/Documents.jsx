import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { PersonaSelect } from './Personas';

const KINDS = {
  license: 'License', work_card: 'Work card', id: 'ID', passport: 'Passport', health_card: 'Health card',
  verification: 'Platform ID check', insurance: 'Insurance', other: 'Other',
};
const BLANK = { name: '', kind: 'license', issued_on: '', expires_on: '', remind_days_before: 30, source_id: '', persona_id: '', notes: '' };

const left = (days) => (days == null ? 'No expiry date'
  : days < 0 ? `Ran out ${-days} day${days === -1 ? '' : 's'} ago`
    : days === 0 ? 'Runs out today' : `${days} day${days === 1 ? '' : 's'} left`);
const tone = (days) => (days == null ? 'text-gray-500' : days < 0 ? 'text-red-700 font-semibold' : days <= 30 ? 'text-amber-700 font-semibold' : 'text-gray-600');

/** Licenses, work cards, ID and the like: when each runs out, with a reminder before. */
export default function DocumentsSettings() {
  const [data, setData] = useState(null);
  const [places, setPlaces] = useState([]);
  const [editing, setEditing] = useState(null);
  const load = useCallback(() => {
    axios.get('/api/documents').then(({ data: d }) => setData(d)).catch(() => setData({ documents: [], from_places: [] }));
  }, []);
  useEffect(() => {
    load();
    axios.get('/api/income-sources').then(({ data: d }) => setPlaces(d)).catch(() => {});
  }, [load]);

  if (!data) return <p className="text-sm text-gray-400">Loading…</p>;
  if (editing) return <DocumentForm doc={editing} places={places} onDone={() => { setEditing(null); load(); }} />;
  const rows = [
    ...data.documents.map((d) => ({ ...d, key: `d${d.id}` })),
    ...data.from_places.map((c) => ({ ...c, key: `c${c.charge_id}`, fromPlace: true })),
  ].sort((a, b) => (a.expires_on || '9999').localeCompare(b.expires_on || '9999'));

  return (
    <div className="space-y-3">
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing yet.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {rows.map((r) => (
            <li key={r.key} className="flex items-center gap-3 py-2 text-sm">
              <span className="flex-1 min-w-0">
                <span className="block text-gray-800">{r.name}</span>
                <span className="block text-xs text-gray-500">
                  {[r.fromPlace ? `From ${r.place_name}'s charges` : KINDS[r.kind], !r.fromPlace && r.place_name, r.expires_on].filter(Boolean).join(' · ')}
                </span>
              </span>
              <span className={`text-xs ${tone(r.days_left)}`}>{left(r.days_left)}</span>
              {r.fromPlace
                ? <span className="text-xs text-gray-400 w-10" title="Change it on the place, on the Money page">Place</span>
                : <button type="button" onClick={() => setEditing(r)} className="text-xs text-sworkr-600 hover:text-sworkr-800 w-10">Edit</button>}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => setEditing(BLANK)} className={quietButtonClass}>+ Add a document</button>
      <p className="text-xs text-gray-500">
        Renewal dates you set on a place's charges (a license paid to a brothel) show here too. sworkr keeps only names
        and dates: there's no place for ID or license numbers, on purpose.
      </p>
    </div>
  );
}

function DocumentForm({ doc, places, onDone }) {
  const [form, setForm] = useState({
    ...BLANK, ...doc,
    issued_on: doc.issued_on || '', expires_on: doc.expires_on || '', notes: doc.notes || '',
    source_id: doc.source_id ? String(doc.source_id) : '', persona_id: doc.persona_id ? String(doc.persona_id) : '',
  });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const body = {
      name: form.name.trim() || KINDS[form.kind], kind: form.kind, issued_on: form.issued_on || null, expires_on: form.expires_on || null,
      remind_days_before: Number(form.remind_days_before) || 0, source_id: form.source_id ? Number(form.source_id) : null,
      persona_id: form.persona_id ? Number(form.persona_id) : null, notes: form.notes || null,
    };
    try {
      if (doc.id) await axios.put(`/api/documents/${doc.id}`, body); else await axios.post('/api/documents', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete ${doc.name}?`)) return;
    await axios.delete(`/api/documents/${doc.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="What it is">
          <select value={form.kind} onChange={set('kind')} className={inputClass}>
            {Object.entries(KINDS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Name">
          <input value={form.name} onChange={set('name')} placeholder="e.g. County work card" className={inputClass} />
        </Field>
        <Field label="Issued on">
          <input type="date" value={form.issued_on} onChange={set('issued_on')} className={inputClass} />
        </Field>
        <Field label="Runs out on">
          <input type="date" value={form.expires_on} onChange={set('expires_on')} className={inputClass} />
        </Field>
        <Field label="Remind me (days before)">
          <input type="number" min="0" max="365" value={form.remind_days_before} onChange={set('remind_days_before')} className={inputClass} />
        </Field>
        <Field label="For a place (optional)">
          <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
            <option value="">None</option>
            {places.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
      </div>
      <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Under persona (optional)" />
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} placeholder="e.g. Renew at the county office, bring two photos" className={inputClass} />
      </Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center gap-2">
        <button type="submit" className={buttonClass}>{doc.id ? 'Save' : 'Add'}</button>
        <button type="button" onClick={onDone} className={quietButtonClass}>Cancel</button>
        {doc.id && <button type="button" onClick={remove} className="ml-auto text-sm text-red-500 hover:text-red-700">Delete</button>}
      </div>
    </form>
  );
}
