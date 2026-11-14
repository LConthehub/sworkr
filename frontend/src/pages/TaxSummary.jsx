import { useEffect, useState } from 'react';
import axios from 'axios';
import { errorMessage, quietButtonClass } from '../components/Modal';
import { money } from '../colors';
import QuarterlyTaxes from '../components/QuarterlyTaxes';

const PERCENT_KEY = 'sworkr:set-aside-percent';
const readPercent = () => { try { return localStorage.getItem(PERCENT_KEY) ?? ''; } catch { return ''; } };

/**
 * The year added up for a tax return or an accountant. Your part after partners' shares. It adds up; it
 * doesn't advise: the set-aside percentage is one you choose.
 */
export default function TaxSummary({ year, setYear }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [percent, setPercent] = useState(readPercent);
  const [open, setOpen] = useState({});
  const thisYear = new Date().getFullYear();

  useEffect(() => {
    setData(null);
    const p = Number(percent);
    axios.get('/api/tax-summary', {
      params: { year, tz_offset: new Date().getTimezoneOffset(), ...(percent !== '' && p >= 0 && p <= 100 ? { set_aside_percent: p } : {}) },
    }).then(({ data: d }) => { setData(d); setError(''); }).catch((err) => setError(errorMessage(err, "Couldn't add up the year")));
  }, [year, percent]);

  const changePercent = (e) => {
    setPercent(e.target.value);
    try { localStorage.setItem(PERCENT_KEY, e.target.value); } catch { /* not remembered */ }
  };

  const row = (label, value, opts = {}) => (
    <div className={`flex justify-between gap-4 py-1.5 ${opts.strong ? 'font-semibold text-gray-900 border-t border-gray-200 mt-1 pt-2' : 'text-gray-700'} ${opts.indent ? 'pl-5 text-sm text-gray-500' : ''}`}>
      <dt>{label}</dt>
      <dd className="tabular-nums whitespace-nowrap">{value}</dd>
    </div>
  );

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-5 print:shadow-none">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button onClick={() => setYear(year - 1)} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600 print:hidden" aria-label="Previous year">←</button>
          <h2 className="text-lg font-bold text-gray-800">{year} for taxes</h2>
          <button onClick={() => setYear(year + 1)} disabled={year >= thisYear} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600 disabled:opacity-30 print:hidden" aria-label="Next year">→</button>
        </div>
        <button onClick={() => window.print()} className={`${quietButtonClass} print:hidden`}>Print or save as PDF</button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {!data && !error && <p className="text-sm text-gray-400">Adding up…</p>}
      {data && (
        <>
          <section>
            <h3 className="font-semibold text-gray-800 mb-1">Income</h3>
            <dl className="max-w-xl">
              {data.income.length === 0 && row('Nothing received this year', money(0))}
              {data.income.map((i) => row(`${i.label} (${i.entries})`, money(i.gross)))}
              {row('Total income', money(data.gross_income), { strong: true })}
            </dl>
            {data.pending > 0 && <p className="text-xs text-gray-500 mt-1">Not counted: {money(data.pending)} earned but not paid out yet.</p>}
          </section>

          <section>
            <h3 className="font-semibold text-gray-800 mb-1">Taken by places</h3>
            <dl className="max-w-xl">
              {data.income.filter((i) => i.fees > 0).map((i) => row(i.key === 'gift' ? "Houses' share of gifts" : `Fees and house shares: ${i.label.toLowerCase()}`, money(i.fees)))}
              {row('Total taken by places', money(data.fees), { strong: true })}
            </dl>
          </section>

          <section>
            <h3 className="font-semibold text-gray-800 mb-1">Expenses</h3>
            <dl className="max-w-xl">
              {data.expenses.length === 0 && row('No expenses this year', money(0))}
              {data.expenses.map((g) => (
                <div key={g.key}>
                  <button type="button" onClick={() => setOpen({ ...open, [g.key]: !open[g.key] })} className="w-full text-left print:pointer-events-none">
                    {row(`${g.label}${g.lines.length > 1 ? (open[g.key] ? ' ▾' : ' ▸') : ''}`, money(g.total))}
                  </button>
                  {(open[g.key] || g.lines.length > 1) && (
                    <div className={open[g.key] ? '' : 'hidden print:block'}>
                      {g.lines.map((l) => <div key={l.key}>{row(l.label, money(l.total), { indent: true })}</div>)}
                    </div>
                  )}
                </div>
              ))}
              {row('Total expenses', money(data.total_expenses), { strong: true })}
            </dl>
          </section>

          <section className="rounded-xl bg-gray-50 p-4 max-w-xl">
            <dl>
              {row('Profit (income − taken by places − expenses)', money(data.profit), { strong: true })}
            </dl>
            <label className="flex flex-wrap items-center gap-2 text-sm text-gray-700 mt-3 print:hidden">
              Set aside
              <input type="number" min="0" max="100" step="1" value={percent} onChange={changePercent} placeholder="%" className="w-16 border border-gray-200 rounded-lg px-2 py-1" />
              % of profit
              {data.set_aside && <span className="font-semibold">= {money(data.set_aside.amount)}</span>}
            </label>
            {data.set_aside && <p className="hidden print:block text-sm">Set aside ({data.set_aside.percent}% of profit): {money(data.set_aside.amount)}</p>}
            {data.estimated_payments?.length > 0 && (
              <dl className="mt-3">
                {data.estimated_payments.map((p) => row(`Estimated tax paid (${p.authority}, ${p.payments} payment${p.payments === 1 ? '' : 's'})`, money(p.total)))}
              </dl>
            )}
          </section>

          <QuarterlyTaxes year={year} percent={percent} />

          <p className="text-xs text-gray-500 max-w-xl">
            Your part only: shares you pay partners are left out. Gifts count at what they're worth, with a house's share of
            them under "Taken by places". This adds up what you've logged; it isn't tax advice, and the rules where you live
            decide what's taxable and deductible. For every payment and expense line by line, use “Export for taxes (CSV)” on
            Income & expenses.
          </p>
        </>
      )}
    </div>
  );
}
