import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { errorMessage, inputClass, buttonClass } from './Modal';
import { money, toDateInput } from '../colors';

const PERIOD_NAMES = ['Jan – Mar', 'Apr – May', 'Jun – Aug', 'Sep – Dec'];
const dueText = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

/**
 * US estimated tax, paid in four periods (IRS dates; most states use the same). For each: your profit, what
 * your set-aside percentage of it comes to, and what you've paid. It shows your own numbers; how much you
 * actually owe is for you, the IRS worksheet or your accountant.
 */
export default function QuarterlyTaxes({ year, percent }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [logging, setLogging] = useState(null);   // quarter number
  const [form, setForm] = useState({ amount: '', authority: 'federal', paid_on: toDateInput(new Date()), note: '' });
  const [reminders, setReminders] = useState(null);

  const load = useCallback(() => {
    const p = Number(percent);
    axios.get('/api/tax-summary/quarters', {
      params: { year, tz_offset: new Date().getTimezoneOffset(), ...(percent !== '' && p >= 0 && p <= 100 ? { set_aside_percent: p } : {}) },
    }).then(({ data: d }) => { setData(d); setError(''); }).catch((err) => setError(errorMessage(err, "Couldn't load the quarters")));
  }, [year, percent]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { axios.get('/api/tax-summary/reminders').then(({ data: d }) => setReminders(d.enabled)).catch(() => {}); }, []);

  const save = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await axios.post('/api/tax-summary/payments', { year, quarter: logging, authority: form.authority, amount: Number(form.amount), paid_on: form.paid_on, note: form.note || null });
      setLogging(null);
      setForm({ ...form, amount: '', note: '' });
      load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the payment"));
    }
  };
  const remove = async (p) => {
    if (!window.confirm(`Delete the ${p.authority} payment of ${money(p.amount)}?`)) return;
    await axios.delete(`/api/tax-summary/payments/${p.id}`).catch(() => {});
    load();
  };
  const toggleReminders = async (e) => {
    const { data: d } = await axios.put('/api/tax-summary/reminders', { enabled: e.target.checked });
    setReminders(d.enabled);
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold text-gray-800">Quarterly estimated tax (US)</h3>
        {reminders !== null && (
          <label className="flex items-center gap-2 text-sm text-gray-700 print:hidden">
            <input type="checkbox" checked={reminders} onChange={toggleReminders} />
            Remind me a week before each due date
          </label>
        )}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!data ? <p className="text-sm text-gray-400">Loading…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[36rem]">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b">
                <th className="py-2 pr-2 font-medium">Period</th>
                <th className="py-2 pr-2 font-medium">Due</th>
                <th className="py-2 pr-2 font-medium text-right">Profit</th>
                {percent !== '' && <th className="py-2 pr-2 font-medium text-right">Set aside ({percent}%)</th>}
                <th className="py-2 pr-2 font-medium text-right">Paid (federal / state)</th>
                <th className="py-2 print:hidden" />
              </tr>
            </thead>
            <tbody>
              {data.quarters.map((q) => {
                const soon = q.days_until_due >= 0 && q.days_until_due <= 21;
                return [
                  <tr key={q.quarter} className="border-b border-gray-50 align-top">
                    <td className="py-2 pr-2 text-gray-800">Q{q.quarter} <span className="text-gray-500">{PERIOD_NAMES[q.quarter - 1]}</span></td>
                    <td className={`py-2 pr-2 ${soon ? 'text-amber-700 font-semibold' : 'text-gray-600'}`}>
                      {dueText(q.due)}
                      {soon && <span className="block text-xs">in {q.days_until_due} day{q.days_until_due === 1 ? '' : 's'}</span>}
                    </td>
                    <td className="py-2 pr-2 text-right tabular-nums">{money(q.profit)}</td>
                    {percent !== '' && <td className="py-2 pr-2 text-right tabular-nums">{money(q.set_aside || 0)}</td>}
                    <td className="py-2 pr-2 text-right tabular-nums">
                      {money(q.paid_federal)} / {money(q.paid_state)}
                      {q.payments.map((p) => (
                        <span key={p.id} className="block text-xs text-gray-500">
                          {p.authority} {money(p.amount)} on {p.paid_on}{p.note ? ` · ${p.note}` : ''}
                          <button type="button" onClick={() => remove(p)} className="ml-1 text-red-500 hover:text-red-700 print:hidden" aria-label="Delete this payment">✕</button>
                        </span>
                      ))}
                    </td>
                    <td className="py-2 text-right print:hidden">
                      <button type="button" onClick={() => setLogging(logging === q.quarter ? null : q.quarter)} className="text-xs text-sworkr-600 hover:text-sworkr-800">
                        Log payment
                      </button>
                    </td>
                  </tr>,
                  logging === q.quarter && (
                    <tr key={`f${q.quarter}`}>
                      <td colSpan={6} className="py-2">
                        <form onSubmit={save} className="flex flex-wrap items-end gap-2 rounded-xl bg-gray-50 p-2">
                          <select value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })} className={`${inputClass} w-28`} aria-label="Paid to">
                            <option value="federal">Federal</option>
                            <option value="state">State</option>
                          </select>
                          <input required type="number" min="0.01" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="$" aria-label="Amount" className={`${inputClass} w-28`} />
                          <input required type="date" value={form.paid_on} onChange={(e) => setForm({ ...form, paid_on: e.target.value })} aria-label="Paid on" className={`${inputClass} w-40`} />
                          <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Confirmation number (optional)" aria-label="Note" className={`${inputClass} flex-1 min-w-40`} />
                          <button type="submit" className={buttonClass}>Save</button>
                        </form>
                      </td>
                    </tr>
                  ),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-gray-500">
        Periods and due dates are the IRS's (a weekend moves the date to Monday; check irs.gov for holidays). Payments
        you log here aren't expenses: they count against the tax you owe, not your profit. Pay at irs.gov/payments or
        your state's tax site.
      </p>
    </section>
  );
}
