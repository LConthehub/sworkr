import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { inputClass, errorMessage } from './Modal';
import { money } from '../colors';
import { useCategories } from '../api';

const small = `${inputClass} !py-1.5`;

/** A tour's pack list: items from your templates or typed in, ticked off as you pack. */
export function PackList({ tourId }) {
  const [items, setItems] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [label, setLabel] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/tours/${tourId}/pack`).then(({ data }) => setItems(data)).catch(() => setItems([]));
    axios.get('/api/pack-templates').then(({ data }) => setTemplates(data)).catch(() => {});
  }, [tourId]);
  useEffect(() => { load(); }, [load]);

  const run = async (request) => {
    setError('');
    try { const { data } = await request(); if (Array.isArray(data)) setItems(data); else load(); } catch (err) { setError(errorMessage(err, "Couldn't save")); }
  };
  const addTemplate = (t) => run(() => axios.post(`/api/tours/${tourId}/pack`, t.id ? { template_id: t.id } : { items: t.items }));
  const saveAsTemplate = async () => {
    const name = window.prompt('Save this list as a template called:', 'Tour basics');
    if (!name) return;
    await run(() => axios.post('/api/pack-templates', { name, items: items.map((i) => i.label) }));
    load();
  };

  if (items === null) return null;
  const packed = items.filter((i) => i.packed).length;
  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h3 className="font-semibold text-gray-800">Pack list {items.length > 0 && <span className="text-sm font-normal text-gray-500">{packed} of {items.length} packed</span>}</h3>
        <div className="flex flex-wrap gap-2 text-xs">
          {templates.map((t) => (
            <button key={t.id ?? 'starter'} type="button" onClick={() => addTemplate(t)} className="text-sworkr-600 hover:text-sworkr-800">+ {t.name}</button>
          ))}
          {items.length > 0 && <button type="button" onClick={saveAsTemplate} className="text-gray-500 hover:text-gray-800">Save as template</button>}
        </div>
      </div>
      <ul className="space-y-1">
        {items.map((i) => (
          <li key={i.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={i.packed} onChange={(e) => run(() => axios.put(`/api/tour-pack/${i.id}`, { packed: e.target.checked }))} aria-label={`Packed: ${i.label}`} />
            <span className={`flex-1 ${i.packed ? 'line-through text-gray-400' : 'text-gray-700'}`}>{i.label}</span>
            <button type="button" onClick={() => run(async () => { await axios.delete(`/api/tour-pack/${i.id}`); return { data: null }; })} className="text-xs text-gray-400 hover:text-red-600" aria-label={`Remove ${i.label}`}>✕</button>
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); if (label.trim()) run(() => axios.post(`/api/tours/${tourId}/pack`, { label })).then(() => setLabel('')); }} className="flex gap-2 mt-2">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Add an item" aria-label="Add an item" className={small} />
      </form>
      {error && <p className="text-sm text-red-600 mt-1">{error}</p>}
    </section>
  );
}

/** A tour's budget: planned per main category, against what's actually been spent. */
export function TourBudget({ tourId, version }) {
  const cats = useCategories();
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);   // { key: amount }
  const [error, setError] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/tours/${tourId}/budget`).then(({ data: d }) => setData(d)).catch(() => {});
  }, [tourId]);
  useEffect(() => { load(); }, [load, version]);

  const startEdit = () => setEditing(Object.fromEntries(cats.tops.map((c) => [c.key, String(data.lines.find((l) => l.category === c.key)?.planned ?? '')])));
  const save = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const lines = Object.entries(editing).filter(([, v]) => v !== '' && Number(v) > 0).map(([category, v]) => ({ category, planned: Number(v) }));
      const { data: d } = await axios.put(`/api/tours/${tourId}/budget`, { lines });
      setData(d);
      setEditing(null);
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the budget"));
    }
  };

  if (!data) return null;
  return (
    <section>
      <div className="flex items-baseline justify-between gap-2 mb-2">
        <h3 className="font-semibold text-gray-800">Budget</h3>
        {!editing && <button type="button" onClick={startEdit} className="text-xs text-sworkr-600 hover:text-sworkr-800">{data.planned ? 'Change' : 'Plan a budget'}</button>}
      </div>
      {editing ? (
        <form onSubmit={save} className="space-y-1.5">
          {cats.tops.filter((c) => !c.hidden).map((c) => (
            <label key={c.key} className="flex items-center gap-2 text-sm">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: c.color }} />
              <span className="flex-1 text-gray-700">{c.label}</span>
              <span className="text-gray-400">$</span>
              <input type="number" min="0" step="1" value={editing[c.key] ?? ''} onChange={(e) => setEditing({ ...editing, [c.key]: e.target.value })} className={`${small} w-24`} />
            </label>
          ))}
          <div className="flex gap-2 pt-1">
            <button type="submit" className="text-sm px-3 py-1.5 rounded-lg bg-sworkr-500 text-white">Save</button>
            <button type="button" onClick={() => setEditing(null)} className="text-sm px-3 py-1.5 rounded-lg text-gray-600">Cancel</button>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </form>
      ) : data.lines.length === 0 ? (
        <p className="text-sm text-gray-400">No plan yet, and nothing spent.</p>
      ) : (
        <dl className="text-sm space-y-1">
          {data.lines.map((l) => {
            const over = l.planned != null && l.actual > l.planned;
            return (
              <div key={l.category}>
                <div className="flex justify-between gap-3">
                  <dt className="flex items-center gap-1.5 text-gray-700"><span className="w-2.5 h-2.5 rounded-full" style={{ background: l.color }} />{l.label}</dt>
                  <dd className={`tabular-nums ${over ? 'text-red-600 font-semibold' : 'text-gray-700'}`}>{money(l.actual)}{l.planned != null && <span className="text-gray-400"> / {money(l.planned)}</span>}</dd>
                </div>
                {l.planned ? (
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mt-0.5">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, (l.actual / l.planned) * 100)}%`, background: over ? '#dc2626' : l.color }} />
                  </div>
                ) : null}
              </div>
            );
          })}
          <div className="flex justify-between font-semibold border-t border-gray-200 pt-1 mt-1">
            <dt>{data.left == null ? 'Spent' : data.left >= 0 ? 'Left to spend' : 'Over budget'}</dt>
            <dd className="tabular-nums">{data.left == null ? money(data.actual) : money(Math.abs(data.left))}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

const MEAL_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' };

/** Meals and snacks for a tour: groceries go onto the pack list in one tap, costs become the food budget. */
export function Meals({ tour, onChanged }) {
  const [meals, setMeals] = useState(null);
  const [form, setForm] = useState({ day: '', meal: 'dinner', what: '', groceries: '', cost: '' });
  const [message, setMessage] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/tours/${tour.id}/meals`).then(({ data }) => setMeals(data)).catch(() => setMeals([]));
  }, [tour.id]);
  useEffect(() => { load(); }, [load]);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const add = async (e) => {
    e.preventDefault();
    setMessage('');
    try {
      const { data } = await axios.post(`/api/tours/${tour.id}/meals`, { ...form, day: form.day || null, cost: form.cost === '' ? null : Number(form.cost) });
      setMeals(data);
      setForm({ ...form, what: '', groceries: '', cost: '' });
      onChanged();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't add it"));
    }
  };
  const remove = async (m) => {
    await axios.delete(`/api/tour-meals/${m.id}`).catch(() => {});
    load();
    onChanged();
  };
  const toPack = async () => {
    const { data } = await axios.post(`/api/tours/${tour.id}/meals/to-pack`);
    setMessage(data.added ? `Added ${data.added} to the pack list.` : 'Everything is already on the pack list.');
    onChanged();
  };

  if (meals === null) return null;
  const total = meals.reduce((sum, m) => sum + (m.cost || 0), 0);
  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h3 className="font-semibold text-gray-800">Meals & snacks {total > 0 && <span className="text-sm font-normal text-gray-500">about {money(total)}</span>}</h3>
        {meals.some((m) => m.groceries) && <button type="button" onClick={toPack} className="text-xs text-sworkr-600 hover:text-sworkr-800">Groceries → pack list</button>}
      </div>
      <ul className="space-y-1 text-sm">
        {meals.map((m) => (
          <li key={m.id} className="flex items-start gap-2">
            <span className="w-20 shrink-0 text-xs text-gray-500 pt-0.5">{m.day ? m.day.slice(5) : 'Any day'} · {MEAL_LABELS[m.meal]}</span>
            <span className="flex-1">
              <span className="text-gray-800">{m.what}</span>
              {m.groceries && <span className="block text-xs text-gray-500">{m.groceries}</span>}
            </span>
            {m.cost != null && <span className="text-xs text-gray-500 tabular-nums">{money(m.cost)}</span>}
            <button type="button" onClick={() => remove(m)} className="text-xs text-gray-400 hover:text-red-600" aria-label={`Remove ${m.what}`}>✕</button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="grid grid-cols-2 sm:grid-cols-6 gap-2 mt-2">
        <input type="date" value={form.day} min={tour.start_date} max={tour.end_date} onChange={set('day')} aria-label="Day (optional)" className={`${small} col-span-1 sm:col-span-2`} />
        <select value={form.meal} onChange={set('meal')} aria-label="Meal" className={`${small} col-span-1`}>
          {Object.entries(MEAL_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input required value={form.what} onChange={set('what')} placeholder="What" aria-label="What" className={`${small} col-span-2 sm:col-span-3`} />
        <input value={form.groceries} onChange={set('groceries')} placeholder="Groceries, comma separated" aria-label="Groceries" className={`${small} col-span-2 sm:col-span-4`} />
        <input type="number" min="0" step="0.5" value={form.cost} onChange={set('cost')} placeholder="$ about" aria-label="Rough cost" className={`${small} col-span-1`} />
        <button type="submit" className="col-span-1 text-sm px-3 py-1.5 rounded-lg bg-sworkr-500 text-white">Add</button>
      </form>
      {message && <p className="text-xs text-gray-600 mt-1">{message}</p>}
    </section>
  );
}

/** Everything for planning a tour, in one place: pack list, budget, meals. */
export function TourPlanning({ tour, version }) {
  const [bump, setBump] = useState(0);
  const changed = () => setBump((n) => n + 1);
  return (
    <div className="rounded-xl border border-gray-100 p-4 space-y-5">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">Tour plan</h3>
      <div className="grid gap-5 lg:grid-cols-2">
        <PackList key={`pack-${bump}`} tourId={tour.id} />
        <TourBudget tourId={tour.id} version={`${version}-${bump}`} />
      </div>
      {tour.purpose === 'convention' && <Convention tour={tour} onChanged={changed} />}
      <Meals tour={tour} onChanged={changed} />
    </div>
  );
}

/** A convention's booth and promo list: what to bring and buy, what it costs, and what's bought already. */
function Convention({ tour, onChanged }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ kind: 'promo', label: '', qty: '1', unit_cost: '' });
  const [message, setMessage] = useState('');
  const load = useCallback(() => {
    axios.get(`/api/tours/${tour.id}/convention`).then(({ data: d }) => setData(d)).catch(() => setData(null));
  }, [tour.id]);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const add = async (item) => {
    setMessage('');
    try {
      const { data: d } = await axios.post(`/api/tours/${tour.id}/convention`, item);
      setData(d);
      setForm({ ...form, label: '', qty: '1', unit_cost: '' });
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't add it"));
    }
  };
  const buy = async (i) => {
    try {
      const { data: d } = await axios.post(`/api/convention-items/${i.id}/bought`);
      setData(d);
      onChanged();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't mark it bought"));
    }
  };
  const remove = async (i) => { await axios.delete(`/api/convention-items/${i.id}`).catch(() => {}); load(); };
  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
        <h3 className="font-semibold text-gray-800">Booth & promo</h3>
        <span className="text-sm text-gray-500">{money(data.bought)} bought of {money(data.planned)} planned</span>
      </div>
      {data.starter.length > 0 && (
        <p className="flex flex-wrap items-center gap-1 mb-2 text-xs text-gray-500">Ideas:
          {data.starter.map((st) => (
            <button key={st.label} type="button" onClick={() => add({ kind: st.kind, label: st.label, qty: 1 })} className="px-2 py-0.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">{st.label}</button>
          ))}
        </p>
      )}
      <ul className="divide-y divide-gray-100 text-sm">
        {data.items.map((i) => (
          <li key={i.id} className="py-1.5 flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-500 w-24">{data.kinds[i.kind]}</span>
            <span className="flex-1 min-w-32 text-gray-800">{i.label}{i.qty !== 1 && <span className="text-gray-500"> × {i.qty}</span>}</span>
            <span className="tabular-nums text-gray-600">{i.total != null ? money(i.total) : '–'}</span>
            {i.bought ? <span className="text-xs text-emerald-700">✓ Bought</span>
              : <button type="button" onClick={() => buy(i)} disabled={i.unit_cost == null} title={i.unit_cost == null ? 'Add what it cost first' : ''} className="text-xs px-2 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40">Bought</button>}
            <button type="button" onClick={() => remove(i)} className="text-xs text-gray-400 hover:text-red-600" aria-label={`Remove ${i.label}`}>✕</button>
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); add({ ...form, qty: Number(form.qty) || 1, unit_cost: form.unit_cost === '' ? null : Number(form.unit_cost) }); }}
        className="grid grid-cols-2 sm:grid-cols-[8rem_1fr_5rem_6rem_auto] gap-2 mt-2">
        <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} aria-label="Kind" className={small}>
          {Object.entries(data.kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input required value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="What" aria-label="What" className={small} />
        <input type="number" min="0" step="1" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} aria-label="How many" className={small} />
        <input type="number" min="0" step="0.5" value={form.unit_cost} onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} placeholder="$ each" aria-label="Cost each" className={small} />
        <button type="submit" className="text-sm px-3 py-1.5 rounded-lg bg-sworkr-500 text-white">Add</button>
      </form>
      {message && <p className="text-xs text-red-600 mt-1">{message}</p>}
      <p className="text-xs text-gray-500 mt-1">Bought ones go into this trip's expenses and budget. Sales at the convention: use "Sold something" on the dashboard.</p>
    </section>
  );
}
