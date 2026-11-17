import { useEffect, useState } from 'react';
import axios from 'axios';
import { errorMessage } from './Modal';
import { money } from '../colors';

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const hourLabel = (h) => `${h % 12 || 12}${h < 12 ? 'a' : 'p'}`;

/** Money → Compare → Busy times: when paid bookings happen, and what an hour of each kind of booking brings in. */
export default function BusyTimes({ year }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [by, setBy] = useState('bookings');
  useEffect(() => {
    setData(null);
    axios.get('/api/marketing/busy', {
      params: { start: new Date(year, 0, 1).toISOString(), end: new Date(year + 1, 0, 1).toISOString(), tz_offset: new Date(year, 6, 1).getTimezoneOffset() },
    }).then(({ data: d }) => { setData(d); setError(''); }).catch((err) => setError(errorMessage(err, "Couldn't load this.")));
  }, [year]);

  if (error) return <p className="text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">{error}</p>;
  if (!data) return null;
  if (data.bookings === 0) return <p className="text-sm text-gray-400 text-center py-10">No paid bookings in {year} yet.</p>;

  const cells = Object.fromEntries(data.grid.map((c) => [`${c.weekday}-${c.hour}`, c]));
  const hours = data.grid.map((c) => c.hour);
  const first = Math.min(...hours);
  const last = Math.max(...hours);
  const range = Array.from({ length: last - first + 1 }, (_, i) => first + i);
  const top = Math.max(...data.grid.map((c) => c[by])) || 1;
  const topDay = Math.max(...data.weekdays.map((d) => d[by])) || 1;
  const best = [...data.weekdays].sort((a, b) => b[by] - a[by])[0];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-gray-500 max-w-xl">
          When your paid bookings started in {year}. Darker means busier. Use it to choose when to be available, and when to post and renew ads.
        </p>
        <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Show">
          {[['bookings', 'Bookings'], ['income', 'Income']].map(([id, label]) => (
            <button key={id} onClick={() => setBy(id)} aria-pressed={by === id} className={`px-3 py-1.5 ${by === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{label}</button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto -mx-4 sm:mx-0 px-4 sm:px-0">
        <table className="text-xs border-separate" style={{ borderSpacing: 3 }}>
          <thead>
            <tr>
              <th />
              {range.map((h) => <th key={h} className="font-normal text-gray-400 w-8">{hourLabel(h)}</th>)}
              <th className="font-normal text-gray-400 pl-2 text-left">All day</th>
            </tr>
          </thead>
          <tbody>
            {DAYS.map((name, d) => (
              <tr key={name}>
                <th className="font-medium text-gray-600 text-left pr-2">{name}</th>
                {range.map((h) => {
                  const c = cells[`${d}-${h}`];
                  const value = c ? c[by] : 0;
                  return (
                    <td key={h} className="w-8 h-8 rounded text-center align-middle"
                      title={c ? `${name} ${hourLabel(h)}: ${c.bookings} booking${c.bookings === 1 ? '' : 's'}, ${money(c.income)}` : `${name} ${hourLabel(h)}: none`}
                      style={{ background: value ? `rgba(252, 76, 156, ${0.15 + 0.85 * (value / top)})` : 'rgba(107, 93, 112, 0.08)', color: value / top > 0.55 ? '#fff' : '#6b7280' }}>
                      {c ? c.bookings : ''}
                    </td>
                  );
                })}
                <td className="pl-2">
                  <span className="flex items-center gap-2">
                    <span className="inline-block h-3 rounded bg-sworkr-400" style={{ width: `${Math.max((data.weekdays[d][by] / topDay) * 80, data.weekdays[d][by] ? 4 : 0)}px` }} />
                    <span className="text-gray-600 whitespace-nowrap">{by === 'income' ? money(data.weekdays[d].income) : data.weekdays[d].bookings}</span>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {best[by] > 0 && <p className="text-sm text-gray-700">Your busiest day is <b>{['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][best.weekday]}</b>.</p>}

      <div>
        <h3 className="font-semibold text-gray-800">What an hour brings in</h3>
        <p className="text-sm text-gray-500 mb-2">
          Your share of what each kind of booking paid, for each hour it took. {data.per_hour != null && <>Across all of them: <b>{money(data.per_hour)}</b> an hour.</>}
        </p>
        <div className="overflow-x-auto -mx-4 sm:mx-0 px-4 sm:px-0">
          <table className="w-full text-sm min-w-[480px]">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="py-1.5 pr-2 font-medium">Kind of booking</th>
                <th className="py-1.5 px-1 font-medium text-right">Bookings</th>
                <th className="py-1.5 px-1 font-medium text-right">Hours</th>
                <th className="py-1.5 px-1 font-medium text-right">You kept</th>
                <th className="py-1.5 px-1 font-medium text-right">Per booking</th>
                <th className="py-1.5 px-1 font-medium text-right">Per hour</th>
              </tr>
            </thead>
            <tbody>
              {data.services.map((s) => (
                <tr key={s.service} className="border-b border-gray-50">
                  <td className="py-1.5 pr-2 text-gray-800">{s.service}</td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{s.bookings}</td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{s.hours}</td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{money(s.income)}</td>
                  <td className="py-1.5 px-1 text-right text-gray-600">{money(s.per_booking)}</td>
                  <td className="py-1.5 px-1 text-right font-semibold text-gray-800">{s.per_hour == null ? '—' : money(s.per_hour)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-gray-400 mt-1">This counts the booking's own length. Travel and getting ready aren't in it, so a short booking far away pays less than it looks.</p>
      </div>
    </div>
  );
}
