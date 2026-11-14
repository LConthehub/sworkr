import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass, Notice } from './Modal';

const FIELD_LABELS = {
  phone: 'Phone number', email: 'Email', handle: 'Handle or username', name: 'Name or alias',
  description: 'What happened', area: 'Area or city', reported_on: 'Date reported', severity: 'Severity',
};

/** Settings: upload a local warning list, see and remove lists, add someone by hand, search. */
export function BlocklistSettings() {
  const [data, setData] = useState({ entries: [], lists: [] });
  const [q, setQ] = useState('');
  const [message, setMessage] = useState(null);
  const [upload, setUpload] = useState(null);     // { csv, headings, mapping, rows, list_name }
  const [manual, setManual] = useState({ phone: '', email: '', handle: '', name: '', description: '', severity: 'warn' });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    axios.get('/api/blocklist', { params: { q: q || undefined, limit: 50 } }).then(({ data: d }) => setData(d)).catch(() => {});
  }, [q]);
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load]);

  const pickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setMessage(null);
    try {
      const csv = await file.text();
      const { data: p } = await axios.post('/api/blocklist/preview', { csv });
      setUpload({ csv, ...p, list_name: file.name.replace(/\.[^.]+$/, '') });
    } catch (err) {
      setMessage({ error: errorMessage(err, "Couldn't read that file. It needs to be a CSV with a heading row.") });
    }
  };

  const runImport = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const { data: r } = await axios.post('/api/blocklist/import', {
        csv: upload.csv, list_name: upload.list_name, mapping: upload.mapping, replace: true,
      });
      setUpload(null);
      setMessage({ ok: `Added ${r.added} ${r.added === 1 ? 'entry' : 'entries'}${r.replaced ? `, replacing the ${r.replaced} from the older copy` : ''}.${r.skipped ? ` ${r.skipped} row${r.skipped === 1 ? ' was' : 's were'} skipped: no phone, email or handle to match on.` : ''}` });
      load();
    } catch (err) {
      setMessage({ error: errorMessage(err, "Couldn't add the list") });
    } finally {
      setBusy(false);
    }
  };

  const addManual = async (e) => {
    e.preventDefault();
    setMessage(null);
    try {
      await axios.post('/api/blocklist', manual);
      setManual({ phone: '', email: '', handle: '', name: '', description: '', severity: 'warn' });
      setMessage({ ok: 'Added.' });
      load();
    } catch (err) {
      setMessage({ error: errorMessage(err, "Couldn't add them") });
    }
  };

  const removeList = async (name) => {
    if (!window.confirm(`Remove the whole list "${name}"?`)) return;
    await axios.delete('/api/blocklist', { params: { list_name: name } }).catch(() => {});
    load();
  };
  const removeEntry = async (entry) => {
    await axios.delete(`/api/blocklist/${entry.id}`).catch(() => {});
    load();
  };

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-sm text-gray-700">
          Upload a list from your local warning group (a CSV file; most spreadsheet apps can save one). Uploading a newer copy
          with the same list name replaces the old one.
        </p>
        <label className={`${quietButtonClass} inline-block cursor-pointer`}>
          Choose a CSV file…
          <input type="file" accept=".csv,text/csv,text/plain" onChange={pickFile} className="sr-only" />
        </label>
      </div>

      {upload && (
        <form onSubmit={runImport} className="rounded-xl border border-gray-200 p-3 space-y-3">
          <Field label="List name (where it came from)">
            <input required value={upload.list_name} onChange={(e) => setUpload({ ...upload, list_name: e.target.value })} className={inputClass} />
          </Field>
          <p className="text-sm text-gray-600">Which column is which? sworkr guessed; change anything it got wrong.</p>
          <div className="grid sm:grid-cols-2 gap-2">
            {Object.entries(FIELD_LABELS).map(([field, label]) => (
              <Field key={field} label={label}>
                <select value={upload.mapping[field] || ''} onChange={(e) => setUpload({ ...upload, mapping: { ...upload.mapping, [field]: e.target.value || null } })} className={inputClass}>
                  <option value="">Not in this file</option>
                  {upload.headings.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </Field>
            ))}
          </div>
          {upload.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="text-xs text-gray-600 min-w-full">
                <thead><tr>{upload.headings.map((h) => <th key={h} className="text-left font-medium px-2 py-1 border-b">{h}</th>)}</tr></thead>
                <tbody>{upload.rows.map((r, i) => <tr key={i}>{upload.headings.map((h) => <td key={h} className="px-2 py-1 border-b border-gray-50 max-w-[12rem] truncate">{r[h]}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-gray-500">Rows without a phone number, email or handle are skipped: a name alone could match the wrong person.</p>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={buttonClass}>{busy ? 'Adding…' : 'Add this list'}</button>
            <button type="button" onClick={() => setUpload(null)} className={quietButtonClass}>Cancel</button>
          </div>
        </form>
      )}
      <Notice message={message} />

      {data.lists.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-1">Your lists</h3>
          <ul className="divide-y divide-gray-100">
            {data.lists.map((l) => (
              <li key={l.list_name} className="flex items-center gap-3 py-2 text-sm">
                <span className="flex-1 text-gray-800">{l.list_name}</span>
                <span className="text-xs text-gray-500">{l.entries} {l.entries === 1 ? 'entry' : 'entries'}</span>
                <button type="button" onClick={() => removeList(l.list_name)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={addManual} className="rounded-xl border border-gray-100 p-3 space-y-2">
        <h3 className="text-sm font-semibold text-gray-700">Add someone yourself</h3>
        <div className="grid sm:grid-cols-3 gap-2">
          <input value={manual.phone} onChange={(e) => setManual({ ...manual, phone: e.target.value })} placeholder="Phone" aria-label="Phone" className={inputClass} />
          <input value={manual.email} onChange={(e) => setManual({ ...manual, email: e.target.value })} placeholder="Email" aria-label="Email" className={inputClass} />
          <input value={manual.handle} onChange={(e) => setManual({ ...manual, handle: e.target.value })} placeholder="Handle" aria-label="Handle" className={inputClass} />
        </div>
        <div className="grid sm:grid-cols-[1fr_2fr_auto] gap-2">
          <input value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} placeholder="Name or alias" aria-label="Name or alias" className={inputClass} />
          <input value={manual.description} onChange={(e) => setManual({ ...manual, description: e.target.value })} placeholder="What happened" aria-label="What happened" className={inputClass} />
          <select value={manual.severity} onChange={(e) => setManual({ ...manual, severity: e.target.value })} aria-label="Severity" className={inputClass}>
            <option value="warn">Warn me</option>
            <option value="block">Never see</option>
          </select>
        </div>
        <button type="submit" disabled={!(manual.phone.trim() || manual.email.trim() || manual.handle.trim())} className={buttonClass}>Add</button>
      </form>

      <div className="space-y-2">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the list" aria-label="Search the bad-date list" className={inputClass} />
        {data.entries.length === 0 ? (
          <p className="text-sm text-gray-400">{q ? 'No one matches.' : 'Nobody on your list yet.'}</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {data.entries.map((e) => (
              <li key={e.id} className="flex items-start gap-3 py-2 text-sm">
                <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${e.severity === 'block' ? 'bg-red-600' : 'bg-amber-500'}`} title={e.severity === 'block' ? 'Never see' : 'Warn me'} />
                <span className="flex-1 min-w-0">
                  <span className="block text-gray-800">{[e.name, e.phone, e.email, e.handle && `@${e.handle}`].filter(Boolean).join(' · ')}</span>
                  <span className="block text-xs text-gray-500">{[e.description, e.area, e.reported_on, e.list_name].filter(Boolean).join(' · ')}</span>
                </span>
                <button type="button" onClick={() => removeEntry(e)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** A warning on a contact (or while typing their details) that matches the bad-date list. */
export function BadDateWarning({ clientId, phone, email, handles }) {
  const [found, setFound] = useState([]);
  const handleKey = (handles || []).join('|');
  useEffect(() => {
    if (!clientId && !phone && !email && !handleKey) { setFound([]); return undefined; }
    const t = setTimeout(() => {
      const params = new URLSearchParams();
      if (clientId) params.set('client_id', clientId);
      if (phone) params.set('phone', phone);
      if (email) params.set('email', email);
      for (const h of handleKey ? handleKey.split('|') : []) if (h) params.append('handle', h);
      axios.get(`/api/blocklist/check?${params}`).then(({ data }) => setFound(data)).catch(() => setFound([]));
    }, 400);
    return () => clearTimeout(t);
  }, [clientId, phone, email, handleKey]);
  if (found.length === 0) return null;
  const blocked = found.some((f) => f.severity === 'block');
  return (
    <div role="alert" className={`rounded-xl px-3 py-2 text-sm ${blocked ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-amber-50 text-amber-900 border border-amber-200'}`}>
      <p className="font-semibold">{blocked ? 'On your bad-date list: never see' : 'Matches your bad-date list'}</p>
      <ul className="mt-1 space-y-0.5">
        {found.slice(0, 5).map((f) => (
          <li key={f.id}>
            {f.list_name} (matched by {f.matched_on}){f.name ? `, listed as ${f.name}` : ''}{f.description ? `: ${f.description}` : ''}{f.reported_on ? ` (${f.reported_on})` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}
