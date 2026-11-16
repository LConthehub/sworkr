import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';
import { CHART, money } from '../colors';

/** Suggestions only: anything can be typed in. */
const COMMON = ['Tryst', 'Eros', 'Slixa', 'Private Delights', 'AdultWork', 'Scarlet Blue', 'Leolist', 'My website',
  'X', 'Instagram', 'Reddit', 'Telegram', 'Bluesky', 'OnlyFans', 'Fansly', 'Referral', 'Agency', 'Met in person'];

/** "How they found you" on a contact: what you've typed before comes first, then common places. */
export function FoundViaField({ value, onChange }) {
  const [used, setUsed] = useState([]);
  useEffect(() => {
    axios.get('/api/marketing/found-via/options').then(({ data }) => setUsed(data)).catch(() => {});
  }, []);
  const have = new Set(used.map((u) => u.toLowerCase()));
  return (
    <Field label="How they found you">
      <input list="found-via" value={value} onChange={onChange} maxLength={80} placeholder="e.g. Tryst, X, a referral" className={inputClass} />
      <datalist id="found-via">{[...used, ...COMMON.filter((c) => !have.has(c.toLowerCase()))].map((x) => <option key={x} value={x} />)}</datalist>
      <span className="block text-xs text-gray-400 mt-1">Money → Compare then shows what each ad site or account brings in.</span>
    </Field>
  );
}

/** Money → Compare → "By how they found you": clients, income, spend and what's left for each. */
export default function FoundViaCompare({ year }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    setData(null);
    axios.get('/api/marketing/found-via', { params: { start: new Date(year, 0, 1).toISOString(), end: new Date(year + 1, 0, 1).toISOString() } })
      .then(({ data: d }) => { setData(d); setError(''); })
      .catch((err) => setError(errorMessage(err, "Couldn't load this comparison.")));
  }, [year]);

  if (error) return <p className="text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">{error}</p>;
  if (!data) return null;
  const known = data.rows.filter((r) => r.key !== 'none');
  const unknown = data.rows.find((r) => r.key === 'none');
  if (known.length === 0) {
    return (
      <p className="text-sm text-gray-500 text-center py-10 max-w-md mx-auto">
        Nothing to compare yet. Open a contact, choose Edit and fill in <b>How they found you</b>. Once a few clients have it,
        this shows which ad sites and accounts bring in the most.
      </p>
    );
  }
  const top = Math.max(...data.rows.map((r) => r.income), 0) || 1;
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        What clients paid you in {year}, by how they found you (your share, after collaborators' splits), next to what you spent on each.
      </p>
      <ul className="space-y-2">
        {data.rows.map((r) => (
          <li key={r.key} className="flex items-center gap-3">
            <span className={`w-32 sm:w-48 shrink-0 text-sm font-medium truncate ${r.key === 'none' ? 'text-gray-400' : 'text-gray-800'}`} title={r.label}>{r.label}</span>
            <span className="relative flex-1 h-6 bg-gray-50 rounded">
              <span className="absolute inset-y-0 left-0 rounded" style={{ width: `${(r.income / top) * 100}%`, background: r.key === 'none' ? '#d1d5db' : CHART.income }} />
            </span>
            <span className="w-24 text-right text-sm font-semibold text-gray-800">
              {money(r.income)}
              {r.share != null && <span className="block text-[11px] font-normal text-gray-400">{Math.round(r.share * 100)}%</span>}
            </span>
          </li>
        ))}
      </ul>
      <div className="overflow-x-auto -mx-4 sm:mx-0 px-4 sm:px-0">
        <table className="w-full text-sm min-w-[600px]">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
              <th className="py-1.5 pr-2 font-medium">Found you via</th>
              <th className="py-1.5 px-1 font-medium text-right">Clients</th>
              <th className="py-1.5 px-1 font-medium text-right">New in {year}</th>
              <th className="py-1.5 px-1 font-medium text-right">Paid bookings</th>
              <th className="py-1.5 px-1 font-medium text-right">Income</th>
              <th className="py-1.5 px-1 font-medium text-right">Per client</th>
              <th className="py-1.5 px-1 font-medium text-right">Spent on it</th>
              <th className="py-1.5 px-1 font-medium text-right">Left</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.key} className="border-b border-gray-50">
                <td className={`py-1.5 pr-2 ${r.key === 'none' ? 'text-gray-400' : 'text-gray-800'}`}>{r.label}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.clients}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.new_clients || '—'}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.bookings}</td>
                <td className="py-1.5 px-1 text-right text-gray-800">{money(r.income)}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.per_client == null ? '—' : money(r.per_client)}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.spend ? money(r.spend) : '—'}</td>
                <td className={`py-1.5 px-1 text-right font-semibold ${r.profit < 0 ? 'text-red-600' : 'text-gray-800'}`}>{money(r.profit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-gray-500 space-y-1">
        {unknown?.clients > 0 && (
          <p>{unknown.clients} client{unknown.clients === 1 ? " doesn't" : "s don't"} say how they found you yet. Filling that in makes this more accurate.</p>
        )}
        {data.spent > 0 && (
          <p>
            You spent {money(data.spent)} on marketing in {year}.
            {data.unmatched_spend > 0 && ` ${money(data.unmatched_spend)} of it isn't matched to a row above.`}
          </p>
        )}
      </div>
    </div>
  );
}
