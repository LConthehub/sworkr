import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { PersonaSelect } from './Personas';
import { fetchAll } from '../api';
import { dayLabel, fromDateInput, money, toDateInput } from '../colors';

const STATUS = {
  requested: { label: 'Requested', badge: 'bg-amber-100 text-amber-800' },
  quoted: { label: 'Quoted', badge: 'bg-sky-100 text-sky-700' },
  to_make: { label: 'To make', badge: 'bg-sworkr-50 text-sworkr-600' },
  delivered: { label: 'Delivered', badge: 'bg-emerald-100 text-emerald-700' },
  declined: { label: 'Declined', badge: 'bg-gray-100 text-gray-500' },
};
const PAYMENT = {
  paid: { label: 'Paid', badge: 'bg-emerald-100 text-emerald-700' },
  part: { label: 'Part paid', badge: 'bg-amber-100 text-amber-800' },
  unpaid: { label: 'Not paid', badge: 'bg-red-100 text-red-700' },
};
const shortDay = (value) => dayLabel(value.length === 10 ? fromDateInput(value) : new Date(value), { weekday: 'short', month: 'short', day: 'numeric' });
const dueText = (o) => (o.days_left == null ? 'No due date' : o.days_left < 0 ? `${-o.days_left} day${o.days_left === -1 ? '' : 's'} late`
  : o.days_left === 0 ? 'Due today' : `Due ${shortDay(o.due_date)} (${o.days_left} day${o.days_left === 1 ? '' : 's'})`);

/** Content → Customs: made-to-order content, from the request to the delivery. */
export default function Customs() {
  const [show, setShow] = useState('open');
  const [data, setData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [menu, setMenu] = useState([]);
  const [modal, setModal] = useState(null); // { order } | { pay } | { deliver } | { menu }
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const year = new Date().getFullYear();

  const load = useCallback(() => {
    axios.get('/api/customs', { params: { show } }).then(({ data: d }) => setData(d)).catch(() => setData({ orders: [], attention: {} }));
    axios.get('/api/customs/menu').then(({ data: d }) => setMenu(d)).catch(() => {});
    axios.get('/api/customs/summary', { params: { start: new Date(year, 0, 1).toISOString(), end: new Date(year + 1, 0, 1).toISOString() } })
      .then(({ data: d }) => setSummary(d)).catch(() => {});
  }, [show, year]);
  useEffect(() => { load(); }, [load]);
  const done = () => { setModal(null); load(); };
  const move = async (o, status) => {
    try {
      await axios.post(`/api/customs/${o.id}/status`, { status });
      setError('');
      load();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const copyMenu = async () => {
    const text = menu.map((m) => `${m.label}${m.price != null ? `: ${money(m.price)}` : ''}${m.notes ? ` (${m.notes})` : ''}`).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };
  const a = data?.attention || {};

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Show">
            {[['open', 'Open'], ['delivered', 'Delivered'], ['declined', 'Declined'], ['all', 'All']].map(([id, label]) => (
              <button key={id} onClick={() => setShow(id)} aria-pressed={show === id} className={`px-3 py-1.5 ${show === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{label}</button>
            ))}
          </div>
          <button onClick={() => setModal({ order: {} })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New custom</button>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Custom photos and videos people order from you. Taking a payment here adds it to your income as a sale, with the platform's fee taken off.
        </p>
        {(a.to_make > 0 || a.to_answer > 0) && (
          <p className="text-sm text-gray-700 mb-3">
            {a.to_make > 0 && <><b>{a.to_make}</b> to make{a.paid_waiting > 0 && ` (${money(a.paid_waiting)} already paid for)`}. </>}
            {a.late > 0 && <span className="text-red-600">{a.late} late. </span>}
            {a.not_paid > 0 && <span className="text-red-600">{a.not_paid} not fully paid: get paid before you film. </span>}
            {a.to_answer > 0 && <>{a.to_answer} to answer.</>}
          </p>
        )}
        {error && <p className="text-sm text-red-600 mb-2">{error}</p>}
        {!data ? null : data.orders.length === 0 ? (
          <p className="text-sm text-gray-400 py-8 text-center">{show === 'open' ? 'No open orders. Add one when someone asks for a custom.' : 'Nothing here yet.'}</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {data.orders.map((o) => (
              <li key={o.id} className="py-3 flex flex-wrap items-start gap-x-3 gap-y-1">
                <button onClick={() => setModal({ order: o })} className="flex-1 min-w-48 text-left">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-gray-800">{o.title}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${STATUS[o.status].badge}`}>{STATUS[o.status].label}</span>
                    {PAYMENT[o.payment] && o.status !== 'declined' && <span className={`text-[10px] px-2 py-0.5 rounded-full ${PAYMENT[o.payment].badge}`}>{PAYMENT[o.payment].label}</span>}
                    {o.can_resell && <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">Can resell</span>}
                  </span>
                  <span className="block text-xs text-gray-500">
                    {o.buyer}{o.source_name && ` · ${o.source_name}`}
                    {o.price != null && ` · ${money(o.price)}`}{o.owed > 0 && o.amount_paid > 0 && ` (${money(o.owed)} still owed)`}
                  </span>
                  {o.status === 'delivered'
                    ? <span className="block text-xs text-gray-500">Delivered {o.delivered_at && shortDay(o.delivered_at)}{o.delivery_note && ` · ${o.delivery_note}`}</span>
                    : o.status !== 'declined' && <span className={`block text-xs ${o.late ? 'text-red-600' : 'text-gray-500'}`}>{dueText(o)}</span>}
                  {o.details && <span className="block text-sm text-gray-600 line-clamp-2 whitespace-pre-wrap">{o.details}</span>}
                </button>
                <span className="flex flex-wrap gap-2 shrink-0">
                  {o.status === 'requested' && <button onClick={() => move(o, 'quoted')} className={quietButtonClass}>Quoted</button>}
                  {o.status !== 'declined' && o.payment !== 'paid' && <button onClick={() => setModal({ pay: o })} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">Got paid</button>}
                  {o.status === 'to_make' && <button onClick={() => setModal({ deliver: o })} className="text-xs px-2.5 py-1.5 rounded-lg bg-sworkr-500 text-white hover:bg-sworkr-600">Delivered</button>}
                  {(o.status === 'requested' || o.status === 'quoted') && <button onClick={() => move(o, 'declined')} className={quietButtonClass}>Decline</button>}
                  {o.status === 'declined' && <button onClick={() => move(o, 'requested')} className={quietButtonClass}>Reopen</button>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 items-start">
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
            <h2 className="font-semibold text-gray-800">Your menu</h2>
            <span className="flex gap-2">
              {menu.length > 0 && <button onClick={copyMenu} className={quietButtonClass}>{copied ? 'Copied ✓' : 'Copy menu'}</button>}
              <button onClick={() => setModal({ menu: {} })} className={buttonClass}>+ Add</button>
            </span>
          </div>
          <p className="text-xs text-gray-500 mb-2">Your usual prices and add-ons. Copy the whole menu to send it, or pick from it when you add an order.</p>
          {menu.length === 0 ? <p className="text-sm text-gray-400 py-3 text-center">Nothing on it yet.</p> : (
            <ul className="divide-y divide-gray-100">
              {menu.map((m) => (
                <li key={m.id}>
                  <button onClick={() => setModal({ menu: m })} className="w-full py-2 flex items-baseline justify-between gap-3 text-left">
                    <span className="text-sm text-gray-800">{m.label}{m.notes && <span className="text-xs text-gray-500"> · {m.notes}</span>}</span>
                    <span className="text-sm font-semibold text-gray-800">{m.price != null ? money(m.price) : ''}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {summary?.orders > 0 && (
          <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
            <h2 className="font-semibold text-gray-800 mb-2">Customs in {year}</h2>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              {[['Orders', summary.orders], ['Delivered', summary.delivered], ['Paid to you', money(summary.paid)],
                ['Still owed to you', money(summary.owed)], ['Usual price', summary.average_price == null ? '—' : money(summary.average_price)],
                ['Usual turnaround', summary.average_days == null ? '—' : `${summary.average_days} days`],
                ['Declined', summary.declined], ['You can resell', summary.can_resell]].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 border-b border-gray-50 py-1"><dt className="text-gray-500">{k}</dt><dd className="font-semibold text-gray-800">{v}</dd></div>
              ))}
            </dl>
            {summary.places.length > 1 && (
              <ul className="mt-3 text-sm divide-y divide-gray-50">
                {summary.places.map((p) => (
                  <li key={p.source_id || 0} className="py-1 flex justify-between gap-2">
                    <span className="text-gray-700">{p.label} <span className="text-xs text-gray-400">{p.orders} order{p.orders === 1 ? '' : 's'}</span></span>
                    <span className="text-gray-800">{money(p.paid)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {modal?.order && (
        <Modal title={modal.order.id ? 'Edit custom' : 'New custom'} onClose={() => setModal(null)} wide>
          <OrderForm order={modal.order} menu={menu} onDone={done} />
        </Modal>
      )}
      {modal?.pay && (
        <Modal title={`Got paid: ${modal.pay.title}`} onClose={() => setModal(null)}>
          <PayForm order={modal.pay} onDone={done} />
        </Modal>
      )}
      {modal?.deliver && (
        <Modal title={`Delivered: ${modal.deliver.title}`} onClose={() => setModal(null)}>
          <DeliverForm order={modal.deliver} onDone={done} />
        </Modal>
      )}
      {modal?.menu && (
        <Modal title={modal.menu.id ? 'Edit menu item' : 'Add to your menu'} onClose={() => setModal(null)}>
          <MenuForm item={modal.menu} onDone={done} />
        </Modal>
      )}
    </div>
  );
}

function PayForm({ order, onDone }) {
  const [form, setForm] = useState({ amount: order.owed || order.price || '', paid_on: toDateInput(new Date()), log_income: true, payment_method: '' });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`/api/customs/${order.id}/payment`, {
        amount: Number(form.amount), log_income: form.log_income, payment_method: form.payment_method.trim() || null,
        paid_on: form.paid_on === toDateInput(new Date()) ? null : fromDateInput(form.paid_on).toISOString(),
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the payment'));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm text-gray-600">
        {order.buyer}{order.price != null && ` · ${money(order.price)} in all`}{order.amount_paid > 0 && ` · ${money(order.amount_paid)} paid so far`}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount ($) *"><input required autoFocus type="number" min="0.01" step="0.01" inputMode="decimal" value={form.amount} onChange={set('amount')} className={inputClass} /></Field>
        <Field label="Paid on"><input type="date" value={form.paid_on} onChange={set('paid_on')} className={inputClass} /></Field>
      </div>
      <Field label="How it was paid">
        <input list="custom-paid-how" value={form.payment_method} onChange={set('payment_method')} placeholder="Platform, Cash App, cash…" className={inputClass} />
        <datalist id="custom-paid-how">{['Platform payout', 'Cash App', 'Venmo', 'PayPal', 'Bank transfer', 'Crypto', 'Gift card', 'Cash'].map((m) => <option key={m} value={m} />)}</datalist>
      </Field>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.log_income} onChange={set('log_income')} />
        Add it to my income{order.source_name ? ` (${order.source_name}, with its fee taken off)` : ''}
      </label>
      <p className="text-xs text-gray-400">Untick this if the platform's payout already includes it, so it isn't counted twice.</p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save payment</button></div>
    </form>
  );
}

function DeliverForm({ order, onDone }) {
  const [note, setNote] = useState(order.delivery_note || '');
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`/api/customs/${order.id}/delivered`, { delivery_note: note });
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      {order.owed > 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="alert">
          {money(order.owed)} of this hasn't been paid yet.
        </p>
      )}
      <Field label="How you sent it (optional)"><input autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. DM on OF, private link" className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Mark as delivered</button></div>
    </form>
  );
}

function MenuForm({ item, onDone }) {
  const [form, setForm] = useState({ label: item.label || '', price: item.price ?? '', notes: item.notes || '' });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...form, price: form.price === '' ? null : Number(form.price) };
    try {
      if (item.id) await axios.put(`/api/customs/menu/${item.id}`, body);
      else await axios.post('/api/customs/menu', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const remove = async () => {
    await axios.delete(`/api/customs/menu/${item.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <span className="col-span-2"><Field label="What *"><input required autoFocus value={form.label} onChange={set('label')} placeholder="e.g. 5 minute video" className={inputClass} /></Field></span>
        <Field label="Price ($)"><input type="number" min="0" step="0.01" inputMode="decimal" value={form.price} onChange={set('price')} className={inputClass} /></Field>
      </div>
      <Field label="Note"><input value={form.notes} onChange={set('notes')} placeholder="e.g. add-on, 3 day turnaround" className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {item.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

function OrderForm({ order, menu, onDone }) {
  const [form, setForm] = useState({
    buyer: order.buyer || '', title: order.title || '', details: order.details || '', price: order.price ?? '',
    status: order.status || 'requested', due_date: order.due_date || '', source_id: order.source_id ? String(order.source_id) : '',
    client_id: order.client_id ? String(order.client_id) : '', persona_id: order.persona_id ? String(order.persona_id) : '',
    delivery_note: order.delivery_note || '', set_path: order.set_path || '', can_resell: !!order.can_resell, notes: order.notes || '',
  });
  const [places, setPlaces] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get('/api/income-sources').then(({ data }) => setPlaces(data.filter((s) => !s.archived || s.id === order.source_id))).catch(() => {});
    fetchAll('/api/clients', { sort: 'name', role: 'client' }, 200).then(setContacts).catch(() => {});
  }, [order.source_id]);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const addFromMenu = (m) => setForm((f) => ({
    ...f, title: f.title.trim() ? `${f.title} + ${m.label}` : m.label,
    price: m.price != null ? String(Math.round(((Number(f.price) || 0) + m.price) * 100) / 100) : f.price,
  }));
  const pickContact = (e) => {
    const c = contacts.find((x) => String(x.id) === e.target.value);
    setForm({ ...form, client_id: e.target.value, buyer: form.buyer || c?.display_name || '' });
  };
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      ...form, price: form.price === '' ? null : Number(form.price), due_date: form.due_date || null,
      source_id: form.source_id ? Number(form.source_id) : null, client_id: form.client_id ? Number(form.client_id) : null,
      persona_id: form.persona_id ? Number(form.persona_id) : null, set_path: form.set_path.trim() || null,
      requested_at: order.requested_at || null,
    };
    try {
      if (order.id) await axios.put(`/api/customs/${order.id}`, body);
      else await axios.post('/api/customs', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the order'));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this order? Payments already in your income stay there.')) return;
    await axios.delete(`/api/customs/${order.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Who it's for *"><input required autoFocus value={form.buyer} onChange={set('buyer')} placeholder="A name or @handle" className={inputClass} /></Field>
        <Field label="One of your contacts (optional)">
          <select value={form.client_id} onChange={pickContact} className={inputClass}>
            <option value="">Not a contact</option>
            {contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
        </Field>
        <Field label="Paid through">
          <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
            <option value="">Not set</option>
            {places.map((s) => <option key={s.id} value={s.id}>{s.name}{s.fee_percent ? ` (${s.fee_percent}% fee)` : ''}</option>)}
          </select>
        </Field>
      </div>
      <Field label="What it is *">
        <input required value={form.title} onChange={set('title')} placeholder="e.g. 5 minute video, name use" className={inputClass} />
        {menu.length > 0 && (
          <span className="flex flex-wrap items-center gap-1 mt-1">
            <span className="text-xs text-gray-400">From your menu:</span>
            {menu.map((m) => (
              <button key={m.id} type="button" onClick={() => addFromMenu(m)} className="text-xs px-2 py-0.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">
                {m.label}{m.price != null && ` ${money(m.price)}`}
              </button>
            ))}
          </span>
        )}
      </Field>
      <Field label="The details"><textarea rows={3} value={form.details} onChange={set('details')} placeholder="What to say, wear and do. Anything you've agreed not to do." className={inputClass} /></Field>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Field label="Price ($)"><input type="number" min="0" step="0.01" inputMode="decimal" value={form.price} onChange={set('price')} className={inputClass} /></Field>
        <Field label="Due"><input type="date" value={form.due_date} onChange={set('due_date')} className={inputClass} /></Field>
        <Field label="Status">
          <select value={form.status} onChange={set('status')} className={inputClass}>
            {Object.entries(STATUS).map(([v, s]) => <option key={v} value={v}>{s.label}</option>)}
          </select>
        </Field>
        <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Persona" />
      </div>
      {order.id && order.amount_paid > 0 && <p className="text-xs text-gray-500">{money(order.amount_paid)} paid so far. Use "Got paid" on the list to add a payment.</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Folder in your library (optional)"><input value={form.set_path} onChange={set('set_path')} placeholder="Where the finished files are" className={inputClass} /></Field>
        <Field label="How you sent it"><input value={form.delivery_note} onChange={set('delivery_note')} className={inputClass} /></Field>
      </div>
      <label className="flex items-start gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.can_resell} onChange={set('can_resell')} className="mt-1" />
        <span>I can sell this again <span className="text-xs text-gray-500">(nothing personal in it, and they didn't pay for it to be theirs alone)</span></span>
      </label>
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {order.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete order</button> : <span />}
        <button type="submit" className={buttonClass}>{order.id ? 'Save changes' : 'Save order'}</button>
      </div>
    </form>
  );
}

/** On the dashboard: customs to make, the late ones first. */
export function CustomsDue() {
  const [orders, setOrders] = useState([]);
  useEffect(() => {
    axios.get('/api/customs').then(({ data }) => setOrders(data.orders.filter((o) => o.status === 'to_make'))).catch(() => {});
  }, []);
  if (orders.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Customs to make</h2>
        <Link to="/content/customs" className="text-sm text-sworkr-600 hover:text-sworkr-800">Customs →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {orders.slice(0, 5).map((o) => (
          <li key={o.id} className="py-2">
            <Link to="/content/customs" className="flex flex-wrap items-center justify-between gap-2">
              <span><span className="font-medium text-gray-800">{o.title}</span><span className="text-xs text-gray-500"> · {o.buyer}</span></span>
              <span className={`text-xs ${o.late ? 'text-red-600' : 'text-gray-500'}`}>{dueText(o)}{o.payment !== 'paid' && o.payment !== 'none' ? ' · not fully paid' : ''}</span>
            </Link>
          </li>
        ))}
      </ul>
      {orders.length > 5 && <p className="text-xs text-gray-400 mt-1">and {orders.length - 5} more</p>}
    </div>
  );
}
