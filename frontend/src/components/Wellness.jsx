import { useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage } from './Modal';
import { money, toDateInput } from '../colors';

/** Settings > Health > Wellness log: on or off. */
export function WellnessSettings() {
  const [on, setOn] = useState(null);
  useEffect(() => {
    axios.get('/api/wellness/settings').then(({ data }) => setOn(data.enabled)).catch(() => setOn(false));
  }, []);
  if (on === null) return null;
  const toggle = async (e) => {
    const { data } = await axios.put('/api/wellness/settings', { enabled: e.target.checked });
    setOn(data.enabled);
  };
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={on} onChange={toggle} /> Show a daily check-in on the dashboard</label>
      <p className="text-xs text-gray-500">
        Sleep, water, how well you ate, and your energy, in a few taps. After a few weeks, the card shows how your earnings
        compare on better and worse days.
      </p>
      {on && <HealthImport />}
    </div>
  );
}

const Scale = ({ value, onChange, label }) => (
  <span className="flex items-center gap-1" role="radiogroup" aria-label={label}>
    {[1, 2, 3, 4, 5].map((n) => (
      <button key={n} type="button" role="radio" aria-checked={value === n} onClick={() => onChange(value === n ? null : n)}
        className={`w-7 h-7 rounded-full text-xs border ${value === n ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600'}`}>{n}</button>
    ))}
  </span>
);

/** Dashboard card: today's check-in, and how it lines up with money. Only when turned on. */
export function WellnessCard() {
  const [on, setOn] = useState(false);
  const [day, setDay] = useState(null);
  const [vs, setVs] = useState(null);
  const [message, setMessage] = useState('');
  const today = toDateInput(new Date());
  useEffect(() => {
    axios.get('/api/wellness/settings').then(({ data }) => {
      setOn(data.enabled);
      if (!data.enabled) return;
      axios.get('/api/wellness', { params: { days: 3 } }).then(({ data: rows }) => setDay(rows.find((r) => r.day === today) || { day: today }));
    }).catch(() => {});
  }, [today]);
  if (!on || !day) return null;
  const save = async (patch) => {
    const next = { ...day, ...patch };
    setDay(next);
    try {
      await axios.put('/api/wellness', next);
      setMessage('Saved');
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't save"));
    }
  };
  const showVs = async () => {
    const { data } = await axios.get('/api/wellness/vs-money');
    setVs(data);
  };
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-gray-800">Today's check-in</h2>
        <span className="text-xs text-gray-400">{message}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm text-gray-700">
        <label className="space-y-1"><span className="block text-xs text-gray-500">Sleep (hours)</span>
          <input type="number" min="0" max="24" step="0.5" value={day.sleep_hours ?? ''} onChange={(e) => setDay({ ...day, sleep_hours: e.target.value === '' ? null : Number(e.target.value) })} onBlur={() => save({})} className={inputClass} />
        </label>
        <label className="space-y-1"><span className="block text-xs text-gray-500">Water (glasses)</span>
          <input type="number" min="0" max="50" value={day.water_glasses ?? ''} onChange={(e) => setDay({ ...day, water_glasses: e.target.value === '' ? null : Number(e.target.value) })} onBlur={() => save({})} className={inputClass} />
        </label>
        <div><span className="block text-xs text-gray-500 mb-1">Ate well</span><Scale label="Ate well" value={day.food} onChange={(v) => save({ food: v })} /></div>
        <div><span className="block text-xs text-gray-500 mb-1">Energy</span><Scale label="Energy" value={day.energy} onChange={(v) => save({ energy: v })} /></div>
      </div>
      {!vs ? (
        <button type="button" onClick={showVs} className="text-sm text-sworkr-600 hover:text-sworkr-800">How it affects your money →</button>
      ) : (
        <div className="border-t border-gray-100 pt-2 text-sm">
          <p className="text-xs text-gray-500 mb-1">Average earned per logged day, last 6 months ({vs.days_logged} days logged{vs.days_logged < 20 ? ': still early' : ''}):</p>
          <ul className="space-y-1">
            {vs.comparisons.filter((c) => c.better_days || c.worse_days).map((c) => (
              <li key={c.title} className="text-gray-700">
                <b>{c.title}</b>: {c.better_label} {c.better_avg != null ? money(c.better_avg) : '–'} ({c.better_days} days) · {c.worse_label} {c.worse_avg != null ? money(c.worse_avg) : '–'} ({c.worse_days} days)
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Fill in sleep and water from the iPhone Health app's export (export.zip). */
function HealthImport() {
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const pick = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setBusy(true);
    setMessage(`Reading ${file.name}… a big export can take a few minutes.`);
    try {
      const { data } = await axios.post('/api/wellness/import-apple-health', file, { headers: { 'Content-Type': 'application/octet-stream' }, timeout: 0 });
      setMessage(`Done: sleep for ${data.sleep_days} days and water for ${data.water_days} days.`);
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't read that file"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="border-t border-gray-100 pt-3 space-y-1">
      <p className="text-sm font-medium text-gray-700">Import from Apple Health</p>
      <p className="text-xs text-gray-500">
        On your iPhone: Health app, tap your picture, then Export All Health Data. Save the zip and choose it here. Only sleep and
        water are read; what you've typed for food and energy stays.
      </p>
      <label className={`inline-block text-sm px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 cursor-pointer ${busy ? 'opacity-50' : 'hover:bg-gray-50'}`}>
        {busy ? 'Importing…' : 'Choose export.zip'}
        <input type="file" accept=".zip,.xml" onChange={pick} disabled={busy} className="hidden" />
      </label>
      {message && <p className="text-xs text-gray-600">{message}</p>}
    </div>
  );
}
