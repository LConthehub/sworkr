import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { toDateInput } from '../colors';

/** Settings > Health > Supplies: a short stock list with a "running low" mark. */
export function Supplies() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ name: '', have: '', low_at: '2' });
  const load = useCallback(() => {
    axios.get('/api/supplies').then(({ data: d }) => setData(d)).catch(() => setData({ supplies: [], starters: [] }));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const add = async (name, have = 0, lowAt = 2) => {
    await axios.post('/api/supplies', { name, have: Number(have) || 0, low_at: Number(lowAt) || 0 }).catch(() => {});
    setForm({ name: '', have: '', low_at: '2' });
    load();
  };
  const change = async (s, by) => { const { data: rows } = await axios.post(`/api/supplies/${s.id}/change`, { by }); setData({ supplies: rows, starters: [] }); };
  const remove = async (s) => { await axios.delete(`/api/supplies/${s.id}`).catch(() => {}); load(); };
  return (
    <div className="space-y-3">
      {data.starters.length > 0 && (
        <p className="flex flex-wrap items-center gap-2 text-sm text-gray-600">Start with:
          {data.starters.map((n) => <button key={n} type="button" onClick={() => add(n)} className={quietButtonClass}>{n}</button>)}
        </p>
      )}
      <ul className="divide-y divide-gray-100">
        {data.supplies.map((s) => (
          <li key={s.id} className="py-2 flex items-center gap-2">
            <span className="flex-1 text-sm text-gray-800">{s.name}{s.low && <span className="ml-2 text-xs px-1.5 rounded bg-amber-100 text-amber-800">running low</span>}</span>
            <button type="button" onClick={() => change(s, -1)} aria-label={`Used one ${s.name}`} className="w-9 h-9 rounded-lg border border-gray-200 text-gray-700">−</button>
            <span className="w-8 text-center tabular-nums text-sm text-gray-800">{s.have}</span>
            <button type="button" onClick={() => change(s, 1)} aria-label={`One more ${s.name}`} className="w-9 h-9 rounded-lg border border-gray-200 text-gray-700">+</button>
            <button type="button" onClick={() => remove(s)} className="text-xs text-gray-400 hover:text-red-600" aria-label={`Remove ${s.name}`}>✕</button>
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); add(form.name, form.have, form.low_at); }} className="grid grid-cols-2 sm:grid-cols-[1fr_6rem_8rem_auto] gap-2">
        <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="What" aria-label="What" className={`${inputClass} col-span-2 sm:col-span-1`} />
        <input type="number" min="0" value={form.have} onChange={(e) => setForm({ ...form, have: e.target.value })} placeholder="Have" aria-label="How many you have" className={inputClass} />
        <input type="number" min="0" value={form.low_at} onChange={(e) => setForm({ ...form, low_at: e.target.value })} placeholder="Low at" aria-label="Running low at" title="Running low at this many" className={inputClass} />
        <button type="submit" className="col-span-2 sm:col-span-1 text-sm px-3 py-2 rounded-lg bg-sworkr-500 text-white">Add</button>
      </form>
      <p className="text-xs text-gray-500">What's running low shows at the top of your dashboard.</p>
    </div>
  );
}

const BLANK = { happened_on: '', title: '', what: '', who: '', evidence: '' };

/** Settings > Security & privacy > Incident log. */
export function Incidents() {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(() => { axios.get('/api/incidents').then(({ data }) => setRows(data)).catch(() => setRows([])); }, []);
  useEffect(() => { load(); }, [load]);
  if (rows === null) return null;
  const set = (k) => (e) => setEditing({ ...editing, [k]: e.target.value });
  const save = async (e) => {
    e.preventDefault();
    try {
      if (editing.id) await axios.put(`/api/incidents/${editing.id}`, editing);
      else await axios.post('/api/incidents', editing);
      setEditing(null);
      load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this entry? It cannot be brought back.')) return;
    await axios.delete(`/api/incidents/${editing.id}`).catch(() => {});
    setEditing(null);
    load();
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">
        Write down what happened while it's fresh: the date, what was said or done, who, and what you kept (screenshots, messages).
        It stays here, encrypted, and is never sent anywhere. It's yours to use later, if and how you choose.
      </p>
      <ul className="divide-y divide-gray-100">
        {rows.map((r) => (
          <li key={r.id} className="py-2">
            <button type="button" onClick={() => { setError(''); setEditing({ ...BLANK, ...Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v ?? ''])) }); }} className="w-full text-left">
              <span className="text-xs text-gray-500 mr-2">{r.happened_on}</span>
              <span className="text-sm text-gray-800">{r.title}</span>
            </button>
          </li>
        ))}
      </ul>
      <button type="button" onClick={() => { setError(''); setEditing({ ...BLANK, happened_on: toDateInput(new Date()) }); }} className={quietButtonClass}>+ Write one down</button>
      {editing && (
        <Modal title={editing.id ? 'Incident' : 'What happened'} onClose={() => setEditing(null)}>
          <form onSubmit={save} className="space-y-3">
            <div className="grid grid-cols-[auto_1fr] gap-3">
              <Field label="When"><input type="date" required value={editing.happened_on} onChange={set('happened_on')} className={inputClass} /></Field>
              <Field label="In a few words"><input required value={editing.title} onChange={set('title')} className={inputClass} /></Field>
            </div>
            <Field label="What happened"><textarea rows={5} value={editing.what} onChange={set('what')} className={inputClass} /></Field>
            <Field label="Who (a name, a handle, a number, a description)"><input value={editing.who} onChange={set('who')} className={inputClass} /></Field>
            <Field label="What you kept, and where"><textarea rows={2} value={editing.evidence} onChange={set('evidence')} placeholder="e.g. Screenshots of the messages, in my private folder" className={inputClass} /></Field>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex items-center justify-between">
              {editing.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
              <button type="submit" className={buttonClass}>Save</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/** Settings > Security & privacy > Privacy check-up. */
export function PrivacyCheckup() {
  const [data, setData] = useState(null);
  useEffect(() => { axios.get('/api/privacy-checkup').then(({ data: d }) => setData(d)).catch(() => {}); }, []);
  if (!data) return null;
  const tick = async (item, done) => {
    const { data: d } = await axios.post('/api/privacy-checkup', { id: item.id, done });
    setData(d);
  };
  return (
    <div className="space-y-2">
      <p className="text-sm text-gray-600">{data.done} of {data.total} done. Things worth doing once, and looking at again now and then.</p>
      <ul className="space-y-2">
        {data.items.map((i) => (
          <li key={i.id}>
            <label className="flex items-start gap-3 rounded-xl border border-gray-100 px-3 py-2 cursor-pointer">
              <input type="checkbox" checked={!!i.done_on} onChange={(e) => tick(i, e.target.checked)} className="mt-1" />
              <span>
                <span className={`block text-sm font-medium ${i.done_on ? 'text-gray-500 line-through' : 'text-gray-800'}`}>{i.title}</span>
                <span className="block text-xs text-gray-500">{i.how}{i.done_on && ` Done ${i.done_on}.`}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
