import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from '../components/Modal';
import { dayLabel, fromDateInput, GOAL_COLORS, money, toDateInput } from '../colors';

const RULES = {
  none: 'No rule: I add money myself',
  percent: 'A percentage of everything I receive',
  weekly: 'An amount every week',
  per_booking: 'An amount for every completed booking',
};
const ruleSummary = (g) => ({
  percent: `${g.rule_amount}% of what comes in`,
  weekly: `${money(g.rule_amount, g.currency)} a week`,
  per_booking: `${money(g.rule_amount, g.currency)} per booking`,
}[g.rule_type]);
const niceDate = (value) => dayLabel(fromDateInput(value), { month: 'short', day: 'numeric', year: 'numeric' });

/**
 * Savings goals. Each goal is an envelope: what you've put in, minus what you've taken out. sworkr doesn't
 * move real money; a goal's rule works out how much should go in, and suggests the difference.
 */
export default function Goals() {
  const [goals, setGoals] = useState(null);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null); // { goal } | { entry: { goal, direction } }
  const [showArchived, setShowArchived] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/goals');
      setGoals(data);
      setError('');
    } catch (err) {
      if (err?.response?.status !== 401) setError(errorMessage(err, "Couldn't load your goals."));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const addEntry = async (goal, amount, note) => {
    try {
      await axios.post(`/api/goals/${goal.id}/entries`, { amount, note });
    } catch (err) {
      window.alert(errorMessage(err, 'Could not save'));
    }
    load();
  };

  if (!goals) {
    return <div className="bg-white rounded-2xl shadow-lg p-6 text-sm text-gray-400">{error || 'Loading…'}</div>;
  }
  const active = goals.filter((g) => !g.archived);
  const archived = goals.filter((g) => g.archived);
  const saved = active.reduce((s, g) => s + g.balance, 0);
  const toSetAside = active.reduce((s, g) => s + (g.suggested || 0), 0);
  const hasTaxGoal = goals.some((g) => g.kind === 'tax');

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-gray-800">Goals &amp; envelopes</h2>
            <p className="text-sm text-gray-500">
              {money(saved)} set aside across {active.length} goal{active.length === 1 ? '' : 's'}
              {toSetAside > 0 && <> · <strong className="text-amber-700">{money(toSetAside)}</strong> to set aside now</>}
            </p>
          </div>
          <button onClick={() => setModal({ goal: null })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New goal</button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Goals are envelopes for keeping track: when you move money into savings, record it here. sworkr never moves real money.
        </p>
      </div>

      {!hasTaxGoal && <TaxPrompt onCreated={load} />}

      {active.length === 0 && hasTaxGoal && (
        <p className="text-center text-white/90 text-sm py-6">No goals yet. Add one for an emergency fund, a move, new gear, or retirement.</p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {active.map((g) => (
          <GoalCard key={g.id} goal={g} onEdit={() => setModal({ goal: g })} onEntry={(direction) => setModal({ entry: { goal: g, direction } })}
            onSetAside={() => addEntry(g, g.suggested, 'Set aside (suggested)')} onChanged={load} />
        ))}
      </div>

      {archived.length > 0 && (
        <div>
          <button onClick={() => setShowArchived(!showArchived)} className="text-sm text-white/90 hover:text-white">
            {showArchived ? 'Hide' : 'Show'} {archived.length} archived goal{archived.length === 1 ? '' : 's'}
          </button>
          {showArchived && (
            <div className="grid gap-4 md:grid-cols-2 mt-3 opacity-80">
              {archived.map((g) => (
                <GoalCard key={g.id} goal={g} onEdit={() => setModal({ goal: g })} onEntry={(direction) => setModal({ entry: { goal: g, direction } })}
                  onSetAside={() => addEntry(g, g.suggested, 'Set aside (suggested)')} onChanged={load} />
              ))}
            </div>
          )}
        </div>
      )}

      {modal && 'goal' in modal && (
        <Modal title={modal.goal ? `Edit ${modal.goal.name}` : 'New goal'} onClose={() => setModal(null)}>
          <GoalForm goal={modal.goal} onSaved={() => { setModal(null); load(); }} />
        </Modal>
      )}
      {modal?.entry && (
        <Modal title={`${modal.entry.direction === 'in' ? 'Add money to' : 'Take money out of'} ${modal.entry.goal.name}`} onClose={() => setModal(null)}>
          <EntryForm goal={modal.entry.goal} direction={modal.entry.direction} onSaved={() => { setModal(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}

function GoalCard({ goal: g, onEdit, onEntry, onSetAside, onChanged }) {
  const [history, setHistory] = useState(false);
  const color = g.color || '#059669';
  const removeEntry = async (e) => {
    if (!window.confirm(`Remove this ${e.amount > 0 ? 'deposit' : 'withdrawal'} of ${money(Math.abs(e.amount), g.currency)}?`)) return;
    await axios.delete(`/api/goals/${g.id}/entries/${e.id}`).catch(() => {});
    onChanged();
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg overflow-hidden">
      <div className="h-1.5" style={{ background: color }} />
      <div className="p-4 sm:p-5 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-semibold text-gray-800 break-words">
              {g.name}
              {g.envelope && <span className="ml-2 align-middle px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-semibold">Envelope</span>}
              {g.kind === 'tax' && <span className="ml-2 align-middle px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-[10px] font-semibold">Taxes</span>}
              {g.reached && <span className="ml-2 align-middle px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-[10px] font-semibold">Reached 🎉</span>}
            </h2>
            {g.notes && <p className="text-xs text-gray-500 mt-0.5 whitespace-pre-wrap">{g.notes}</p>}
          </div>
          <button onClick={onEdit} className="text-xs text-sworkr-600 hover:text-sworkr-800 shrink-0">Edit</button>
        </div>

        <div>
          <p className="text-2xl font-bold text-gray-800">
            {money(g.balance, g.currency)}
            {g.target_amount && <span className="text-sm font-normal text-gray-500"> of {money(g.target_amount, g.currency)}</span>}
          </p>
          {g.held != null && <p className="text-xs text-gray-500">{money(g.held, g.currency)} of it is still with the workplace</p>}
          {g.target_amount && (
            <div className="mt-2 h-2.5 bg-gray-100 rounded-full overflow-hidden" role="progressbar" aria-valuenow={Math.round(g.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={`${g.name}: ${Math.round(g.progress * 100)}%`}>
              <div className="h-full rounded-full" style={{ width: `${Math.max(g.progress * 100, g.balance > 0 ? 2 : 0)}%`, background: color }} />
            </div>
          )}
          <p className="text-xs text-gray-500 mt-1.5">
            {[
              g.target_amount && !g.reached && `${money(g.remaining, g.currency)} to go`,
              g.target_date && `by ${niceDate(g.target_date)}`,
              g.per_week_needed != null && `${money(g.per_week_needed, g.currency)} a week needed`,
            ].filter(Boolean).join(' · ')}
            {g.on_track === true && <span className="text-emerald-700"> · on track</span>}
            {g.on_track === false && <span className="text-amber-700"> · behind</span>}
          </p>
        </div>

        {g.rule_type !== 'none' && (
          <div className="rounded-xl bg-gray-50 px-3 py-2 text-sm">
            <p className="text-gray-600">Rule: {ruleSummary(g)} since {niceDate(g.starts_on)}</p>
            {g.rule_type === 'percent' && <p className="text-xs text-gray-400">{money(g.rule_basis, g.currency)} received since then</p>}
            {g.rule_type === 'per_booking' && <p className="text-xs text-gray-400">{g.rule_basis} completed booking{g.rule_basis === 1 ? '' : 's'} since then</p>}
            {g.suggested > 0 ? (
              <div className="flex flex-wrap items-center gap-2 mt-2">
                <span className="text-amber-800">Set aside <strong>{money(g.suggested, g.currency)}</strong> to catch up</span>
                <button onClick={onSetAside} className="ml-auto text-xs px-3 py-1.5 rounded-lg bg-amber-500 text-white hover:bg-amber-600 font-medium">
                  I've set it aside
                </button>
              </div>
            ) : <p className="text-xs text-emerald-700 mt-1">✓ Up to date</p>}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button onClick={() => onEntry('in')} className={quietButtonClass}>+ Add money</button>
          {g.balance > 0 && <button onClick={() => onEntry('out')} className={quietButtonClass}>− Take out</button>}
          {g.entries.length > 0 && (
            <button onClick={() => setHistory(!history)} className="ml-auto text-xs text-gray-500 hover:text-gray-800">
              {history ? 'Hide history' : `History (${g.entries.length})`}
            </button>
          )}
        </div>
        {history && (
          <ul className="divide-y divide-gray-100 text-sm">
            {g.entries.map((e) => (
              <li key={e.id} className="flex items-center gap-3 py-1.5">
                <span className="text-xs text-gray-500 w-20 shrink-0">{niceDate(e.date)}</span>
                <span className="flex-1 min-w-0 truncate text-gray-600">{e.note || (e.amount > 0 ? 'Added' : 'Taken out')}</span>
                <span className={`font-medium ${e.amount < 0 ? 'text-red-600' : 'text-gray-800'}`}>{e.amount > 0 ? '+' : '−'}{money(Math.abs(e.amount), g.currency)}</span>
                <button onClick={() => removeEntry(e)} className="text-gray-300 hover:text-red-500" aria-label="Remove this entry">✕</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Offered until there's a tax goal: set aside a share of everything that comes in. */
function TaxPrompt({ onCreated }) {
  const [percent, setPercent] = useState('');
  const [error, setError] = useState('');
  const create = async (e) => {
    e.preventDefault();
    const value = Number(percent);
    if (!(value > 0 && value <= 100)) return setError('Enter a percentage between 1 and 100');
    try {
      await axios.post('/api/goals', { name: 'Taxes', kind: 'tax', rule_type: 'percent', rule_amount: value, color: '#4f46e5', priority: 10 });
      onCreated();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  return (
    <form onSubmit={create} className="bg-white rounded-2xl shadow-lg p-4 sm:p-5 border-l-4 border-indigo-500">
      <h2 className="font-semibold text-gray-800">Set money aside for taxes?</h2>
      <p className="text-sm text-gray-500 mt-1">
        Choose a share of everything you receive to put aside. sworkr will work out how much that is and remind you.
        What share is right depends on where you live and how you file. A tax professional can tell you.
      </p>
      <div className="flex flex-wrap items-center gap-2 mt-3">
        <input type="number" min="1" max="100" step="0.5" inputMode="decimal" value={percent} onChange={(e) => setPercent(e.target.value)}
          placeholder="e.g. 25" className={`${inputClass} !w-28`} aria-label="Percentage to set aside" />
        <span className="text-sm text-gray-600">% of what I receive</span>
        <button type="submit" className={`${buttonClass} ml-auto`}>Start a tax goal</button>
      </div>
      {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
    </form>
  );
}

function GoalForm({ goal, onSaved }) {
  const [form, setForm] = useState({
    name: goal?.name || '',
    kind: goal?.kind || 'savings',
    target_amount: goal?.target_amount ?? '',
    target_date: goal?.target_date || '',
    rule_type: goal?.rule_type || 'none',
    rule_amount: goal?.rule_amount ?? '',
    starts_on: goal?.starts_on || toDateInput(new Date()),
    color: goal?.color || GOAL_COLORS[0],
    priority: goal?.priority ?? 0,
    notes: goal?.notes || '',
    archived: !!goal?.archived,
    envelope: !!goal?.envelope,
    source_id: goal?.source_id ? String(goal.source_id) : '',
  });
  const [sources, setSources] = useState([]);
  useEffect(() => {
    axios.get('/api/income-sources').then(({ data }) => setSources(data.filter((x) => !x.archived))).catch(() => {});
  }, []);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const body = {
      ...form,
      name: form.name.trim(),
      target_amount: form.target_amount === '' ? null : Number(form.target_amount),
      target_date: form.target_date || null,
      rule_amount: form.rule_type === 'none' || form.rule_amount === '' ? null : Number(form.rule_amount),
      priority: Number(form.priority) || 0,
      notes: form.notes.trim() || null,
      currency: 'USD',
      source_id: form.envelope && form.source_id ? Number(form.source_id) : null,
    };
    setSaving(true);
    try {
      if (goal) await axios.put(`/api/goals/${goal.id}`, body);
      else await axios.post('/api/goals', body);
      onSaved();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete the goal "${goal.name}" and its history? (Archive it instead to keep the history.)`)) return;
    await axios.delete(`/api/goals/${goal.id}`).catch(() => {});
    onSaved();
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3">
        <Field label="Name *">
          <input required autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Emergency fund, New camera, Retirement goal" className={inputClass} />
        </Field>
        <Field label="Kind">
          <select value={form.envelope ? 'envelope' : form.kind}
            onChange={(e) => setForm({ ...form, envelope: e.target.value === 'envelope', kind: e.target.value === 'tax' ? 'tax' : 'savings' })}
            className={inputClass}>
            <option value="savings">Savings goal</option>
            <option value="envelope">Envelope</option>
            <option value="tax">Taxes</option>
          </select>
        </Field>
      </div>
      {form.envelope && (
        <Field label="Also holds what a workplace is keeping for you (optional)">
          <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
            <option value="">No, just what I put in</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Target ($, optional)">
          <input type="number" min="0" step="0.01" inputMode="decimal" value={form.target_amount} onChange={set('target_amount')} className={inputClass} />
        </Field>
        <Field label="By (optional)">
          <input type="date" value={form.target_date} onChange={set('target_date')} className={inputClass} />
        </Field>
      </div>
      <Field label="How money goes in">
        <select value={form.rule_type} onChange={set('rule_type')} className={inputClass}>
          {Object.entries(RULES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </Field>
      {form.rule_type !== 'none' && (
        <div className="grid grid-cols-2 gap-3">
          <Field label={form.rule_type === 'percent' ? 'Percentage (%)' : 'Amount ($)'}>
            <input required type="number" min="0" max={form.rule_type === 'percent' ? 100 : undefined} step="0.01" inputMode="decimal"
              value={form.rule_amount} onChange={set('rule_amount')} className={inputClass} />
          </Field>
          <Field label="Counting from">
            <input type="date" value={form.starts_on} onChange={set('starts_on')} className={inputClass} />
          </Field>
        </div>
      )}
      <div className="grid grid-cols-[1fr_auto] gap-3 items-end">
        <Field label="Colour">
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Colour">
            {GOAL_COLORS.map((c) => (
              <button key={c} type="button" role="radio" aria-checked={form.color === c} aria-label={c} onClick={() => setForm({ ...form, color: c })}
                className={`w-7 h-7 rounded-full ${form.color === c ? 'ring-2 ring-offset-2 ring-gray-500' : ''}`} style={{ background: c }} />
            ))}
          </div>
        </Field>
        <Field label="Order">
          <input type="number" value={form.priority} onChange={set('priority')} className={`${inputClass} !w-20`} title="Higher numbers show first" />
        </Field>
      </div>
      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>
      {goal && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.archived} onChange={set('archived')} />
          Archived (done or on hold; kept with its history)
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between pt-1">
        {goal ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete goal</button> : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : goal ? 'Save changes' : 'Add goal'}</button>
      </div>
    </form>
  );
}

function EntryForm({ goal, direction, onSaved }) {
  const [amount, setAmount] = useState(direction === 'in' && goal.suggested > 0 ? String(goal.suggested) : '');
  const [when, setWhen] = useState(toDateInput(new Date()));
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    const value = Number(amount);
    if (!(value > 0)) return setError('Enter an amount');
    try {
      await axios.post(`/api/goals/${goal.id}/entries`, { amount: direction === 'in' ? value : -value, date: when, note: note.trim() || null });
      onSaved();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount ($) *">
          <input required autoFocus type="number" min="0.01" step="0.01" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Date">
          <input type="date" value={when} onChange={(e) => setWhen(e.target.value)} className={inputClass} />
        </Field>
      </div>
      <Field label="Note">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={direction === 'in' ? 'e.g. From Friday' : 'e.g. Paid estimated tax'} className={inputClass} />
      </Field>
      {direction === 'out' && <p className="text-xs text-gray-500">There's {money(goal.balance, goal.currency)} in this goal.</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end">
        <button type="submit" className={buttonClass}>{direction === 'in' ? 'Add' : 'Take out'}</button>
      </div>
    </form>
  );
}
