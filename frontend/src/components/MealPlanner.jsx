import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { inputClass, errorMessage, quietButtonClass } from './Modal';
import { dayLabel, toDateInput } from '../colors';

const MEALS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' };
const MACROS = [['calories', 'kcal'], ['protein', 'g protein'], ['carbs', 'g carbs'], ['fat', 'g fat']];

const monday = (d) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
const addDays = (iso, n) => { const x = new Date(`${iso}T12:00`); x.setDate(x.getDate() + n); return toDateInput(x); };

function ShoppingList({ start, version }) {
  const [items, setItems] = useState([]);
  const [label, setLabel] = useState('');
  const [message, setMessage] = useState('');
  const load = useCallback(() => { axios.get('/api/shopping').then(({ data }) => setItems(data)).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load, version]);
  const add = async (e) => {
    e.preventDefault();
    const { data } = await axios.post('/api/shopping', { label }).catch(() => ({ data: items }));
    setItems(data);
    setLabel('');
  };
  const tick = async (i) => { const { data } = await axios.post(`/api/shopping/${i.id}/done`, { done: !i.done }); setItems(data); };
  const fromMeals = async () => {
    const { data } = await axios.post('/api/shopping/from-meals', null, { params: { start } });
    setItems(data.items);
    setMessage(data.added ? `Added ${data.added} from this week's meals.` : 'Everything from this week is on the list already.');
  };
  const clear = async () => { const { data } = await axios.post('/api/shopping/clear-done'); setItems(data); };
  return (
    <section className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-gray-800">Shopping list</h2>
        <button type="button" onClick={fromMeals} className={quietButtonClass}>Add this week's groceries</button>
      </div>
      <ul className="space-y-1">
        {items.map((i) => (
          <li key={i.id}>
            <label className="flex items-center gap-3 py-1 text-sm">
              <input type="checkbox" checked={i.done} onChange={() => tick(i)} className="w-5 h-5" />
              <span className={i.done ? 'line-through text-gray-400' : 'text-gray-800'}>{i.label}</span>
            </label>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="flex gap-2">
        <input required value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Add, or several with commas" aria-label="Add to the list" className={inputClass} />
        <button type="submit" className="text-sm px-3 rounded-lg bg-sworkr-500 text-white">Add</button>
      </form>
      {items.some((i) => i.done) && <button type="button" onClick={clear} className="text-xs text-gray-500 hover:text-gray-800">Clear ticked items</button>}
      {message && <p className="text-xs text-gray-600">{message}</p>}
    </section>
  );
}

/** Calendar > Meals: a week of meals, a shopping list, and (if turned on) calories and macros. */
export default function MealPlanner() {
  const [start, setStart] = useState(toDateInput(monday(new Date())));
  const [week, setWeek] = useState(null);
  const [form, setForm] = useState({ day: toDateInput(new Date()), meal: 'dinner', what: '', groceries: '', calories: '', protein: '', carbs: '', fat: '' });
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const load = useCallback(() => {
    axios.get('/api/meals', { params: { start } }).then(({ data }) => setWeek(data)).catch(() => {});
  }, [start]);
  useEffect(() => { load(); }, [load]);
  if (!week) return null;
  const on = week.nutrition.enabled;
  const targets = week.nutrition.targets;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const num = (v) => (v === '' ? null : Number(v));
  const add = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const { data } = await axios.post('/api/meals', { ...form, calories: num(form.calories), protein: num(form.protein), carbs: num(form.carbs), fat: num(form.fat) }, { params: { start } });
      setWeek(data);
      setForm({ ...form, what: '', groceries: '', calories: '', protein: '', carbs: '', fat: '' });
    } catch (err) {
      setError(errorMessage(err, "Couldn't add it"));
    }
  };
  const remove = async (m) => { await axios.delete(`/api/meals/${m.id}`).catch(() => {}); load(); setVersion((v) => v + 1); };
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr] items-start">
      <section className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold text-gray-800">Meals, week of {dayLabel(new Date(`${start}T12:00`), { month: 'short', day: 'numeric' })}</h2>
          <span className="flex gap-1">
            <button type="button" onClick={() => setStart(addDays(start, -7))} className={quietButtonClass} aria-label="Week before">←</button>
            <button type="button" onClick={() => setStart(toDateInput(monday(new Date())))} className={quietButtonClass}>This week</button>
            <button type="button" onClick={() => setStart(addDays(start, 7))} className={quietButtonClass} aria-label="Week after">→</button>
          </span>
        </div>
        <ul className="divide-y divide-gray-100">
          {week.days.map((d) => (
            <li key={d.day} className="py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-gray-800">{dayLabel(new Date(`${d.day}T12:00`), { weekday: 'long', month: 'short', day: 'numeric' })}</span>
                {on && d.meals.length > 0 && (
                  <span className="text-xs text-gray-500 tabular-nums">
                    {MACROS.map(([k, unit]) => `${Math.round(d.totals[k])}${targets[k] ? `/${targets[k]}` : ''} ${unit}`).join(' · ')}
                  </span>
                )}
              </div>
              {d.meals.length === 0 ? <p className="text-xs text-gray-400">Nothing planned</p> : (
                <ul className="mt-1 space-y-0.5">
                  {d.meals.map((m) => (
                    <li key={m.id} className="flex items-start gap-2 text-sm">
                      <span className="w-20 shrink-0 text-xs text-gray-500 pt-0.5">{MEALS[m.meal]}</span>
                      <span className="flex-1">
                        <span className="text-gray-800">{m.what}</span>
                        {m.groceries && <span className="block text-xs text-gray-500">{m.groceries}</span>}
                      </span>
                      {on && m.calories != null && <span className="text-xs text-gray-500 tabular-nums">{Math.round(m.calories)} kcal</span>}
                      <button type="button" onClick={() => remove(m)} className="text-xs text-gray-400 hover:text-red-600" aria-label={`Remove ${m.what}`}>✕</button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
        <form onSubmit={add} className="grid grid-cols-2 sm:grid-cols-6 gap-2 border-t border-gray-100 pt-3">
          <input type="date" required value={form.day} onChange={set('day')} aria-label="Day" className={`${inputClass} sm:col-span-2`} />
          <select value={form.meal} onChange={set('meal')} aria-label="Meal" className={inputClass}>
            {Object.entries(MEALS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <input required value={form.what} onChange={set('what')} placeholder="What" aria-label="What" className={`${inputClass} col-span-2 sm:col-span-3`} />
          <input value={form.groceries} onChange={set('groceries')} placeholder="Groceries, comma separated" aria-label="Groceries" className={`${inputClass} col-span-2 sm:col-span-6`} />
          {on && MACROS.map(([k, unit]) => (
            <input key={k} type="number" min="0" step="1" value={form[k]} onChange={set(k)} placeholder={unit} aria-label={unit} className={inputClass} />
          ))}
          <button type="submit" className="col-span-2 sm:col-span-2 text-sm px-3 py-2 rounded-lg bg-sworkr-500 text-white">Add meal</button>
        </form>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!on && <p className="text-xs text-gray-500">Want calories and macros? Turn them on in <Link to="/account/health" className="underline">Settings → Health</Link>.</p>}
      </section>
      <ShoppingList start={start} version={version} />
    </div>
  );
}

/** Settings > Health > Calories & macros: off unless turned on, with daily targets of your own. */
export function NutritionSettings() {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState('');
  useEffect(() => {
    axios.get('/api/meals/nutrition').then(({ data }) => setForm({ enabled: data.enabled, ...Object.fromEntries(MACROS.map(([k]) => [k, data.targets[k] ?? ''])) })).catch(() => {});
  }, []);
  if (!form) return null;
  const save = async (next) => {
    setForm(next);
    const body = { enabled: next.enabled, ...Object.fromEntries(MACROS.map(([k]) => [k, next[k] === '' ? null : Number(next[k])])) };
    await axios.put('/api/meals/nutrition', body).then(() => setMessage('Saved.')).catch(() => setMessage("Couldn't save"));
  };
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.enabled} onChange={(e) => save({ ...form, enabled: e.target.checked })} /> Track calories and macros on meals
      </label>
      {form.enabled && (
        <div className="flex flex-wrap gap-2">
          {MACROS.map(([k, unit]) => (
            <label key={k} className="text-xs text-gray-500">Daily {unit}
              <input type="number" min="0" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} onBlur={() => save(form)} placeholder="No target" className={`${inputClass} !w-28 block`} />
            </label>
          ))}
        </div>
      )}
      <p className="text-xs text-gray-500">Only what you type in, and targets only if you set them. Nothing is suggested. {message}</p>
    </div>
  );
}
