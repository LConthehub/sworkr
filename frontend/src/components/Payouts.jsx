import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, quietButtonClass } from './Modal';
import { money, toDateInput } from '../colors';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const dayText = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
const awayText = (d) => (d.late ? `${-d.days_away} day${d.days_away === -1 ? '' : 's'} late` : d.days_away === 0 ? 'today' : d.days_away === 1 ? 'tomorrow' : `in ${d.days_away} days`);

/** Money > Payouts: when pending money should land, by day, and each place's payout day. */
export default function Payouts() {
  const [data, setData] = useState(null);
  const load = useCallback(() => {
    axios.get('/api/payouts', { params: { today: toDateInput(new Date()) } }).then(({ data: d }) => setData(d)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const nothing = data.days.length === 0 && data.undated.length === 0;
  return (
    <div className="grid gap-4 lg:grid-cols-2 items-start">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
        <h2 className="font-semibold text-gray-800">Money on its way</h2>
        <p className="text-sm text-gray-600">
          Income you've marked as pending, on the day it should arrive. Mark it as arrived under Income &amp; expenses when it lands.
        </p>
        {nothing ? (
          <p className="text-sm text-gray-400 py-6 text-center">Nothing pending. When a platform or a house is holding money, log it as pending and it shows here.</p>
        ) : (
          <>
            <p className="text-sm text-gray-800">
              <b>{money(data.expected)}</b> expected{data.late > 0 && <span className="text-red-600"> · {money(data.late)} late</span>}
              {data.undated_total > 0 && <span className="text-gray-500"> · {money(data.undated_total)} with no day yet</span>}
            </p>
            <ul className="divide-y divide-gray-100">
              {data.days.map((d) => (
                <li key={d.date} className="py-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={`text-sm font-medium ${d.late ? 'text-red-700' : 'text-gray-800'}`}>{dayText(d.date)} <span className="font-normal text-xs text-gray-500">{awayText(d)}</span></span>
                    <span className="text-sm font-semibold text-gray-800">{money(d.total)}</span>
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {d.items.map((i) => (
                      <li key={i.id} className="flex justify-between gap-2 text-xs text-gray-500">
                        <span>{i.source_name || 'No place'}{i.description ? ` · ${i.description}` : ''} · earned {i.earned_on}{i.guessed ? ' · from the payout day' : ''}</span>
                        <span>{money(i.net)}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            {data.undated.length > 0 && (
              <div className="border-t border-gray-100 pt-2">
                <p className="text-xs font-medium text-gray-700">No day yet (set the place's payout day, or a payout date on the entry):</p>
                <ul className="mt-1 space-y-0.5">
                  {data.undated.map((i) => (
                    <li key={i.id} className="flex justify-between gap-2 text-xs text-gray-500">
                      <span>{i.source_name || 'No place'}{i.description ? ` · ${i.description}` : ''} · earned {i.earned_on}</span><span>{money(i.net)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
        <h2 className="font-semibold text-gray-800">Payout days</h2>
        <p className="text-sm text-gray-600">Tell Sworkr when each place pays, and pending money gets its day by itself.</p>
        {data.places.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">Add the places you earn under Settings first.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {data.places.map((p) => <PlaceRule key={p.source_id} place={p} onChanged={load} />)}
          </ul>
        )}
      </div>
    </div>
  );
}

function PlaceRule({ place, onChanged }) {
  const [every, setEvery] = useState(place.every || '');
  const [day, setDay] = useState(place.day ?? '');
  const save = async (nextEvery, nextDay) => {
    setEvery(nextEvery);
    setDay(nextDay);
    if (!nextEvery) await axios.delete(`/api/payouts/rules/${place.source_id}`).catch(() => {});
    else if (nextEvery === 'twice_monthly' || nextDay !== '') await axios.put(`/api/payouts/rules/${place.source_id}`, { every: nextEvery, day: Number(nextDay) || 0 }).catch(() => {});
    else return;
    onChanged();
  };
  const defaults = { weekly: 4, twice_monthly: 0, monthly: 1, days_after: 7 };
  return (
    <li className="py-2 space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-1 min-w-32 text-sm text-gray-800">{place.name}</span>
        <select value={every} onChange={(e) => save(e.target.value, e.target.value ? defaults[e.target.value] : '')} aria-label={`How ${place.name} pays out`} className={`${inputClass} w-auto`}>
          <option value="">Not set</option>
          <option value="weekly">Every week</option>
          <option value="twice_monthly">The 1st and the 15th</option>
          <option value="monthly">Once a month</option>
          <option value="days_after">Days after it's earned</option>
        </select>
        {every === 'weekly' && (
          <select value={day} onChange={(e) => save(every, e.target.value)} aria-label="Which day" className={`${inputClass} w-auto`}>
            {WEEKDAYS.map((w, i) => <option key={w} value={i}>{w}</option>)}
          </select>
        )}
        {every === 'monthly' && (
          <label className="flex items-center gap-1 text-xs text-gray-500">day
            <input type="number" min="1" max="28" value={day} onChange={(e) => save(every, e.target.value)} className={`${inputClass} w-16`} />
          </label>
        )}
        {every === 'days_after' && (
          <label className="flex items-center gap-1 text-xs text-gray-500">
            <input type="number" min="0" max="120" value={day} onChange={(e) => save(every, e.target.value)} className={`${inputClass} w-16`} /> days
          </label>
        )}
        {every && <button type="button" onClick={() => save('', '')} className={quietButtonClass}>Clear</button>}
      </div>
      {place.payout_note && <p className="text-xs text-gray-400">{place.payout_note}</p>}
    </li>
  );
}
