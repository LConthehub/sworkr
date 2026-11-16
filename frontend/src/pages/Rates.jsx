import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from '../components/Modal';
import { PersonaSelect } from '../components/Personas';
import { dayLabel, formatDuration, formatTime, money } from '../colors';

const shortDay = (iso) => dayLabel(new Date(iso), { weekday: 'short', month: 'short', day: 'numeric' });

/** Money → Rates: the rate card, deposits still to come in, and clients on an old rate. */
export default function Rates() {
  const [rates, setRates] = useState(null);
  const [deposits, setDeposits] = useState(null);
  const [behind, setBehind] = useState([]);
  const [editing, setEditing] = useState(null);
  const [showOld, setShowOld] = useState(false);
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => {
    axios.get('/api/rates').then(({ data }) => setRates(data)).catch(() => setRates([]));
    axios.get('/api/rates/deposits').then(({ data }) => setDeposits(data)).catch(() => {});
    axios.get('/api/rates/behind').then(({ data }) => setBehind(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!rates) return null;

  const shown = rates.filter((r) => showOld || !r.archived);
  const groups = [];
  for (const r of shown) {
    const name = r.persona_name || '';
    const group = groups.find((g) => g.name === name) || groups[groups.push({ name, rates: [] }) - 1];
    group.rates.push(r);
  }
  const line = (r) => `${r.label}${r.minutes ? ` (${formatDuration(r.minutes)})` : ''}: ${money(r.price)}${r.notes ? `, ${r.notes}` : ''}`;
  const copyCard = async (group) => {
    try {
      await navigator.clipboard.writeText(group.rates.filter((r) => !r.archived).map(line).join('\n'));
      setCopied(group.name || 'all');
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="text-xl font-bold text-gray-800">Your rates</h2>
          <button onClick={() => setEditing({})} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ Add a rate</button>
        </div>
        <p className="text-sm text-gray-500 mb-3">
          What you charge. Pick one of these as the service when you add a booking and its length and price fill themselves in.
          Copy the card to send it to someone who asks.
        </p>
        {shown.length === 0 ? (
          <p className="text-sm text-gray-400 py-6 text-center">No rates yet. Add what you charge for an hour, a dinner date, an overnight.</p>
        ) : groups.map((g) => (
          <section key={g.name} className="mb-4">
            <div className="flex items-center justify-between gap-2 mb-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{g.name || (groups.length > 1 ? 'Any persona' : 'Rate card')}</h3>
              <button onClick={() => copyCard(g)} className={quietButtonClass}>{copied === (g.name || 'all') ? 'Copied ✓' : 'Copy as text'}</button>
            </div>
            <ul className="divide-y divide-gray-100">
              {g.rates.map((r) => (
                <li key={r.id}>
                  <button onClick={() => setEditing(r)} className={`w-full py-2 flex items-baseline justify-between gap-3 text-left ${r.archived ? 'opacity-50' : ''}`}>
                    <span className="text-sm text-gray-800">
                      {r.label}{r.minutes && <span className="text-xs text-gray-500"> · {formatDuration(r.minutes)}</span>}
                      {r.notes && <span className="text-xs text-gray-500"> · {r.notes}</span>}
                    </span>
                    <span className="text-sm font-semibold text-gray-800">{money(r.price)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {rates.some((r) => r.archived) && (
          <button onClick={() => setShowOld(!showOld)} className="text-xs text-gray-500 hover:text-gray-700">{showOld ? 'Hide rates you no longer offer' : 'Show rates you no longer offer'}</button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2 items-start">
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <h3 className="font-semibold text-gray-800">Deposits to collect</h3>
          {!deposits ? null : deposits.deposit_percent === 0 ? (
            <p className="text-sm text-gray-500 mt-1">
              You don't ask for a deposit yet. Set a percentage under <Link to="/account/work#policy" className="underline text-sworkr-600">Account → Deposits & cancellations</Link> and
              bookings without one show up here.
            </p>
          ) : (
            <>
              <p className="text-xs text-gray-500 mb-2">
                Your deposit is {deposits.deposit_percent}% of the rate. {deposits.to_collect.length === 0
                  ? 'Every booking ahead has its deposit.' : <><b className="text-red-600">{money(deposits.missing)}</b> still to come in.</>}
                {deposits.held > 0 && ` You're holding ${money(deposits.held)} for bookings ahead.`}
              </p>
              <ul className="divide-y divide-gray-100">
                {deposits.to_collect.map((d) => (
                  <li key={d.id} className="py-2 flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <Link to={d.client_id ? `/contacts/${d.client_id}` : '/calendar'} className="font-medium text-gray-800 hover:text-sworkr-700">{d.client_name || 'Booking'}</Link>
                      <span className="block text-xs text-gray-500">{shortDay(d.scheduled_date)}, {formatTime(new Date(d.scheduled_date))} · {d.service_type} · {money(d.rate)}</span>
                    </span>
                    <span className="text-sm text-red-600 font-semibold">{money(d.missing)}{d.amount_paid > 0 && <span className="block text-[11px] font-normal text-gray-500">of {money(d.deposit)}</span>}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
          <h3 className="font-semibold text-gray-800">On an old rate</h3>
          <p className="text-xs text-gray-500 mb-2">Clients whose last booking cost less than your card says now. Worth knowing before you tell regulars about a new price.</p>
          {behind.length === 0 ? <p className="text-sm text-gray-400 py-2">Nobody: everyone's last booking was at your current rate, or isn't on the card.</p> : (
            <ul className="divide-y divide-gray-100">
              {behind.map((b) => (
                <li key={`${b.client_id}-${b.service}-${b.minutes}`} className="py-2 flex flex-wrap items-center justify-between gap-2">
                  <span>
                    <Link to={`/contacts/${b.client_id}`} className="font-medium text-gray-800 hover:text-sworkr-700">{b.client_name}</Link>
                    <span className="block text-xs text-gray-500">{b.service} · {formatDuration(b.minutes)} · last on {shortDay(b.last_booked)} · {b.bookings} booking{b.bookings === 1 ? '' : 's'}</span>
                  </span>
                  <span className="text-sm text-gray-800 text-right">{money(b.their_rate)} → {money(b.card_rate)}<span className="block text-[11px] text-amber-700">{money(b.gap)} under</span></span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {editing && (
        <Modal title={editing.id ? 'Edit rate' : 'Add a rate'} onClose={() => setEditing(null)}>
          <RateForm rate={editing} onDone={() => { setEditing(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}

function RateForm({ rate, onDone }) {
  const [form, setForm] = useState({
    label: rate.label || '', hours: rate.minutes ? String(rate.minutes / 60) : '', price: rate.price ?? '', notes: rate.notes || '',
    persona_id: rate.persona_id ? String(rate.persona_id) : '', archived: !!rate.archived,
  });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      label: form.label, minutes: form.hours === '' ? null : Math.round(Number(form.hours) * 60), price: Number(form.price), notes: form.notes,
      persona_id: form.persona_id ? Number(form.persona_id) : null, archived: form.archived,
    };
    try {
      if (rate.id) await axios.put(`/api/rates/${rate.id}`, body);
      else await axios.post('/api/rates', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the rate'));
    }
  };
  const remove = async () => {
    await axios.delete(`/api/rates/${rate.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="What it's for *"><input required autoFocus value={form.label} onChange={set('label')} placeholder="e.g. One hour, Dinner date, Overnight" className={inputClass} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Length (hours)"><input type="number" min="0.25" step="0.25" value={form.hours} onChange={set('hours')} placeholder="e.g. 2" className={inputClass} /></Field>
        <Field label="Price ($) *"><input required type="number" min="0" step="0.01" inputMode="decimal" value={form.price} onChange={set('price')} className={inputClass} /></Field>
      </div>
      <Field label="Note"><input value={form.notes} onChange={set('notes')} placeholder="e.g. incall, outcall +$100, 2 hour minimum" className={inputClass} /></Field>
      <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Persona" />
      {rate.id && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.archived} onChange={set('archived')} /> I don't offer this any more
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {rate.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

/** On the dashboard: bookings ahead whose deposit hasn't come in. */
export function DepositsDue() {
  const [data, setData] = useState(null);
  useEffect(() => { axios.get('/api/rates/deposits').then(({ data: d }) => setData(d)).catch(() => {}); }, []);
  if (!data || data.to_collect.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Deposits to collect</h2>
        <Link to="/money/rates" className="text-sm text-sworkr-600 hover:text-sworkr-800">Rates →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {data.to_collect.slice(0, 5).map((d) => (
          <li key={d.id} className="py-2 flex flex-wrap items-center justify-between gap-2">
            <span><span className="font-medium text-gray-800">{d.client_name || 'Booking'}</span><span className="text-xs text-gray-500"> · {shortDay(d.scheduled_date)}</span></span>
            <span className="text-sm text-red-600">{money(d.missing)}</span>
          </li>
        ))}
      </ul>
      {data.to_collect.length > 5 && <p className="text-xs text-gray-400 mt-1">and {data.to_collect.length - 5} more</p>}
    </div>
  );
}
