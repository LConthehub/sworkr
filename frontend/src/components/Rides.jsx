import { useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass } from './Modal';
import { money } from '../colors';

const UNITS = { trip: 'a trip', hour: 'an hour', mile: 'a mile', km: 'a km', day: 'a day' };
const PLURAL = { trip: 'trips', hour: 'hours', mile: 'miles', km: 'km', day: 'days' };

// One fetch shared by every booking on the page.
let pending = null;
export const fetchDrivers = (fresh = false) => {
  if (fresh || !pending) pending = axios.get('/api/drivers').then(({ data }) => data).catch(() => []);
  return pending;
};

/** On a contact you work with: their own rates. */
export function DriverRates({ contactId }) {
  const [rates, setRates] = useState(null);
  const [form, setForm] = useState({ label: '', amount: '', unit: 'trip' });
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get(`/api/clients/${contactId}/rates`).then(({ data }) => setRates(data)).catch(() => setRates([]));
  }, [contactId]);
  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const { data } = await axios.post(`/api/clients/${contactId}/rates`, { ...form, amount: Number(form.amount) });
      setRates(data);
      setForm({ label: '', amount: '', unit: form.unit });
      fetchDrivers(true);
    } catch (err) {
      setError(errorMessage(err, "Couldn't add it"));
    }
  };
  const remove = async (r) => {
    await axios.delete(`/api/clients/${contactId}/rates/${r.id}`).catch(() => {});
    setRates(rates.filter((x) => x.id !== r.id));
    fetchDrivers(true);
  };
  if (rates === null) return null;
  return (
    <div className="mt-4 rounded-xl border border-gray-100 p-3">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Their rates</p>
      {rates.length > 0 && (
        <ul className="mt-1 text-sm divide-y divide-gray-100">
          {rates.map((r) => (
            <li key={r.id} className="py-1.5 flex items-center gap-2">
              <span className="flex-1 text-gray-800">{r.label}</span>
              <span className="tabular-nums text-gray-600">{money(r.amount)} {UNITS[r.unit]}</span>
              <button type="button" onClick={() => remove(r)} className="text-xs text-gray-400 hover:text-red-600" aria-label={`Remove ${r.label}`}>✕</button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="mt-2 grid grid-cols-[1fr_6rem_auto_auto] gap-2">
        <input required value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="e.g. Airport run, Waiting" aria-label="What for" className={inputClass} />
        <input required type="number" min="0" step="0.5" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="$" aria-label="Amount" className={inputClass} />
        <select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} aria-label="Per" className={inputClass}>
          {Object.entries(UNITS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button type="submit" className="text-sm px-3 rounded-lg bg-sworkr-500 text-white">Add</button>
      </form>
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </div>
  );
}

/** "Ride" on a booking: pick a driver and one of their rates; it's logged as a travel expense. */
export function RideLogger({ appointment, drivers, onClose }) {
  const [driverId, setDriverId] = useState(drivers[0]?.id || '');
  const driver = drivers.find((d) => d.id === Number(driverId));
  const [rateId, setRateId] = useState(drivers[0]?.rates[0]?.id || '');
  const rate = driver?.rates.find((r) => r.id === Number(rateId));
  const [quantity, setQuantity] = useState('1');
  const [done, setDone] = useState(null);
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try {
      const { data } = await axios.post(`/api/appointments/${appointment.id}/ride`, { rate_id: Number(rateId), quantity: Number(quantity) });
      setDone(data);
    } catch (err) {
      setError(errorMessage(err, "Couldn't log the ride"));
    }
  };
  return (
    <Modal title="Ride" onClose={onClose}>
      {done ? (
        <div className="space-y-3">
          <p className="text-sm text-gray-700">Logged {money(done.amount)} as a travel expense on the booking's day.</p>
          <div className="flex justify-end"><button onClick={onClose} className={buttonClass}>Done</button></div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Driver">
              <select value={driverId} onChange={(e) => { setDriverId(e.target.value); const d = drivers.find((x) => x.id === Number(e.target.value)); setRateId(d?.rates[0]?.id || ''); }} className={inputClass}>
                {drivers.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            <Field label="Rate">
              <select value={rateId} onChange={(e) => setRateId(e.target.value)} className={inputClass}>
                {driver?.rates.map((r) => <option key={r.id} value={r.id}>{r.label}: {money(r.amount)} {UNITS[r.unit]}</option>)}
              </select>
            </Field>
          </div>
          {rate && (
            <Field label={`How many ${PLURAL[rate.unit]}`}>
              <input type="number" min="0.25" step="0.25" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={inputClass} />
            </Field>
          )}
          {rate && <p className="text-sm text-gray-600">Comes to {money(rate.amount * (Number(quantity) || 0))}.</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end"><button type="submit" disabled={!rate} className={buttonClass}>Log the ride</button></div>
        </form>
      )}
    </Modal>
  );
}
