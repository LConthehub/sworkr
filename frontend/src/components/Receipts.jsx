import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { money, toDateInput } from '../colors';

const longDate = (day) => new Date(`${day}T12:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });

/** The receipt itself: plain, nothing about sworkr or the work. Printing shows only this. */
export function ReceiptView({ receipt: r }) {
  return (
    <div className="receipt-print rounded-xl border border-gray-200 bg-white p-6 sm:p-8 text-gray-800 max-w-md mx-auto">
      <div className="flex items-start justify-between gap-4">
        <div>
          {r.business && <p className="text-lg font-semibold">{r.business}</p>}
          {r.contact && <p className="text-xs text-gray-500 whitespace-pre-line">{r.contact}</p>}
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wide text-gray-500">Receipt</p>
          <p className="text-sm font-medium tabular-nums">{r.number}</p>
        </div>
      </div>
      <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <dt className="text-gray-500">Date</dt><dd>{longDate(r.issued_on)}</dd>
        {r.billed_to && <><dt className="text-gray-500">Received from</dt><dd>{r.billed_to}</dd></>}
        {r.method && <><dt className="text-gray-500">Paid by</dt><dd>{r.method}</dd></>}
      </dl>
      <div className="mt-6 border-t border-gray-200 pt-3 flex justify-between gap-4 text-sm">
        <span>{r.description}</span>
        <span className="tabular-nums">{money(r.amount, r.currency)}</span>
      </div>
      <div className="mt-2 border-t border-gray-200 pt-3 flex justify-between gap-4 font-semibold">
        <span>Total paid</span>
        <span className="tabular-nums">{money(r.amount, r.currency)}</span>
      </div>
      {r.note && <p className="mt-4 text-xs text-gray-600 whitespace-pre-line">{r.note}</p>}
      {r.footer && <p className="mt-6 text-sm text-gray-600 text-center">{r.footer}</p>}
    </div>
  );
}

/** A receipt on screen, with Print (or Save as PDF from the print window). */
export function ReceiptModal({ receipt, onClose }) {
  return (
    <Modal title={`Receipt ${receipt.number}`} onClose={onClose}>
      <ReceiptView receipt={receipt} />
      <div className="mt-4 flex flex-wrap justify-end gap-2 print:hidden">
        <button onClick={onClose} className={quietButtonClass}>Close</button>
        <button onClick={() => window.print()} className={buttonClass}>Print or save as PDF</button>
      </div>
    </Modal>
  );
}

/** "Receipt" on a paid booking: the form, filled from the booking, then the receipt. */
export function ReceiptMaker({ appointment: a, onClose }) {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState({
    billed_to: '', description: '', amount: a.amount_paid || a.rate || '',
    date: a.scheduled_date ? toDateInput(new Date(a.scheduled_date)) : toDateInput(new Date()),  // the local day, not UTC's method: a.payment_method || '', note: '',
  });
  const [made, setMade] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get('/api/receipts/settings').then(({ data }) => setSettings(data)).catch(() => setSettings({}));
  }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const { data } = await axios.post('/api/receipts', {
        appointment_id: a.id, ...form, amount: Number(form.amount), currency: a.currency,
      });
      setMade(data);
    } catch (err) {
      setError(errorMessage(err, "Couldn't make the receipt"));
    }
  };
  if (made) return <ReceiptModal receipt={made} onClose={onClose} />;
  return (
    <Modal title="Receipt" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {settings && !settings.business && (
          <p className="text-xs text-amber-800 bg-amber-50 rounded-lg px-3 py-2">
            Tip: set the name printed at the top in Settings → Money → Receipts. Until then it's left blank.
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount"><input type="number" min="0.01" step="0.01" required value={form.amount} onChange={set('amount')} className={inputClass} /></Field>
          <Field label="Date"><input type="date" required value={form.date} onChange={set('date')} className={inputClass} /></Field>
        </div>
        <Field label="What for (leave empty for your usual wording)">
          <input value={form.description} onChange={set('description')} placeholder={settings?.service || 'Consulting services'} className={inputClass} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Received from (optional)"><input value={form.billed_to} onChange={set('billed_to')} placeholder="Any name they want" className={inputClass} /></Field>
          <Field label="Paid by"><input value={form.method} onChange={set('method')} placeholder="Cash, card…" className={inputClass} /></Field>
        </div>
        <Field label="Note (optional)"><input value={form.note} onChange={set('note')} className={inputClass} /></Field>
        <p className="text-xs text-gray-500">Only what's here goes on the receipt: nothing about the booking, the client's details or sworkr.</p>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end"><button type="submit" className={buttonClass}>Make receipt</button></div>
      </form>
    </Modal>
  );
}

/** Settings > My work > Receipts: the wording, and receipts already issued. */
export function ReceiptSettings() {
  const [form, setForm] = useState(null);
  const [list, setList] = useState([]);
  const [shown, setShown] = useState(null);
  const [saved, setSaved] = useState('');
  const loadList = useCallback(() => {
    axios.get('/api/receipts').then(({ data }) => setList(data)).catch(() => {});
  }, []);
  useEffect(() => {
    axios.get('/api/receipts/settings').then(({ data }) => setForm(data)).catch(() => {});
    loadList();
  }, [loadList]);
  if (!form) return null;
  const set = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setSaved(''); };
  const save = async (e) => {
    e.preventDefault();
    try {
      const { data } = await axios.put('/api/receipts/settings', form);
      setForm(data);
      setSaved('Saved.');
    } catch (err) {
      setSaved(errorMessage(err, "Couldn't save"));
    }
  };
  const remove = async (r) => {
    if (!window.confirm(`Delete receipt ${r.number}? Its number won't be used again.`)) return;
    await axios.delete(`/api/receipts/${r.id}`).catch(() => {});
    loadList();
  };
  const sample = { number: `${form.prefix || 'R'}-${new Date().getFullYear()}-001`, issued_on: toDateInput(new Date()),
    business: form.business, contact: form.contact, footer: form.footer, description: form.service || 'Services', amount: 300, currency: 'USD', method: 'Cash' };
  return (
    <div className="space-y-5">
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
        <Field label="Name at the top"><input value={form.business} onChange={set('business')} placeholder="e.g. Lake Street Wellness" className={inputClass} /></Field>
        <Field label="Usual wording"><input value={form.service} onChange={set('service')} placeholder="Consulting services" className={inputClass} /></Field>
        <Field label="Contact under the name (optional)"><input value={form.contact} onChange={set('contact')} placeholder="An email or website" className={inputClass} /></Field>
        <Field label="Line at the bottom (optional)"><input value={form.footer} onChange={set('footer')} placeholder="Thank you." className={inputClass} /></Field>
        <Field label="Number starts with"><input value={form.prefix} onChange={set('prefix')} maxLength={8} className={inputClass} /></Field>
        <div className="flex items-end gap-3">
          <button type="submit" className={buttonClass}>Save</button>
          {saved && <span className="text-sm text-gray-600">{saved}</span>}
        </div>
      </form>
      <div>
        <p className="text-xs text-gray-500 mb-2">How it looks (make one from a paid booking: open it in the calendar list and tap Receipt):</p>
        <ReceiptView receipt={sample} />
      </div>
      {list.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-1">Issued</h4>
          <ul className="divide-y divide-gray-100 text-sm">
            {list.map((r) => (
              <li key={r.id} className="py-2 flex flex-wrap items-center gap-3">
                <span className="tabular-nums text-gray-800 w-28">{r.number}</span>
                <span className="text-gray-500">{r.issued_on}</span>
                <span className="flex-1 text-gray-600 truncate">{r.billed_to || ''}</span>
                <span className="tabular-nums">{money(r.amount, r.currency)}</span>
                <button onClick={() => setShown(r)} className="text-xs text-sworkr-600 hover:text-sworkr-800">View</button>
                <button onClick={() => remove(r)} className="text-xs text-gray-400 hover:text-red-600">Delete</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {shown && <ReceiptModal receipt={shown} onClose={() => setShown(null)} />}
    </div>
  );
}
