import { useEffect, useState } from 'react';
import axios from 'axios';
import { useTestKinds } from './TestKinds';
import { Field, inputClass, errorMessage, buttonClass } from './Modal';
import { fetchAll, isDemo, reloadCategories, useCategories } from '../api';
import { SplitEditor, useSplit } from './Splits';
import { PersonaSelect } from './Personas';
import { CADENCES, INCOME_KINDS, money, SOURCE_KINDS, toDateInput } from '../colors';

const numberOrNull = (value) => (value === '' || value == null ? null : Number(value));

// ==================== EXPENSE CATEGORIES ====================

/**
 * Expense categories in two levels: main categories (everyone has the same ones to start with, renameable)
 * and subcategories under them. Rename, recolour, hide, move, add and delete.
 */
export function CategoryManager() {
  const cats = useCategories();
  const [adding, setAdding] = useState({});   // { [main key]: label being typed }
  const [newTop, setNewTop] = useState('');
  const [error, setError] = useState('');

  const run = async (request) => {
    setError('');
    try {
      await request();
      await reloadCategories();
      return true;
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
      return false;
    }
  };
  // parent_key is only sent when moving, so a plain rename never moves anything.
  const save = (c, changes) => run(() => axios.put(`/api/expense-categories/${c.key}`, { label: c.label, hidden: c.hidden, ...changes }));
  const add = async (label, parentKey) => {
    if (!label.trim()) return;
    if (await run(() => axios.post('/api/expense-categories', { label: label.trim(), parent_key: parentKey }))) {
      if (parentKey) setAdding((a) => ({ ...a, [parentKey]: undefined }));
      else setNewTop('');
    }
  };
  const remove = (c) => {
    const subs = cats.subsOf(c.key).length;
    const notes = [
      c.used && `Its ${c.used} expense${c.used === 1 ? '' : 's'} will move to Other.`,
      subs && `Its ${subs} subcategor${subs === 1 ? 'y' : 'ies'} will move under Other.`,
    ].filter(Boolean).join(' ');
    if (window.confirm(`Delete the category "${c.label}"? ${notes}`)) run(() => axios.delete(`/api/expense-categories/${c.key}`));
  };

  const row = (c, sub = false) => (
    <div key={c.key} className={`flex items-center gap-2 py-1.5 ${sub ? 'pl-6' : ''}`}>
      {sub ? (
        <span className="w-2.5 h-2.5 rounded-full shrink-0 ml-2.5 mr-0.5" style={{ background: c.color }} aria-hidden="true" />
      ) : (
        <input
          type="color"
          value={c.color || '#9ca3af'}
          onChange={(e) => save(c, { color: e.target.value })}
          className="w-8 h-8 shrink-0 rounded cursor-pointer border border-gray-200"
          aria-label={`Colour for ${c.label}`}
        />
      )}
      <input
        key={c.label}
        defaultValue={c.label}
        onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== c.label && save(c, { label: e.target.value.trim() })}
        className={`${inputClass} ${sub ? '' : 'font-medium'} ${c.hidden ? 'text-gray-400' : ''}`}
        aria-label={sub ? `Name of subcategory ${c.label}` : `Name of category ${c.label}`}
      />
      {sub && (
        <select
          value={c.parent_key}
          onChange={(e) => save(c, { parent_key: e.target.value })}
          className="text-xs text-gray-600 border border-gray-200 rounded-lg py-1.5 px-1 w-28 shrink-0 bg-white"
          aria-label={`Move ${c.label} to another main category`}
          title="Move to another main category"
        >
          {cats.tops.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      )}
      <span className="text-xs text-gray-400 w-8 text-right shrink-0" title="Expenses in this category">{c.used || ''}</span>
      {c.key !== 'other' ? (
        <button type="button" onClick={() => save(c, { hidden: !c.hidden })} className="text-xs text-gray-500 hover:text-gray-800 w-10 shrink-0">
          {c.hidden ? 'Show' : 'Hide'}
        </button>
      ) : <span className="w-10 shrink-0" />}
      {!c.builtin ? (
        <button type="button" onClick={() => remove(c)} className="text-xs text-red-500 hover:text-red-700 w-12 shrink-0">Delete</button>
      ) : <span className="w-12 shrink-0" />}
    </div>
  );

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-500">
        Main categories keep your totals tidy; subcategories say exactly what it was. Rename anything to your own words,
        move a subcategory with its menu, or hide what you don't use. Built-in categories can be hidden but not deleted.
      </p>
      <ul className="divide-y divide-gray-100">
        {cats.tops.map((top) => (
          <li key={top.key} className="py-1.5">
            {row(top)}
            {cats.subsOf(top.key).map((c) => row(c, true))}
            {adding[top.key] !== undefined ? (
              <form onSubmit={(e) => { e.preventDefault(); add(adding[top.key], top.key); }} className="flex gap-2 pl-6 py-1.5">
                <input
                  autoFocus
                  value={adding[top.key]}
                  onChange={(e) => setAdding((a) => ({ ...a, [top.key]: e.target.value }))}
                  onKeyDown={(e) => e.key === 'Escape' && setAdding((a) => ({ ...a, [top.key]: undefined }))}
                  placeholder={`New subcategory of ${top.label}`}
                  className={inputClass}
                  aria-label={`New subcategory of ${top.label}`}
                />
                <button type="submit" disabled={!adding[top.key].trim()} className={buttonClass}>Add</button>
              </form>
            ) : (
              <button type="button" onClick={() => setAdding((a) => ({ ...a, [top.key]: '' }))} className="ml-6 text-xs text-sworkr-600 hover:text-sworkr-800 py-1">
                + Subcategory
              </button>
            )}
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); add(newTop, null); }} className="flex gap-2">
        <input value={newTop} onChange={(e) => setNewTop(e.target.value)} placeholder="New main category" className={inputClass} aria-label="New main category" />
        <button type="submit" disabled={!newTop.trim()} className={buttonClass}>Add</button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

/**
 * A category picker: each main category, with its subcategories indented under it. Hidden ones are left
 * out unless already chosen.
 */
export function CategorySelect({ value, onChange, className = inputClass, ...rest }) {
  const cats = useCategories();
  const shown = (c) => !c.hidden || c.key === value;
  return (
    <select value={value} onChange={onChange} className={className} {...rest}>
      {cats.tops.filter((t) => shown(t) || cats.subsOf(t.key).some(shown)).flatMap((t) => [
        <option key={t.key} value={t.key}>{t.label}</option>,
        ...cats.subsOf(t.key).filter(shown).map((c) => (
          <option key={c.key} value={c.key}>{'    '}{c.label}</option>
        )),
      ])}
    </select>
  );
}

// ==================== CHARGES A PLACE MAKES ====================

const BLANK_CHARGE = { label: '', amount: '', cadence: 'per_day', category: 'other', test_type: '', renews_on: '' };

// What each kind of place usually charges, offered when adding a new one. Amounts are left for you.
const SUGGESTED_CHARGES = {
  brothel: [
    { label: 'Room & board', cadence: 'per_day', category: 'room_rent' },
    { label: 'Doctor', cadence: 'per_week', category: 'medical', test_type: 'weekly' },
  ],
  studio: [{ label: 'Room hire', cadence: 'per_booking', category: 'workspace' }],
  event: [{ label: 'Table or booth', cadence: 'per_stay', category: 'travel' }],
};

const RENEWABLE = ['per_quarter', 'per_year', 'once'];

const chargeToRow = (c) => ({
  key: c.id, id: c.id, label: c.label, amount: c.amount ?? '', cadence: c.cadence, category: c.category,
  test_type: c.test_type || '', renews_on: c.renews_on || '', original: c,
});

const rowToBody = (r) => ({
  label: r.label.trim(), amount: numberOrNull(r.amount), cadence: r.cadence, category: r.category,
  test_type: r.test_type || null, renews_on: RENEWABLE.includes(r.cadence) ? (r.renews_on || null) : null,
});

/** Save a place's charges: add new rows, update changed ones, delete removed ones. Blank new rows are skipped. */
async function saveCharges(sourceId, rows, removedIds) {
  for (const id of removedIds) await axios.delete(`/api/place-charges/${id}`);
  for (const r of rows) {
    if (!r.label.trim()) continue;
    const body = rowToBody(r);
    if (!r.id) await axios.post(`/api/income-sources/${sourceId}/charges`, body);
    else if (JSON.stringify(rowToBody(chargeToRow(r.original))) !== JSON.stringify(body)) await axios.put(`/api/place-charges/${r.id}`, body);
  }
}

/** "Room & board $120 a day", "License $275 a year, renew by 3 Mar 2027" */
export function chargeSummary(c) {
  const price = c.amount != null ? `${money(c.amount)} ${CADENCES[c.cadence]}` : `amount not set, ${CADENCES[c.cadence]}`;
  const renew = c.renews_on ? `, renew by ${new Date(`${c.renews_on}T12:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}` : '';
  return `${c.label} ${price}${renew}`;
}

function ChargesEditor({ rows, onChange, onRemove }) {
  const { labels: TEST_TYPES } = useTestKinds();
  const update = (i, changes) => onChange(rows.map((r, j) => (j === i ? { ...r, ...changes } : r)));
  const remove = (i) => { onRemove(rows[i]); onChange(rows.filter((_, j) => j !== i)); };
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={r.key} className="rounded-xl border border-gray-100 p-2 space-y-2">
          <div className="grid grid-cols-[1fr_6rem_7.5rem] gap-2">
            <input value={r.label} onChange={(e) => update(i, { label: e.target.value })} placeholder="e.g. Room & board" aria-label="Charge" className={inputClass} />
            <input type="number" min="0" step="0.01" inputMode="decimal" value={r.amount} onChange={(e) => update(i, { amount: e.target.value })} placeholder="$" aria-label={`Amount for ${r.label || 'this charge'}`} className={inputClass} />
            <select value={r.cadence} onChange={(e) => update(i, { cadence: e.target.value })} aria-label={`How often for ${r.label || 'this charge'}`} className={inputClass}>
              {Object.entries(CADENCES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
            <label className="flex items-center gap-1.5 text-gray-700">
              <input type="checkbox" checked={!!r.test_type} onChange={(e) => update(i, { test_type: e.target.checked ? 'weekly' : '', category: e.target.checked ? 'medical' : r.category })} />
              Health check
            </label>
            {r.test_type ? (
              <select value={r.test_type} onChange={(e) => update(i, { test_type: e.target.value })} aria-label="Kind of health test" className="text-sm border border-gray-200 rounded-lg py-1 px-1 bg-white">
                {Object.entries(TEST_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            ) : (
              <CategorySelect value={r.category} onChange={(e) => update(i, { category: e.target.value })} aria-label={`Expense category for ${r.label || 'this charge'}`} className="text-sm border border-gray-200 rounded-lg py-1 px-1 bg-white max-w-[12rem]" />
            )}
            {RENEWABLE.includes(r.cadence) && (
              <label className="flex items-center gap-1.5 text-gray-700">
                Renew by
                <input type="date" value={r.renews_on} onChange={(e) => update(i, { renews_on: e.target.value })} className="text-sm border border-gray-200 rounded-lg py-1 px-1" />
              </label>
            )}
            <button type="button" onClick={() => remove(i)} className="ml-auto text-xs text-red-500 hover:text-red-700">Remove</button>
          </div>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...rows, { ...BLANK_CHARGE, key: Math.random() }])} className="text-sm text-sworkr-600 hover:text-sworkr-800">
        + Add a charge
      </button>
      {rows.some((r) => r.test_type) && (
        <p className="text-xs text-gray-500">A health check is logged as a health test too, so it shows in your test history.</p>
      )}
      {rows.some((r) => r.renews_on && RENEWABLE.includes(r.cadence)) && (
        <p className="text-xs text-gray-500">sworkr adds a reminder to your tasks two weeks before a renewal date.</p>
      )}
    </div>
  );
}

/** Pay a charge once: today unless changed, at its usual amount unless changed. */
export function LogChargeForm({ charge, onSaved }) {
  const [form, setForm] = useState({ date: toDateInput(new Date()), amount: charge.amount ?? '' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const [y, m, d] = form.date.split('-').map(Number);
    setSaving(true);
    try {
      await axios.post(`/api/place-charges/${charge.id}/log`, { date: new Date(y, m - 1, d, 12).toISOString(), amount: numberOrNull(form.amount) });
      onSaved();
    } catch (err) {
      setError(errorMessage(err, 'Could not log it'));
    } finally {
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Paid on">
          <input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputClass} />
        </Field>
        <Field label="Amount ($)">
          <input required type="number" min="0" step="0.01" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={inputClass} />
        </Field>
      </div>
      <p className="text-xs text-gray-500">
        {charge.test_type ? 'Added as a health test, with its cost as an expense.' : 'Added to your expenses.'}
        {charge.renews_on && charge.cadence === 'per_year' && ' Paying it moves the renewal date on a year.'}
        {charge.renews_on && charge.cadence === 'per_quarter' && ' Paying it moves the renewal date on three months.'}
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : 'Log it'}</button>
    </form>
  );
}

// ==================== PLACES YOU EARN ====================

export function SourceForm({ source, onSaved }) {
  const [form, setForm] = useState({
    name: source?.name || '',
    kind: source?.kind || 'platform',
    fee_percent: source?.fee_percent ?? '',
    fee_per_shift: source?.fee_per_shift ?? '',
    token_value: source?.token_value ?? '',
    payout_note: source?.payout_note || '',
    notes: source?.notes || '',
    archived: !!source?.archived,
    work_type: source?.work_type || '',
    persona_id: source?.persona_id ? String(source.persona_id) : '',
    gift_share_percent: source?.gift_share_percent ?? '',
    tip_share_percent: source?.tip_share_percent ?? '',
    cuts: (source?.cuts || []).map((c) => ({ label: c.label, kind: c.kind, value: String(c.value), basis: c.basis, auto: c.auto })),
    holds_cash: !!source?.holds_cash,
    cash_limit: source?.cash_limit ?? '',
  });
  const [workTypes, setWorkTypes] = useState([]);
  useEffect(() => {
    axios.get('/api/work-profile').then(({ data }) => setWorkTypes(data.options)).catch(() => {});
  }, []);
  // Charges you pay this place. Edited here and saved with the place.
  const [charges, setCharges] = useState(source ? null : []);
  const [removed, setRemoved] = useState([]);
  useEffect(() => {
    if (!source) return;
    axios.get('/api/place-charges')
      .then(({ data }) => setCharges(data.filter((c) => c.source_id === source.id).map(chargeToRow)))
      .catch(() => setCharges([]));
  }, [source]);
  const changeKind = (e) => {
    const kind = e.target.value;
    setForm({ ...form, kind });
    // A new place starts with the charges that kind of place usually makes, if none have been added yet.
    if (!source && charges && charges.every((c) => !c.label.trim()) && SUGGESTED_CHARGES[kind]) {
      setCharges(SUGGESTED_CHARGES[kind].map((c) => ({ ...BLANK_CHARGE, ...c, key: Math.random() })));
    }
  };
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const body = {
      ...form,
      name: form.name.trim(),
      fee_percent: numberOrNull(form.fee_percent),
      fee_per_shift: numberOrNull(form.fee_per_shift),
      token_value: numberOrNull(form.token_value),
      work_type: form.work_type || null,
      persona_id: form.persona_id ? Number(form.persona_id) : null,
      gift_share_percent: numberOrNull(form.gift_share_percent),
      tip_share_percent: numberOrNull(form.tip_share_percent),
      cuts: form.cuts.filter((c) => c.label.trim() && c.value !== '').map((c) => ({ ...c, label: c.label.trim(), value: Number(c.value) })),
      holds_cash: form.holds_cash,
      cash_limit: form.holds_cash ? numberOrNull(form.cash_limit) : null,
      currency: 'USD',
    };
    setSaving(true);
    try {
      const { data } = source ? await axios.put(`/api/income-sources/${source.id}`, body) : await axios.post('/api/income-sources', body);
      await saveCharges(data.id, charges || [], removed);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete "${source.name}"? Its income stays, just not linked to it. (Archive it instead to keep the link.)`)) return;
    try {
      await axios.delete(`/api/income-sources/${source.id}`);
      onSaved(null);
    } catch (err) {
      setError(errorMessage(err, 'Could not delete'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Name *">
          <input required autoFocus value={form.name} onChange={set('name')} placeholder="e.g. OnlyFans, Club Velvet" className={inputClass} />
        </Field>
        <Field label="Kind">
          <select value={form.kind} onChange={changeKind} className={inputClass}>
            {Object.entries(SOURCE_KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Type of work (for comparing income)">
        <select value={form.work_type} onChange={set('work_type')} className={inputClass}>
          <option value="">Not set</option>
          {workTypes.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
        </select>
      </Field>
      <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Persona (the name you use there)" />
      <h3 className="text-sm font-semibold text-gray-700 pt-1">Taken from your pay</h3>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Their share (%)">
          <input type="number" min="0" max="100" step="0.1" inputMode="decimal" value={form.fee_percent} onChange={set('fee_percent')} placeholder="0" className={inputClass} />
        </Field>
        <Field label="Fee per shift ($)">
          <input type="number" min="0" step="0.01" inputMode="decimal" value={form.fee_per_shift} onChange={set('fee_per_shift')} placeholder="0" className={inputClass} />
        </Field>
        <Field label="$ per token">
          <input type="number" min="0" step="0.0001" inputMode="decimal" value={form.token_value} onChange={set('token_value')} placeholder="—" className={inputClass} />
        </Field>
      </div>
      <p className="text-xs text-gray-500 -mt-1">
        These fill in the fees when you add income from here. "Their share" is the percentage the site, club or house
        keeps; the fee per shift is a house fee or tip-out. Platforms change their rates, so check yours.
      </p>
      {(form.kind === 'brothel' || form.gift_share_percent !== '') && (
        <Field label="Their share of gifts (%)">
          <input type="number" min="0" max="100" step="1" inputMode="decimal" value={form.gift_share_percent} onChange={set('gift_share_percent')} placeholder="e.g. 50" className={`${inputClass} max-w-[8rem]`} />
          <span className="block text-xs text-gray-500 mt-1">Many brothels charge half a gift's value. Logging a gift from here fills that in as the house share.</span>
        </Field>
      )}
      <Field label="Their share of your tips (%)">
        <input type="number" min="0" max="100" step="1" inputMode="decimal" value={form.tip_share_percent} onChange={set('tip_share_percent')} placeholder="Leave empty if tips are all yours" className={`${inputClass} max-w-[16rem]`} />
        <span className="block text-xs text-gray-500 mt-1">A house cut or tip-out. Logging a tip from here takes it off for you.</span>
      </Field>
      <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-2">
        <legend className="px-1 text-xs font-medium text-gray-500">House rules</legend>
        {isDemo() ? (
          <p className="text-xs text-gray-500">Some features are only available in the full version.</p>
        ) : (<>
        <p className="text-xs text-gray-500">
          Anything else this place takes, however it's named there: Kelly called (one for each rate), a runner, a card fee.
          Each is a percentage or an amount, taken off the top (before their share) or out of your share.
        </p>
        {form.cuts.map((c, i) => {
          const change = (patch) => setForm({ ...form, cuts: form.cuts.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
          return (
            <div key={i} className="grid grid-cols-12 gap-2 items-center">
              <input value={c.label} onChange={(e) => change({ label: e.target.value })} placeholder="e.g. Kelly called (cab)" aria-label="What it's called" className={`${inputClass} col-span-12 sm:col-span-4`} />
              <input type="number" min="0" step="0.01" inputMode="decimal" value={c.value} onChange={(e) => change({ value: e.target.value })} aria-label="How much" className={`${inputClass} col-span-4 sm:col-span-2`} />
              <select value={c.kind} onChange={(e) => change({ kind: e.target.value })} aria-label="Percent or dollars" className={`${inputClass} col-span-4 sm:col-span-1 !px-1`}>
                <option value="percent">%</option><option value="amount">$</option>
              </select>
              <select value={c.basis} onChange={(e) => change({ basis: e.target.value })} aria-label="Taken from" className={`${inputClass} col-span-4 sm:col-span-3 !px-1`}>
                <option value="top">off the top</option><option value="mine">out of my share</option>
              </select>
              <label className="col-span-10 sm:col-span-1 flex items-center gap-1 text-xs text-gray-600" title="Taken every time, without ticking it">
                <input type="checkbox" checked={c.auto} onChange={(e) => change({ auto: e.target.checked })} /> always
              </label>
              <button type="button" onClick={() => setForm({ ...form, cuts: form.cuts.filter((_, j) => j !== i) })} className="col-span-2 sm:col-span-1 text-gray-300 hover:text-red-500" aria-label="Remove this cut">✕</button>
            </div>
          );
        })}
        <button type="button" onClick={() => setForm({ ...form, cuts: [...form.cuts, { label: '', kind: 'percent', value: '', basis: 'top', auto: false }] })} className="text-xs text-sworkr-600 hover:text-sworkr-800">+ Add a cut</button>
        <label className="flex items-start gap-2 text-sm text-gray-700 pt-1">
          <input type="checkbox" checked={form.holds_cash} onChange={set('holds_cash')} className="mt-1" />
          <span>The office holds what I earn until payout <span className="text-xs text-gray-500">(income added here starts as "not paid out yet", and sworkr keeps the running total they owe you)</span></span>
        </label>
        {form.holds_cash && (
          <Field label="Cash I'm allowed to keep on me ($)">
            <input type="number" min="0" step="1" inputMode="decimal" value={form.cash_limit} onChange={set('cash_limit')} placeholder="e.g. 20" className={`${inputClass} max-w-[8rem]`} />
          </Field>
        )}
        </>)}
      </fieldset>
      <h3 className="text-sm font-semibold text-gray-700 pt-1">Charges you pay them</h3>
      <p className="text-xs text-gray-500 -mt-2">
        Room & board, a house doctor, room hire: anything you pay this place as well. (Licenses go to the government, not the house: add them under Account → Licenses & documents.) Log each one from the
        place's card when you pay it; a stay at this place logs its daily and weekly charges for you.
      </p>
      {charges === null ? <p className="text-sm text-gray-400">Loading…</p> : (
        <ChargesEditor
          rows={charges}
          onChange={setCharges}
          onRemove={(row) => { if (row.id) setRemoved((r) => [...r, row.id]); }}
        />
      )}
      {charges && charges.length === 0 && SUGGESTED_CHARGES[form.kind] && (
        <button type="button" onClick={() => setCharges(SUGGESTED_CHARGES[form.kind].map((c) => ({ ...BLANK_CHARGE, ...c, key: Math.random() })))}
          className="text-sm text-sworkr-600 hover:text-sworkr-800">
          + Add the usual {SOURCE_KINDS[form.kind].toLowerCase()} charges ({SUGGESTED_CHARGES[form.kind].map((c) => c.label.toLowerCase()).join(', ')})
        </button>
      )}
      <Field label="Payouts">
        <input value={form.payout_note} onChange={set('payout_note')} placeholder="e.g. Weekly on Fridays, $20 minimum" className={inputClass} />
      </Field>
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>
      {source && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.archived} onChange={set('archived')} />
          Archived (kept for past income, hidden when adding new income)
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between pt-1">
        {source ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : source ? 'Save changes' : 'Add'}</button>
      </div>
    </form>
  );
}

/** "20% · $60 a shift · $0.05 a token" */
export function sourceFees(s) {
  return [
    s.fee_percent != null && `${s.fee_percent}% to them`,
    s.fee_per_shift != null && `${money(s.fee_per_shift, s.currency)} a shift`,
    s.token_value != null && `$${s.token_value} a token`,
  ].filter(Boolean).join(' · ');
}

// ==================== INCOME ====================

/**
 * Add or edit income that isn't a calendar booking: a payout, tips, a sale, a shift.
 * The fees fill in from the workplace or platform (its share, plus its fee per shift for a shift) until you change them.
 */
export function IncomeForm({ income, sources, defaultDate, onSaved }) {
  const firstSource = sources.find((s) => !s.archived);
  const [form, setForm] = useState({
    source_id: income ? (income.source_id ? String(income.source_id) : '') : firstSource ? String(firstSource.id) : '',
    kind: income?.kind || (['brothel', 'club'].includes(firstSource?.kind) ? 'shift' : 'payout'),
    date: toDateInput(income ? new Date(income.date) : defaultDate || new Date()),
    tokens: income?.tokens ?? '',
    gross: income ? String(income.gross) : '',
    fees: income ? String(income.fees) : '',
    status: income?.status || (firstSource?.holds_cash ? 'pending' : 'received'),
    payout_date: income?.payout_date || '',
    description: income?.description || '',
    notes: income?.notes || '',
    client_id: income?.client_id ? String(income.client_id) : '',
    payment_method: income?.payment_method || '',
    cuts: income ? (income.cuts || []).map((c) => c.label) : null,   // the cuts ticked (null: the place's "always" ones)
  });
  const [feesTouched, setFeesTouched] = useState(!!income);
  // Gifts and allowances can say who they're from.
  const [contacts, setContacts] = useState([]);
  const fromSomeone = ['gift', 'allowance', 'booking'].includes(form.kind);
  useEffect(() => {
    if (fromSomeone && contacts.length === 0) fetchAll('/api/clients', { sort: 'name', role: 'client' }, 200).then(setContacts).catch(() => {});
  }, [fromSomeone, contacts.length]);
  const [split, setSplit, saveSplit] = useSplit('income', income?.id);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const source = sources.find((s) => String(s.id) === form.source_id);
  // What the place takes from this income: its ticked cuts off the top, then its usual share of what's left, then
  // any cuts that come out of your share.
  const houseTake = (f) => {
    const s = sources.find((x) => String(x.id) === f.source_id);
    const gross = Number(f.gross) || 0;
    if (!s) return { fees: 0, taken: [] };
    if (f.kind === 'gift') return { fees: gross * (s.gift_share_percent || 0) / 100, taken: [] };
    if (f.kind === 'tips' && s.tip_share_percent != null) return { fees: gross * s.tip_share_percent / 100, taken: [] };
    const ticked = f.cuts ?? (s.cuts || []).filter((c) => c.auto).map((c) => c.label);
    const active = f.kind === 'tips' ? [] : (s.cuts || []).filter((c) => ticked.includes(c.label));
    const amount = (c, base) => Math.round((c.kind === 'percent' ? base * c.value / 100 : Math.min(c.value, base)) * 100) / 100;
    const top = active.filter((c) => c.basis === 'top').map((c) => ({ label: c.label, amount: amount(c, gross) }));
    const rest = Math.max(gross - top.reduce((sum, c) => sum + c.amount, 0), 0);
    const house = rest * (s.fee_percent || 0) / 100 + (f.kind === 'shift' ? s.fee_per_shift || 0 : 0);
    const mine = active.filter((c) => c.basis === 'mine').map((c) => ({ label: c.label, amount: amount(c, Math.max(rest - house, 0)) }));
    const taken = [...top, ...mine];
    return { fees: taken.reduce((sum, c) => sum + c.amount, 0) + house, taken };
  };
  const suggestFees = (f) => {
    const { fees } = houseTake(f);
    return fees ? fees.toFixed(2) : '';
  };
  const update = (changes) => setForm((f) => {
    const next = { ...f, ...changes };
    if ('source_id' in changes && !income) {      // another place: its own rules
      const place = sources.find((x) => String(x.id) === next.source_id);
      next.cuts = null;
      next.status = place?.holds_cash ? 'pending' : 'received';
    }
    if ('tokens' in changes) {
      const s = sources.find((x) => String(x.id) === next.source_id);
      if (s?.token_value && next.tokens !== '') next.gross = (Number(next.tokens) * s.token_value).toFixed(2);
    }
    if (!feesTouched) next.fees = suggestFees(next);
    return next;
  });
  const set = (k) => (e) => {
    if (k === 'fees') setFeesTouched(true);
    update({ [k]: e.target.value });
  };

  const gross = Number(form.gross) || 0;
  const fees = Number(form.fees) || 0;

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!(gross >= 0) || !(fees >= 0)) return setError('Amounts must be 0 or more');
    const [y, m, d] = form.date.split('-').map(Number);
    const body = {
      source_id: form.source_id ? Number(form.source_id) : null,
      kind: form.kind,
      date: new Date(y, m - 1, d, 12).toISOString(),
      tokens: numberOrNull(form.tokens),
      gross,
      fees,
      status: form.status,
      payout_date: form.payout_date || null,
      description: form.description.trim() || null,
      notes: form.notes.trim() || null,
      currency: 'USD',
      client_id: fromSomeone && form.client_id ? Number(form.client_id) : null,
      payment_method: form.payment_method.trim() || null,
      cuts: houseTake(form).taken,
    };
    setSaving(true);
    try {
      const { data } = income ? await axios.put(`/api/income/${income.id}`, body) : await axios.post('/api/income', body);
      await saveSplit(data.id);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm('Delete this income?')) return;
    try {
      await axios.delete(`/api/income/${income.id}`);
      onSaved(null);
    } catch (err) {
      setError(errorMessage(err, 'Could not delete'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Where from">
          <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
            <option value="">Not from a saved place</option>
            {sources.filter((s) => !s.archived || String(s.id) === form.source_id).map((s) => (
              <option key={s.id} value={s.id}>{s.name}{s.archived ? ' (archived)' : ''}</option>
            ))}
          </select>
        </Field>
        <Field label="What for">
          <select value={form.kind} onChange={set('kind')} className={inputClass}>
            {Object.entries(INCOME_KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
      </div>
      {fromSomeone && (
        <Field label="From (optional)">
          <select value={form.client_id} onChange={set('client_id')} className={inputClass}>
            <option value="">Not saying</option>
            {contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
        </Field>
      )}
      <Field label="Description">
        <input value={form.description} onChange={set('description')} placeholder={form.kind === 'gift' ? 'e.g. Designer bag' : 'e.g. Friday shift, March subscriptions'} className={inputClass} />
      </Field>
      <div className={`grid gap-3 ${source?.token_value ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-3'}`}>
        <Field label="Date earned *">
          <input required type="date" value={form.date} onChange={set('date')} className={inputClass} />
        </Field>
        {source?.token_value != null && (
          <Field label="Tokens">
            <input type="number" min="0" step="1" inputMode="numeric" value={form.tokens} onChange={set('tokens')} className={inputClass} />
          </Field>
        )}
        <Field label={form.kind === 'gift' ? "What it's worth ($) *" : 'Amount ($) *'}>
          <input required type="number" min="0" step="0.01" inputMode="decimal" value={form.gross} onChange={set('gross')} className={inputClass} />
        </Field>
        <Field label={form.kind === 'gift' && source?.gift_share_percent ? 'House share ($)' : 'Fees ($)'}>
          <input type="number" min="0" step="0.01" inputMode="decimal" value={form.fees} onChange={set('fees')} placeholder="0" className={inputClass} />
        </Field>
      </div>
      <p className="text-sm text-gray-600 -mt-1">
        You keep <strong className={gross - fees < 0 ? 'text-red-600' : 'text-gray-800'}>{money(gross - fees)}</strong>
        {source && !feesTouched && fees > 0 && <span className="text-xs text-gray-400"> (fees filled in from {source.name})</span>}
      </p>
      {form.kind === 'gift' && (
        <p className="text-xs text-gray-500 -mt-2">
          A gift counts as income at what it's worth.
          {source?.gift_share_percent
            ? ` ${source.name} charges ${source.gift_share_percent}% of a gift's value, so that's the house share: what you pay them, which comes off your income for tax.`
            : ' If the place charges you a share of gifts (many brothels charge half), set it on the place and it fills in here.'}
        </p>
      )}
      {source?.cuts?.length > 0 && form.kind !== 'gift' && form.kind !== 'tips' && (
        <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-2">
          <legend className="px-1 text-xs font-medium text-gray-500">{source.name} also took</legend>
          {source.cuts.map((c) => {
            const ticked = (form.cuts ?? source.cuts.filter((x) => x.auto).map((x) => x.label)).includes(c.label);
            const taken = houseTake(form).taken.find((t) => t.label === c.label);
            return (
              <label key={c.label} className="flex items-center gap-2 text-sm text-gray-700 py-0.5">
                <input type="checkbox" checked={ticked} onChange={(e) => {
                  const now = form.cuts ?? source.cuts.filter((x) => x.auto).map((x) => x.label);
                  update({ cuts: e.target.checked ? [...now, c.label] : now.filter((l) => l !== c.label) });
                }} />
                <span>{c.label} <span className="text-xs text-gray-500">({c.kind === 'percent' ? `${c.value}%` : money(c.value)} {c.basis === 'top' ? 'off the top' : 'out of your share'}{taken ? `: ${money(taken.amount)}` : ''})</span></span>
              </label>
            );
          })}
        </fieldset>
      )}
      {source?.holds_cash && (
        <p className="text-xs rounded-lg bg-sky-50 border border-sky-200 text-sky-900 px-3 py-2">
          {source.name} holds what you earn until payout{source.cash_limit != null ? `, and you can keep ${money(source.cash_limit)} on you` : ''}. Leave this as "Not yet" and it's added to what they owe you.
        </p>
      )}
      <Field label="How it was paid">
        <input list="income-paid-how" value={form.payment_method} onChange={set('payment_method')} placeholder="Cash, bank transfer, platform payout…" className={inputClass} />
        <datalist id="income-paid-how">
          {['Cash', 'Bank transfer', 'Check', 'Platform payout', 'Card', 'Cash App', 'Venmo', 'PayPal', 'Zelle', 'Crypto', 'Gift card'].map((m) => <option key={m} value={m} />)}
        </datalist>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Paid out?">
          <select value={form.status} onChange={set('status')} className={inputClass}>
            <option value="received">Yes, I have it</option>
            <option value="pending">Not yet (pending)</option>
          </select>
        </Field>
        <Field label={form.status === 'pending' ? 'Expected on' : 'Paid out on'}>
          <input type="date" value={form.payout_date} onChange={set('payout_date')} className={inputClass} />
        </Field>
      </div>
      <SplitEditor split={split} onChange={setSplit} base={form.status === 'received' ? gross - fees : 0} kind="content" handledLabel="Who was paid" />
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between pt-1">
        {income ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : income ? 'Save changes' : 'Add income'}</button>
      </div>
    </form>
  );
}

