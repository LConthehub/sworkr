import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, buttonClass, errorMessage } from './Modal';
import { money, toDateInput } from '../colors';

/**
 * Miles driven for work (outcalls, tours, shoots), for the standard mileage deduction. The IRS sets the rate
 * each year; you enter it (sworkr doesn't guess), and it's multiplied out here and in the year's summary.
 */
export default function Mileage({ year, onChanged }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ date: toDateInput(new Date()), miles: '', purpose: '' });
  const [rate, setRate] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get('/api/tax-summary/mileage', { params: { year } })
      .then(({ data: d }) => { setData(d); setRate(d.rate ?? ''); })
      .catch((err) => setError(errorMessage(err, "Couldn't load mileage")));
  }, [year]);
  useEffect(() => { load(); }, [load]);

  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await axios.post('/api/tax-summary/mileage', { date: form.date, miles: Number(form.miles), purpose: form.purpose || null });
      setForm({ ...form, miles: '', purpose: '' });
      load();
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the trip"));
    }
  };
  const saveRate = async () => {
    try {
      await axios.put(`/api/tax-summary/mileage/rate/${year}`, { rate: rate === '' ? null : Number(rate) });
      load();
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the rate"));
    }
  };
  const remove = async (t) => {
    await axios.delete(`/api/tax-summary/mileage/${t.id}`).catch(() => {});
    load();
    onChanged?.();
  };

  return (
    <section className="space-y-3">
      <h3 className="font-semibold text-gray-800">Mileage</h3>
      <form onSubmit={add} className="flex flex-wrap items-end gap-2 print:hidden">
        <input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} aria-label="Date" className={`${inputClass} w-40`} />
        <input type="number" required min="0.1" step="0.1" value={form.miles} onChange={(e) => setForm({ ...form, miles: e.target.value })} placeholder="Miles" aria-label="Miles" className={`${inputClass} w-24`} />
        <input value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} placeholder="What for, e.g. outcall, photo shoot" aria-label="What for" className={`${inputClass} flex-1 min-w-40`} />
        <button type="submit" className={buttonClass}>Add trip</button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {data && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm text-gray-700">
            <span><strong>{data.miles}</strong> miles in {data.trip_count} trip{data.trip_count === 1 ? '' : 's'} ×</span>
            <span className="print:hidden">$</span>
            <input type="number" min="0" step="0.005" value={rate} onChange={(e) => setRate(e.target.value)} onBlur={saveRate}
              placeholder="rate" aria-label={`Rate per mile for ${year}`} className="w-20 border border-gray-200 rounded-lg px-2 py-1 print:hidden" />
            <span className="hidden print:inline">{data.rate != null ? `$${data.rate}` : '(no rate)'}</span>
            <span>per mile {data.deduction != null && <>= <strong>{money(data.deduction)}</strong></>}</span>
          </div>
          <p className="text-xs text-gray-500">
            Enter {year}'s IRS standard mileage rate (it was 70¢ a mile for 2025; irs.gov has each year's). The standard rate
            is instead of car costs like gas and repairs, so don't count those as expenses as well.
          </p>
          {data.trips.length > 0 && (
            <ul className="divide-y divide-gray-100 text-sm max-h-64 overflow-y-auto">
              {data.trips.map((t) => (
                <li key={t.id} className="flex items-center gap-3 py-1.5">
                  <span className="w-24 text-gray-500">{t.date}</span>
                  <span className="w-16 tabular-nums">{t.miles} mi</span>
                  <span className="flex-1 text-gray-700">{[t.purpose, t.tour_name].filter(Boolean).join(' · ')}</span>
                  <button type="button" onClick={() => remove(t)} className="text-xs text-red-500 hover:text-red-700 print:hidden" aria-label="Delete this trip">✕</button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
