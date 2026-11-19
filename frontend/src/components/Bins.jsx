import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { toDateInput } from '../colors';

const blankItem = () => ({ label: '', quantity: 1, key: Math.random() });

function BinSummary({ bin }) {
  return (
    <span className="block text-xs text-gray-500">
      {[bin.place, bin.where_kept, `${bin.pieces} thing${bin.pieces === 1 ? '' : 's'}`, bin.days_stored != null && `left ${bin.days_stored} day${bin.days_stored === 1 ? '' : 's'} ago`].filter(Boolean).join(' · ')}
    </span>
  );
}

/** Settings > My work > Storage bins. */
export default function Bins() {
  const [bins, setBins] = useState(null);
  const [places, setPlaces] = useState([]);
  const [modal, setModal] = useState(null);
  const [q, setQ] = useState('');
  const [found, setFound] = useState(null);
  const load = useCallback(() => { axios.get('/api/bins').then(({ data }) => setBins(data)).catch(() => setBins([])); }, []);
  useEffect(() => { load(); axios.get('/api/income-sources').then(({ data }) => setPlaces(data.filter((p) => !p.archived))).catch(() => {}); }, [load]);
  useEffect(() => {
    if (!q.trim()) { setFound(null); return undefined; }
    const t = setTimeout(() => axios.get('/api/bins/find', { params: { q } }).then(({ data }) => setFound(data)).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);
  if (!bins) return null;
  const done = () => { setModal(null); load(); };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {bins.length > 0 && <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Which bin is it in?" aria-label="Find something in a bin" className={`${inputClass} flex-1 min-w-40`} />}
        <button type="button" onClick={() => setModal({ bin: { label: '', source_id: '', where_kept: '', stored_on: '', notes: '', items: [blankItem()] } })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New bin</button>
      </div>
      {found && (
        <ul className="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700 space-y-0.5">
          {found.length === 0 ? <li className="text-gray-500">Not in any bin.</li>
            : found.map((f, i) => <li key={i}><b>{f.item}</b>{f.quantity > 1 ? ` (${f.quantity})` : ''}: {f.bin}{f.place ? ` at ${f.place}` : ''}{f.where_kept ? `, ${f.where_kept}` : ''}</li>)}
        </ul>
      )}
      {bins.length === 0 ? (
        <p className="text-sm text-gray-400 py-2">No bins yet. When a place keeps your things between stays, list what's in each bin here and print a label for it.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {bins.map((b) => (
            <li key={b.id} className="py-2 flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => setModal({ bin: { ...b, source_id: b.source_id ? String(b.source_id) : '', where_kept: b.where_kept || '', stored_on: b.stored_on || '', notes: b.notes || '', items: [...b.items.map((i) => ({ ...i, key: i.id })), blankItem()] } })} className="flex-1 min-w-40 text-left">
                <span className="block text-sm font-medium text-gray-800">{b.label}</span>
                <BinSummary bin={b} />
              </button>
              <button type="button" onClick={() => setModal({ label: b })} className={quietButtonClass}>Label</button>
            </li>
          ))}
        </ul>
      )}
      {modal?.bin && (
        <Modal title={modal.bin.id ? modal.bin.label : 'New bin'} onClose={() => setModal(null)} wide>
          <BinForm bin={modal.bin} places={places} onDone={done} />
        </Modal>
      )}
      {modal?.label && (
        <Modal title={`Label for ${modal.label.label}`} onClose={() => setModal(null)}>
          <BinLabel bin={modal.label} />
        </Modal>
      )}
    </div>
  );
}

function BinForm({ bin, places, onDone }) {
  const [form, setForm] = useState(bin);
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const setItem = (i, patch) => {
    const items = form.items.map((it, j) => (j === i ? { ...it, ...patch } : it));
    // Typing in the last row adds a fresh one under it.
    if (i === items.length - 1 && items[i].label.trim()) items.push(blankItem());
    setForm({ ...form, items });
  };
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      label: form.label, source_id: form.source_id ? Number(form.source_id) : null, where_kept: form.where_kept, stored_on: form.stored_on || null,
      notes: form.notes, items: form.items.filter((i) => i.label.trim()).map((i) => ({ label: i.label, quantity: Number(i.quantity) || 1 })),
    };
    try {
      if (form.id) await axios.put(`/api/bins/${form.id}`, body);
      else await axios.post('/api/bins', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this bin and its list? It cannot be brought back.')) return;
    await axios.delete(`/api/bins/${form.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Name *"><input required autoFocus={!form.id} value={form.label} onChange={set('label')} placeholder="e.g. Blue tote, Bin 2" className={inputClass} /></Field>
        <Field label="Kept at">
          <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
            <option value="">Somewhere else</option>
            {places.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Where exactly"><input value={form.where_kept} onChange={set('where_kept')} placeholder="e.g. Storage room, top shelf" className={inputClass} /></Field>
        <Field label="Left there on">
          <input type="date" value={form.stored_on} onChange={set('stored_on')} className={inputClass} />
          {!form.stored_on && <button type="button" onClick={() => setForm({ ...form, stored_on: toDateInput(new Date()) })} className="mt-1 text-xs text-sworkr-600">Today</button>}
        </Field>
      </div>
      {form.storage_rules && <p className="text-xs rounded-lg bg-gray-50 px-3 py-2 text-gray-600">This place's storage rules: {form.storage_rules}</p>}
      <div>
        <p className="text-sm font-medium text-gray-700 mb-1">What's in it</p>
        <ul className="space-y-1">
          {form.items.map((it, i) => (
            <li key={it.key} className="flex items-center gap-2">
              <input value={it.label} onChange={(e) => setItem(i, { label: e.target.value })} placeholder={i === form.items.length - 1 ? 'Add something…' : ''} aria-label="What" className={inputClass} />
              <input type="number" min="1" value={it.quantity} onChange={(e) => setItem(i, { quantity: e.target.value })} aria-label="How many" className={`${inputClass} !w-20`} />
            </li>
          ))}
        </ul>
      </div>
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} placeholder="e.g. Lock code, who has the key" className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {form.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

/** A label to print and tape to the bin: its name and a QR code that opens the bin in sworkr (login needed). */
function BinLabel({ bin }) {
  const [label, setLabel] = useState(null);
  const [withName, setWithName] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get(`/api/bins/${bin.id}/label`, { params: { origin: window.location.origin } }).then(({ data }) => setLabel(data))
      .catch((err) => setError(errorMessage(err, "Couldn't make the label")));
  }, [bin.id]);
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!label) return null;
  const local = /^(localhost|127\.|\[::1\])/.test(window.location.hostname);
  const print = () => {
    const w = window.open('', '_blank', 'width=420,height=520');
    if (!w) return;
    w.document.write(`<title>Label</title><body style="margin:0;font-family:sans-serif;text-align:center;padding:24px">
      <img src="${label.qr}" style="width:260px;height:260px" alt="">${withName ? `<p style="font-size:28px;font-weight:700;margin:8px 0 0"></p>` : ''}</body>`);
    if (withName) w.document.querySelector('p').textContent = bin.label;
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 300);
  };
  return (
    <div className="space-y-3 text-center">
      <img src={label.qr} alt="QR code for this bin" className="mx-auto w-52 h-52" />
      {withName && <p className="text-lg font-bold text-gray-800">{bin.label}</p>}
      <label className="flex items-center justify-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={withName} onChange={(e) => setWithName(e.target.checked)} /> Print the bin's name under the code</label>
      <ul className="text-xs text-gray-500 text-left list-disc pl-5 space-y-1">
        <li>The code holds only a link. Scanning it opens this bin's list in Sworkr, and only for you, after you log in. Anyone else sees a login page.</li>
        <li>Use a name that says nothing about you, and never your legal name.</li>
        {local
          ? <li className="text-amber-700">You're on this computer's own address, so the code would only work on this computer. Open Sworkr at its Tailscale or web address and make the label there, so your phone can scan it.</li>
          : <li>It opens {window.location.origin}. If Sworkr's address changes, print a new label.</li>}
      </ul>
      <button type="button" onClick={print} className={buttonClass}>Print the label</button>
    </div>
  );
}

/** What a scanned label opens: /bins/<code>. */
export function BinPage() {
  const { code } = useParams();
  const [bin, setBin] = useState(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => { axios.get(`/api/bins/code/${code}`).then(({ data }) => setBin(data)).catch(() => setMissing(true)); }, [code]);
  return (
    <div className="max-w-xl mx-auto bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
      {missing ? <p className="text-sm text-gray-600">This label isn't one of your bins.</p> : !bin ? null : (
        <>
          <h1 className="text-xl font-bold text-gray-800">{bin.label}</h1>
          <BinSummary bin={bin} />
          {bin.items.length === 0 ? <p className="text-sm text-gray-400">Nothing listed in it yet.</p> : (
            <ul className="divide-y divide-gray-100">
              {bin.items.map((i) => <li key={i.id} className="py-1.5 flex justify-between gap-2 text-sm text-gray-800"><span>{i.label}</span>{i.quantity > 1 && <span className="text-gray-500">× {i.quantity}</span>}</li>)}
            </ul>
          )}
          {bin.notes && <p className="text-sm text-gray-600 whitespace-pre-wrap">{bin.notes}</p>}
          {bin.storage_rules && <p className="text-xs rounded-lg bg-gray-50 px-3 py-2 text-gray-600">Storage rules here: {bin.storage_rules}</p>}
        </>
      )}
      <Link to="/account/work" className="inline-block text-sm text-sworkr-600 hover:text-sworkr-800">All bins →</Link>
    </div>
  );
}
