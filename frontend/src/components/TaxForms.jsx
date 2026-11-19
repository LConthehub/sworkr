import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage } from './Modal';
import { money } from '../colors';

const VERDICT = {
  match: { text: 'Matches', badge: 'bg-emerald-100 text-emerald-700' },
  form_higher: { text: 'The form says more', badge: 'bg-red-100 text-red-700' },
  form_lower: { text: 'The form says less', badge: 'bg-amber-100 text-amber-800' },
  no_place: { text: 'Not one of your places', badge: 'bg-gray-100 text-gray-600' },
};

/** Money > Taxes: what each platform's tax form says, next to what you recorded. */
export default function TaxForms({ year }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ source_id: '', label: '', amount: '' });
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get('/api/tax-summary/forms', { params: { year, tz_offset: new Date().getTimezoneOffset() } }).then(({ data: d }) => setData(d)).catch(() => {});
  }, [year]);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const places = [...data.forms.filter((f) => f.source_id).map((f) => ({ source_id: f.source_id, name: f.source_name })), ...data.without_form]
    .filter((p, i, all) => all.findIndex((x) => x.source_id === p.source_id) === i);
  const add = async (e) => {
    e.preventDefault();
    try {
      await axios.post('/api/tax-summary/forms', { year, source_id: form.source_id ? Number(form.source_id) : null, label: form.label, amount: Number(form.amount) });
      setForm({ source_id: '', label: '', amount: '' });
      setError('');
      load();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  const remove = async (f) => { await axios.delete(`/api/tax-summary/forms/${f.id}`).catch(() => {}); load(); };
  return (
    <section className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3 print:hidden">
      <h2 className="font-semibold text-gray-800">Tax forms from platforms, {year}</h2>
      <p className="text-sm text-gray-600">
        Platforms send the tax office a form saying what they paid you (a 1099 in the US). Type in the amount on each one, and
        Sworkr puts it next to what you recorded for that place, so a gap is found before the tax office finds it.
      </p>
      {data.forms.length > 0 && (
        <ul className="divide-y divide-gray-100">
          {data.forms.map((f) => (
            <li key={f.id} className="py-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="flex-1 min-w-40">
                <span className="block text-sm font-medium text-gray-800">{f.source_name || f.label}{f.source_name && f.label ? ` · ${f.label}` : ''}</span>
                <span className="block text-xs text-gray-500">
                  The form: {money(f.amount)}
                  {f.recorded_gross != null && ` · you recorded ${money(f.recorded_gross)} before fees, ${money(f.recorded_net)} after`}
                  {f.gap != null && f.verdict !== 'match' && ` · ${money(Math.abs(f.gap))} apart`}
                </span>
              </span>
              <span className={`text-[10px] px-2 py-0.5 rounded-full ${VERDICT[f.verdict].badge}`}>{VERDICT[f.verdict].text}{f.verdict === 'match' && f.matches ? ` (${f.matches})` : ''}</span>
              <button type="button" onClick={() => remove(f)} className="text-xs text-gray-400 hover:text-red-600" aria-label="Remove this form">✕</button>
            </li>
          ))}
        </ul>
      )}
      {data.forms.some((f) => f.verdict === 'form_higher') && (
        <p className="text-xs text-gray-600">Where the form says more, look for income you forgot to log for that place: the tax office goes by the form.</p>
      )}
      {data.without_form.length > 0 && (
        <p className="text-xs text-gray-500">
          Paid you this year, with no form typed in yet: {data.without_form.map((p) => `${p.name} (${money(p.recorded_gross)})`).join(', ')}.
          Not every place sends one, and you still report the income.
        </p>
      )}
      <form onSubmit={add} className="grid grid-cols-2 sm:grid-cols-[1fr_1fr_8rem_auto] gap-2">
        <select value={form.source_id} onChange={(e) => setForm({ ...form, source_id: e.target.value })} aria-label="Which place" className={inputClass}>
          <option value="">Someone else…</option>
          {places.map((p) => <option key={p.source_id} value={p.source_id}>{p.name}</option>)}
        </select>
        <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder={form.source_id ? 'Form name (optional)' : 'Who it is from'} aria-label="Form name or payer" className={inputClass} />
        <input required type="number" min="0" step="0.01" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} placeholder="Amount" aria-label="Amount on the form" className={inputClass} />
        <button type="submit" className="text-sm px-3 py-2 rounded-lg bg-sworkr-500 text-white">Add</button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </section>
  );
}
