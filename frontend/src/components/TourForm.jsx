import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass } from './Modal';
import { useCycleDays } from './Cycle';
import { CADENCES, daysBetween, money, periodTimes, SOURCE_KINDS, TIME_OFF_LABELS, toDateInput } from '../colors';

/**
 * Create or edit a tour, or time off (a day off or a vacation).
 * New: pass `defaultKind` ('tour' | 'time_off') and optionally `defaultDate`. Edit: pass `period`.
 */
export default function TourForm({ period, defaultKind = 'tour', defaultDate, onSaved, onDeleted }) {
  const fromDate = (v) => { const [y, m, d] = v.split('-').map(Number); return new Date(y, m - 1, d); };
  const firstDay = toDateInput(defaultDate || new Date());
  const [form, setForm] = useState({
    kind: period?.kind || defaultKind,
    time_off_type: period?.time_off_type || 'day_off',
    name: period?.name || '',
    location: period?.location || '',
    start_date: period?.start_date || firstDay,
    end_date: period?.end_date || firstDay,
    room_rent_per_day: period?.room_rent_per_day != null ? String(period.room_rent_per_day) : '',
    notes: period?.notes || '',
    source_id: period?.source_id ? String(period.source_id) : '',
  });
  // A tour can be a stay at one of your places: its daily and weekly charges are then logged for you.
  const [places, setPlaces] = useState([]);
  const [charges, setCharges] = useState([]);
  useEffect(() => {
    if (form.kind !== 'tour') return;
    axios.get('/api/income-sources').then(({ data }) => setPlaces(data)).catch(() => {});
    axios.get('/api/place-charges').then(({ data }) => setCharges(data)).catch(() => {});
  }, [form.kind]);
  const stayCharges = charges.filter((c) => String(c.source_id) === form.source_id
    && ['per_day', 'per_week', 'per_month', 'per_stay'].includes(c.cadence));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => {
    const value = e.target.value;
    setForm((f) => {
      const next = { ...f, [k]: value };
      // Moving the first day past the last day moves the last day with it.
      if (k === 'start_date' && value && next.end_date < value) next.end_date = value;
      return next;
    });
  };

  const isTour = form.kind === 'tour';
  const days = form.start_date && form.end_date && form.end_date >= form.start_date
    ? daysBetween(form.start_date, form.end_date) : 0;
  const rate = form.room_rent_per_day === '' ? null : Number(form.room_rent_per_day);
  const dayAfter = days ? toDateInput(new Date(fromDate(form.end_date).getTime() + 86400000 * 1.5)) : '';
  const cycle = useCycleDays(days ? form.start_date : '', dayAfter);
  const periodDays = Object.entries(cycle).filter(([, k]) => k !== 'fertile').map(([d]) => d);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.start_date || !form.end_date) return setError('Choose the first and last day');
    if (form.end_date < form.start_date) return setError("The last day can't be before the first day");
    if (isTour && !form.name.trim()) return setError('Give the tour a name, like the city');
    if (rate !== null && !(rate >= 0)) return setError('Room & board must be 0 or more');
    const body = {
      kind: form.kind,
      time_off_type: isTour ? null : form.time_off_type,
      name: form.name.trim() || null,
      location: isTour ? form.location.trim() || null : null,
      ...periodTimes(form.start_date, form.end_date),
      room_rent_per_day: isTour ? rate : null,
      notes: form.notes.trim() || null,
      source_id: isTour && form.source_id ? Number(form.source_id) : null,
    };
    setSaving(true);
    try {
      const { data } = period
        ? await axios.put(`/api/tours/${period.id}`, body)
        : await axios.post('/api/tours', body);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    const what = isTour ? `the tour "${period.name}" and its room & board` : 'this time off';
    if (!window.confirm(`Delete ${what}? Appointments and other expenses stay.`)) return;
    try {
      await axios.delete(`/api/tours/${period.id}`);
      onDeleted?.();
    } catch (err) {
      setError(errorMessage(err, 'Could not delete'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      {!period && (
        <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden" role="group" aria-label="What is it?">
          {[['tour', 'Tour'], ['time_off', 'Time off']].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setForm({ ...form, kind: value })}
              aria-pressed={form.kind === value}
              className={`px-4 py-1.5 text-sm ${form.kind === value ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {isTour ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Tour name *">
            <input required autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Chicago" className={inputClass} />
          </Field>
          <Field label="Where (optional)">
            <input value={form.location} onChange={set('location')} placeholder="Hotel or area" className={inputClass} />
          </Field>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Kind">
            <select value={form.time_off_type} onChange={set('time_off_type')} className={inputClass}>
              {Object.entries(TIME_OFF_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field label="Name (optional)">
            <input value={form.name} onChange={set('name')} placeholder="e.g. Mexico trip" className={inputClass} />
          </Field>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field label="First day *">
          <input required type="date" value={form.start_date} onChange={set('start_date')} className={inputClass} />
        </Field>
        <Field label="Last day *">
          <input required type="date" value={form.end_date} min={form.start_date} onChange={set('end_date')} className={inputClass} />
        </Field>
      </div>

      {isTour && (
        <div>
          <Field label="At one of your places (optional)">
            <select value={form.source_id} onChange={set('source_id')} className={inputClass}>
              <option value="">No, somewhere else</option>
              {places.filter((p) => !p.archived || String(p.id) === form.source_id).map((p) => (
                <option key={p.id} value={p.id}>{p.name}{SOURCE_KINDS[p.kind] ? ` (${SOURCE_KINDS[p.kind].toLowerCase()})` : ''}</option>
              ))}
            </select>
          </Field>
          {form.source_id && (
            <p className="text-xs text-gray-500 mt-1">
              {stayCharges.length === 0
                ? "This place has no daily, weekly or per-stay charges. Add them to the place on the Money page and they'll be logged for this stay."
                : `Logged for you: ${stayCharges.map((c) => (c.amount == null ? `${c.label} (no amount yet)` : `${c.label} ${money(c.amount)} ${CADENCES[c.cadence]}`)).join(', ')}.`}
              {stayCharges.some((c) => c.test_type) && ' The doctor is added as a health test.'}
            </p>
          )}
        </div>
      )}
      {isTour && (
        <div>
          <Field label={form.source_id ? 'Other room & board per day ($)' : 'Room & board per day ($)'}>
            <input type="number" min="0" step="0.01" inputMode="decimal" value={form.room_rent_per_day} onChange={set('room_rent_per_day')} placeholder="0" className={inputClass} />
          </Field>
          <p className="text-xs text-gray-500 mt-1">
            {rate > 0 && days > 0
              ? `${days} day${days === 1 ? '' : 's'} × ${money(rate)} = ${money(days * rate)}, added to your expenses as one room & board expense per day.`
              : 'Each day of the tour gets a room & board expense (rent, hotel, food). They update when you change the dates or the rate.'}
          </p>
        </div>
      )}
      {isTour && periodDays.length > 0 && (
        <p className="text-xs rounded-lg bg-rose-50 text-rose-800 px-3 py-2">
          Your period is {Object.values(cycle).includes('period') ? 'logged' : 'predicted'} for {periodDays.length} day{periodDays.length === 1 ? '' : 's'} of this tour
          ({periodDays[0] === periodDays[periodDays.length - 1] ? periodDays[0] : `${periodDays[0]} – ${periodDays[periodDays.length - 1]}`}).
        </p>
      )}
      {!isTour && (
        <p className="text-xs text-gray-500">
          You'll be asked to confirm if you book a client on these days. Days off are left out of "working days" when you compare earnings.
        </p>
      )}

      <Field label="Notes">
        <textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex items-center justify-between pt-2">
        {period ? (
          <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">
            Delete {isTour ? 'tour' : 'time off'}
          </button>
        ) : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>
          {saving ? 'Saving…' : period ? 'Save changes' : isTour ? 'Add tour' : 'Add time off'}
        </button>
      </div>
    </form>
  );
}
