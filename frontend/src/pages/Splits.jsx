import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass } from '../components/Modal';
import ClientForm from '../components/ClientForm';
import { dayLabel, money, toDateInput } from '../colors';

const when = (iso) => (iso ? dayLabel(new Date(iso.length === 10 ? `${iso}T12:00:00` : iso), { month: 'short', day: 'numeric', year: 'numeric' }) : '');
const TYPE_LABELS = { appointment: 'Booking', income: 'Income', expense: 'Cost', settlement: 'Settled up' };

function standing(balance) {
  if (Math.abs(balance) < 0.005) return { text: 'All square', className: 'text-gray-500' };
  return balance > 0
    ? { text: `Owes you ${money(balance)}`, className: 'text-emerald-700' }
    : { text: `You owe ${money(-balance)}`, className: 'text-amber-700' };
}

/**
 * Working with other workers, kept privately: who owes whom from shared bookings, content and costs,
 * settling up, and split agreements. Nothing here is shared with anyone.
 */
export default function Splits() {
  const [partners, setPartners] = useState(null);
  const [agreements, setAgreements] = useState([]);
  const [open, setOpen] = useState(null); // a partner id
  const [modal, setModal] = useState(null); // 'partner' | { agreement }
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const [p, a] = await Promise.all([axios.get('/api/partners'), axios.get('/api/agreements')]);
      setPartners(p.data);
      setAgreements(a.data);
      setError('');
    } catch (err) {
      if (err?.response?.status !== 401) setError(errorMessage(err, "Couldn't load your collaborators."));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!partners) return <div className="bg-white rounded-2xl shadow-lg p-6 text-sm text-gray-400">{error || 'Loading…'}</div>;

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
          <h2 className="text-xl font-bold text-gray-800">Splits with collaborators</h2>
          <button onClick={() => setModal('partner')} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ Add a collaborator</button>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Split a booking, income or cost from its form ("Split with a collaborator"). sworkr keeps track of who owes whom.
          This is private: only you see it, and collaborators aren't told anything.
        </p>
        {partners.length === 0 ? (
          <p className="text-sm text-gray-400 py-6 text-center">No collaborators yet. Add another worker you do duos, parties or content with.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {partners.map((p) => {
              const s = standing(p.balance);
              return (
                <li key={p.id}>
                  <button onClick={() => setOpen(open === p.id ? null : p.id)} className="w-full flex flex-wrap items-center gap-x-3 gap-y-1 py-3 text-left hover:bg-gray-50 rounded-lg px-1">
                    <span className="font-medium text-gray-800">{p.display_name}</span>
                    {p.industry && <span className="text-xs text-gray-400">{p.industry}</span>}
                    <span className="text-xs text-gray-400">{p.shared} shared</span>
                    <span className={`ml-auto font-semibold ${s.className}`}>{s.text}</span>
                  </button>
                  {open === p.id && <Ledger partner={p} onChanged={load} />}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
          <h2 className="font-semibold text-gray-800">Split agreements</h2>
          <button onClick={() => setModal({ agreement: null })} disabled={partners.length === 0} className="text-sm text-sworkr-600 hover:text-sworkr-800 disabled:opacity-40">+ New agreement</button>
        </div>
        <p className="text-sm text-gray-500 mb-3">Reusable splits, so a duo booking or a collab set fills itself in.</p>
        {agreements.length === 0 ? (
          <p className="text-sm text-gray-400">None yet. For example: "Jade & me: bookings 50/50, content 60/40, costs split evenly".</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {agreements.map((a) => (
              <li key={a.id}>
                <button onClick={() => setModal({ agreement: a })} className={`w-full text-left rounded-xl border border-gray-100 px-3 py-2 hover:bg-gray-50 ${a.active ? '' : 'opacity-60'}`}>
                  <span className="block text-sm font-medium text-gray-800">{a.name}{!a.active && <span className="text-xs text-gray-400"> · not in use</span>}</span>
                  <span className="block text-xs text-gray-500">
                    You: bookings {a.mine.booking}% · content {a.mine.content}% · costs {a.mine.costs}%
                  </span>
                  <span className="block text-xs text-gray-400">{a.parties.map((p) => `${p.partner_name} ${p.booking_pct}/${p.content_pct}/${p.costs_pct}%`).join(' · ')}</span>
                  {a.notes && <span className="block text-xs text-gray-400 truncate">{a.notes}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {modal === 'partner' && (
        <Modal title="New collaborator" onClose={() => setModal(null)}>
          <ClientForm initial={{ role: 'partner' }} onSaved={() => { setModal(null); load(); }} />
        </Modal>
      )}
      {modal && modal !== 'partner' && (
        <Modal title={modal.agreement ? 'Edit agreement' : 'New split agreement'} onClose={() => setModal(null)}>
          <AgreementForm agreement={modal.agreement} partners={partners} onSaved={() => { setModal(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}

function Ledger({ partner, onChanged }) {
  const [book, setBook] = useState(null);
  const [form, setForm] = useState({ amount: '', direction: 'paid_them', date: toDateInput(new Date()), note: '' });
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/partners/${partner.id}/ledger`).then(({ data }) => {
      setBook(data);
      if (Math.abs(data.balance) >= 0.005) {
        setForm((f) => ({ ...f, amount: Math.abs(data.balance).toFixed(2), direction: data.balance < 0 ? 'paid_them' : 'they_paid' }));
      }
    }).catch(() => {});
  }, [partner.id]);
  useEffect(() => { load(); }, [load]);

  const settle = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await axios.post(`/api/partners/${partner.id}/settlements`, { ...form, amount: Number(form.amount), note: form.note.trim() || null });
      setForm((f) => ({ ...f, note: '' }));
      load();
      onChanged();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const undo = async (entry) => {
    if (!window.confirm('Remove this settle-up payment?')) return;
    await axios.delete(`/api/settlements/${entry.id}`).catch(() => {});
    load();
    onChanged();
  };

  if (!book) return <p className="text-sm text-gray-400 px-1 pb-3">Loading…</p>;
  return (
    <div className="px-1 pb-4 space-y-3">
      <form onSubmit={settle} className="flex flex-wrap items-end gap-2 rounded-xl bg-gray-50 px-3 py-2">
        <Field label="Settle up">
          <select value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })} className={`${inputClass} bg-white`}>
            <option value="paid_them">I paid {partner.display_name}</option>
            <option value="they_paid">{partner.display_name} paid me</option>
          </select>
        </Field>
        <Field label="Amount ($)">
          <input type="number" min="0.01" step="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={`${inputClass} bg-white !w-28`} />
        </Field>
        <Field label="Date">
          <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={`${inputClass} bg-white`} />
        </Field>
        <Field label="Note">
          <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="e.g. Cash" className={`${inputClass} bg-white !w-32`} />
        </Field>
        <button type="submit" className={buttonClass}>Save</button>
        {error && <p className="w-full text-sm text-red-600">{error}</p>}
      </form>
      {book.entries.length === 0 ? (
        <p className="text-sm text-gray-400">Nothing shared with {partner.display_name} yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[560px]">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="py-1.5 pr-2 font-medium">Date</th>
                <th className="py-1.5 pr-2 font-medium">What</th>
                <th className="py-1.5 px-1 font-medium text-right">Total</th>
                <th className="py-1.5 px-1 font-medium text-right">Theirs</th>
                <th className="py-1.5 px-1 font-medium text-right">Yours</th>
                <th className="py-1.5 px-1 font-medium text-right">Effect</th>
              </tr>
            </thead>
            <tbody>
              {book.entries.map((e) => (
                <tr key={`${e.type}-${e.id}`} className="border-b border-gray-50 align-top">
                  <td className="py-1.5 pr-2 text-gray-500 whitespace-nowrap">{when(e.date)}</td>
                  <td className="py-1.5 pr-2">
                    <span className="text-gray-800">{e.description}</span>
                    <span className="block text-[11px] text-gray-400">
                      {TYPE_LABELS[e.type]} · {e.why}{e.pending && ' · payout pending'}
                      {e.type === 'settlement' && <button onClick={() => undo(e)} className="ml-2 text-red-400 hover:text-red-600">remove</button>}
                    </span>
                  </td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{money(e.total)}</td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{e.their_share == null ? '' : money(e.their_share)}</td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{e.your_share == null ? '' : money(e.your_share)}</td>
                  <td className={`py-1.5 px-1 text-right font-medium ${e.effect > 0 ? 'text-emerald-700' : e.effect < 0 ? 'text-amber-700' : 'text-gray-400'}`}>
                    {e.effect > 0 ? '+' : ''}{money(e.effect)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-400 mt-2">+ means {partner.display_name} owes you more; − means you owe more. <Link to={`/contacts/${partner.id}`} className="text-sworkr-600">Open {partner.display_name}'s contact page</Link></p>
        </div>
      )}
    </div>
  );
}

function AgreementForm({ agreement, partners, onSaved }) {
  const [form, setForm] = useState({ name: agreement?.name || '', notes: agreement?.notes || '', active: agreement ? agreement.active : true });
  const [parties, setParties] = useState(agreement?.parties.map((p) => ({ ...p })) || [{ partner_id: partners[0]?.id || '', booking_pct: 50, content_pct: 50, costs_pct: 50 }]);
  const [error, setError] = useState('');
  const setParty = (i, k, v) => setParties(parties.map((p, j) => (j === i ? { ...p, [k]: v } : p)));
  const mine = (k) => 100 - parties.reduce((s, p) => s + (Number(p[k]) || 0), 0);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const body = {
      ...form, name: form.name.trim(), notes: form.notes.trim() || null,
      parties: parties.filter((p) => p.partner_id).map((p) => ({
        partner_id: Number(p.partner_id), booking_pct: Number(p.booking_pct) || 0, content_pct: Number(p.content_pct) || 0, costs_pct: Number(p.costs_pct) || 0,
      })),
    };
    try {
      if (agreement) await axios.put(`/api/agreements/${agreement.id}`, body);
      else await axios.post('/api/agreements', body);
      onSaved();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the agreement'));
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete "${agreement.name}"? Splits already made with it stay as they are.`)) return;
    await axios.delete(`/api/agreements/${agreement.id}`).catch(() => {});
    onSaved();
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Name *">
        <input required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Jade & me" className={inputClass} />
      </Field>
      <p className="text-xs text-gray-500">Each collaborator's share, in percent. Whatever's left is yours.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500">
              <th className="pb-1 font-medium">Collaborator</th>
              <th className="pb-1 font-medium">Bookings %</th>
              <th className="pb-1 font-medium">Content %</th>
              <th className="pb-1 font-medium">Costs %</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {parties.map((p, i) => (
              <tr key={i}>
                <td className="pr-2 py-1">
                  <select value={p.partner_id} onChange={(e) => setParty(i, 'partner_id', e.target.value)} className={inputClass} aria-label="Collaborator">
                    <option value="">Choose…</option>
                    {partners.map((x) => <option key={x.id} value={x.id}>{x.display_name}</option>)}
                  </select>
                </td>
                {['booking_pct', 'content_pct', 'costs_pct'].map((k) => (
                  <td key={k} className="pr-2 py-1">
                    <input type="number" min="0" max="100" step="0.1" value={p[k]} onChange={(e) => setParty(i, k, e.target.value)} className={`${inputClass} !w-20`} aria-label={k} />
                  </td>
                ))}
                <td><button type="button" onClick={() => setParties(parties.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500" aria-label="Remove">✕</button></td>
              </tr>
            ))}
            <tr className="text-gray-600">
              <td className="pr-2 py-1 text-xs">You get</td>
              {['booking_pct', 'content_pct', 'costs_pct'].map((k) => (
                <td key={k} className={`pr-2 py-1 text-sm font-medium ${mine(k) < 0 ? 'text-red-600' : ''}`}>{Math.round(mine(k) * 10) / 10}%</td>
              ))}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <button type="button" onClick={() => setParties([...parties, { partner_id: '', booking_pct: 0, content_pct: 0, costs_pct: 0 }])} className="text-xs text-sworkr-600 hover:text-sworkr-800">
        + Another collaborator (for a trio or a party)
      </button>
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="When and how you agreed it, who pays for what…" className={inputClass} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> In use
      </label>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {agreement ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete agreement</button> : <span />}
        <button type="submit" className={buttonClass}>{agreement ? 'Save changes' : 'Add agreement'}</button>
      </div>
    </form>
  );
}
