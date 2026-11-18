import { useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage } from './Modal';

const names = (() => {
  try { return new Intl.DisplayNames(undefined, { type: 'region' }); } catch { return null; }
})();
const countryName = (code) => { try { return names?.of(code) || code; } catch { return code; } };

/** Settings > My work > Holidays: public holidays on the calendar, worked out on this computer. */
export default function HolidaySettings() {
  const [data, setData] = useState(null);
  const [message, setMessage] = useState('');
  useEffect(() => {
    axios.get('/api/holidays/settings').then(({ data: d }) => setData(d)).catch(() => {});
  }, []);
  if (!data) return null;
  const countries = [...data.countries].sort((a, b) => countryName(a.code).localeCompare(countryName(b.code)));
  const chosen = data.countries.find((c) => c.code === data.country);
  const save = async (country, subdivision) => {
    setMessage('');
    try {
      const { data: s } = await axios.put('/api/holidays/settings', { country: country || null, subdivision: subdivision || null });
      setData({ ...data, ...s });
      setMessage(s.country ? 'Holidays are on your calendar.' : 'No holidays on the calendar.');
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't save"));
    }
  };
  return (
    <div className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-2">
        <select value={data.country || ''} onChange={(e) => save(e.target.value, '')} aria-label="Country" className={inputClass}>
          <option value="">No holidays</option>
          {countries.map((c) => <option key={c.code} value={c.code}>{countryName(c.code)}</option>)}
        </select>
        {chosen?.subdivisions.length > 0 && (
          <select value={data.subdivision || ''} onChange={(e) => save(data.country, e.target.value)} aria-label="State or province" className={inputClass}>
            <option value="">The whole country</option>
            {chosen.subdivisions.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </div>
      <p className="text-xs text-gray-500">Public holidays show on the calendar. They're worked out on this computer: no calendar is downloaded from anyone.</p>
      {message && <p className="text-sm text-gray-600">{message}</p>}
    </div>
  );
}
