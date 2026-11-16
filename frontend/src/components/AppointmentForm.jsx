import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useTestKinds } from './TestKinds';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { fetchAll, saveAppointment } from '../api';
import { SplitEditor, useSplit } from './Splits';
import {
  toDateInput, toTimeInput, fromDateTimeInputs, repeatDates, formatTime, dayLabel, LOCATION_LABELS, money,
} from '../colors';

const DURATIONS = [30, 45, 60, 90, 120, 180, 240, 480, 720];
const REPEATS = [
  { value: '', label: "Doesn't repeat" },
  { value: 'week', label: 'Every week' },
  { value: '2weeks', label: 'Every 2 weeks' },
  { value: 'month', label: 'Every month' },
];

/**
 * Create an appointment (pass `defaultDate`, optionally `defaultClientId`) or edit one (pass `appointment`).
 * `defaultKind` 'test' starts a health test instead (optionally with `defaultTestType` and `defaultTourId`).
 * Times are entered in the browser's local time and sent to the server in UTC.
 */
export default function AppointmentForm({
  appointment, defaultDate, defaultClientId, defaultKind = 'client', defaultTestType = 'weekly', defaultTourId,
  onSaved, onDeleted,
}) {
  const start = appointment ? new Date(appointment.scheduled_date) : defaultDate || new Date();
  const startsAsTest = (appointment?.kind || defaultKind) === 'test';
  const [form, setForm] = useState({
    kind: startsAsTest ? 'test' : 'client',
    test_type: appointment?.test_type || defaultTestType,
    cost: appointment?.cost != null ? String(appointment.cost) : '',
    tour_id: appointment ? (appointment.tour_id ? String(appointment.tour_id) : '') : defaultTourId ? String(defaultTourId) : '',
    client_id: appointment?.client_id ? String(appointment.client_id) : defaultClientId ? String(defaultClientId) : '',
    as_couple: !!appointment?.second_client_id,
    service_type: appointment?.service_type || '',
    date: toDateInput(start),
    time: appointment || defaultDate ? toTimeInput(start) : '19:00',
    duration_minutes: String(appointment?.duration_minutes || (startsAsTest ? 30 : 60)),
    status: appointment?.status || 'scheduled',
    notes: appointment?.notes || '',
    rate: appointment?.rate != null ? String(appointment.rate) : '',
    amount_paid: appointment?.amount_paid ? String(appointment.amount_paid) : '',
    payment_method: appointment?.payment_method || '',
    location_type: appointment?.location_type || '',
    location: appointment?.location || '',
    safety_checkin: appointment?.safety_checkin || false,
    repeat: '',
    repeat_count: '4',
  });
  const [clients, setClients] = useState([]);
  const [serviceTypes, setServiceTypes] = useState([]);
  const [safety, setSafety] = useState(null);
  const [tours, setTours] = useState([]);
  const [testCosts, setTestCosts] = useState({});
  // Once the cost or tour is chosen by hand, it isn't filled in automatically any more.
  const [touched, setTouched] = useState({ cost: !!appointment, tour: !!appointment || !!defaultTourId });
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState(null);
  const [saving, setSaving] = useState(false);
  const warningBox = useRef(null);
  useEffect(() => {
    // The warning is at the bottom of a long form: bring it into view when it appears.
    if (warnings) warningBox.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [warnings]);
  const set = (k) => (e) => {
    setWarnings(null);
    if (k === 'cost' || k === 'tour_id') setTouched((t) => ({ ...t, [k === 'cost' ? 'cost' : 'tour']: true }));
    setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  };
  const isTest = form.kind === 'test';

  useEffect(() => {
    fetchAll('/api/clients', { sort: 'name' }, 200).then(setClients).catch(() => {});
    axios.get('/api/appointments/service-types').then(({ data }) => setServiceTypes(data)).catch(() => {});
    axios.get('/api/safety').then(({ data }) => setSafety(data)).catch(() => {});
    axios.get('/api/tours', { params: { kind: 'tour' } }).then(({ data }) => setTours(data)).catch(() => {});
    axios.get('/api/appointments/test-costs').then(({ data }) => setTestCosts(data)).catch(() => {});
  }, []);
  const { options: TEST_TYPES } = useTestKinds(form.test_type);
  // The usual first choice may be one this person has hidden: start on one they use.
  useEffect(() => {
    const keys = Object.keys(TEST_TYPES);
    if (!appointment && keys.length && !keys.includes(form.test_type)) setForm((f) => ({ ...f, test_type: keys[0] }));
  }, [TEST_TYPES]);   // eslint-disable-line react-hooks/exhaustive-deps

  // A test's cost starts as what that kind of test cost last time.
  useEffect(() => {
    if (!isTest || touched.cost) return;
    const last = testCosts[form.test_type];
    setForm((f) => ({ ...f, cost: last != null ? String(last) : '' }));
  }, [isTest, form.test_type, testCosts, touched.cost]);

  // ...and its tour is the one on that day, if there is one.
  useEffect(() => {
    if (!isTest || touched.tour) return;
    const onDay = tours.find((t) => t.start_date <= form.date && t.end_date >= form.date);
    setForm((f) => ({ ...f, tour_id: onDay ? String(onDay.id) : '' }));
  }, [isTest, form.date, tours, touched.tour]);

  const client = clients.find((c) => String(c.id) === form.client_id);
  const rate = form.rate === '' ? null : Number(form.rate);
  const paid = form.amount_paid === '' ? 0 : Number(form.amount_paid);
  // Your deposit percentage (booking policy), for the "deposit paid" shortcut.
  const [depositPercent, setDepositPercent] = useState(0);
  useEffect(() => { axios.get('/api/booking-policy').then(({ data }) => setDepositPercent(data.deposit_percent || 0)).catch(() => {}); }, []);
  const [split, setSplit, saveSplit] = useSplit('appointment', appointment?.id);

  const submit = async (e, confirmed = false) => {
    e?.preventDefault();
    setError('');
    if (!form.date || !form.time) return setError('Choose a date and start time');
    const first = fromDateTimeInputs(form.date, form.time);
    let body;
    if (isTest) {
      const cost = form.cost === '' ? null : Number(form.cost);
      if (cost !== null && !(cost >= 0)) return setError('Cost must be 0 or more');
      body = {
        kind: 'test',
        test_type: form.test_type,
        cost,
        tour_id: form.tour_id ? Number(form.tour_id) : null,
        duration_minutes: Number(form.duration_minutes),
        scheduled_date: first.toISOString(),
        status: form.status,
        notes: form.notes.trim() || null,
        location: form.location.trim() || null,
      };
    } else {
      if (!form.client_id) return setError('Choose a client');
      if ((rate !== null && !(rate >= 0)) || !(paid >= 0)) return setError('Rate and amount paid must be 0 or more');
      body = {
        kind: 'client',
        client_id: Number(form.client_id),
        second_client_id: form.as_couple && client?.couple_with ? client.couple_with : null,
        service_type: form.service_type.trim(),
        duration_minutes: Number(form.duration_minutes),
        scheduled_date: first.toISOString(),
        status: form.status,
        notes: form.notes.trim() || null,
        rate,
        amount_paid: paid,
        payment_method: form.payment_method.trim() || null,
        location_type: form.location_type || null,
        location: form.location.trim() || null,
        safety_checkin: form.safety_checkin,
      };
    }
    if (!appointment && !isTest && form.repeat) {
      const count = Math.min(Math.max(Number(form.repeat_count) || 2, 2), 52);
      body.repeat_dates = repeatDates(first, form.repeat, count).map((d) => d.toISOString());
    }
    setSaving(true);
    try {
      const result = appointment
        ? await saveAppointment('put', `/api/appointments/${appointment.id}`, body, confirmed)
        : await saveAppointment('post', '/api/appointments', body, confirmed);
      if (result.warnings) setWarnings(result.warnings);
      else {
        if (!isTest) await saveSplit(result.data.id);
        onSaved(result.data);
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not save appointment'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (scope) => {
    const what = isTest ? 'this test and its cost'
      : scope === 'following' ? 'this appointment and all later ones in the series' : 'this appointment';
    if (!window.confirm(`Delete ${what}?`)) return;
    try {
      await axios.delete(`/api/appointments/${appointment.id}`, { params: { scope } });
      onDeleted?.();
    } catch (err) {
      setError(errorMessage(err, 'Could not delete appointment'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden" role="group" aria-label="What is it?">
        {[['client', 'Client appointment'], ['test', 'Health test']].map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => { setWarnings(null); setForm((f) => ({ ...f, kind: value })); }}
            aria-pressed={form.kind === value}
            className={`px-3 sm:px-4 py-1.5 text-sm ${form.kind === value ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
          >
            {label}
          </button>
        ))}
      </div>

      {isTest && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Test *">
              <select value={form.test_type} onChange={set('test_type')} className={inputClass}>
                {Object.entries(TEST_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
            <Field label="Cost ($)">
              <input type="number" min="0" step="0.01" inputMode="decimal" value={form.cost} onChange={set('cost')} placeholder="0" className={inputClass} />
            </Field>
          </div>
          <Field label="Tour">
            <select value={form.tour_id} onChange={set('tour_id')} className={inputClass}>
              <option value="">No tour</option>
              {tours.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.start_date} – {t.end_date})</option>)}
            </select>
          </Field>
          <p className="text-xs text-gray-500 -mt-1">The cost is added to your expenses as Medical{form.tour_id ? ', on this tour' : ''}.</p>
        </>
      )}

      {!isTest && (<>
      <Field label="Client *">
        <select required value={form.client_id} onChange={set('client_id')} className={inputClass}>
          <option value="">Choose a client…</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.do_not_see ? '⚠ ' : ''}{c.display_name}{c.do_not_see ? ' (do not see)' : c.is_active ? '' : ' (inactive)'}
            </option>
          ))}
        </select>
      </Field>
      {client?.do_not_see && (
        <p className="text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">
          <strong>Do not see.</strong> {client.do_not_see_reason || 'This client is flagged.'}
        </p>
      )}
      {client?.couple_with && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.as_couple} onChange={set('as_couple')} />
          Book as a couple with {client.couple_name}
        </label>
      )}
      {client && !client.do_not_see && client.screening_status !== 'verified' && (
        <p className="text-xs text-amber-700">
          {client.screening_status === 'declined' ? 'Screening was declined for this client.' : 'This client has not been verified yet.'}
        </p>
      )}

      <Field label="Service *">
        <input
          required
          list="service-types"
          value={form.service_type}
          onChange={set('service_type')}
          placeholder="e.g. Individual Session"
          className={inputClass}
        />
        <datalist id="service-types">
          {serviceTypes.map((s) => <option key={s} value={s} />)}
        </datalist>
      </Field>
      </>)}

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Field label="Date *">
          <input required type="date" value={form.date} onChange={set('date')} className={inputClass} />
        </Field>
        <Field label="Start time *">
          <input required type="time" value={form.time} onChange={set('time')} className={inputClass} />
        </Field>
        <Field label="Length">
          <select value={form.duration_minutes} onChange={set('duration_minutes')} className={inputClass}>
            {[...new Set([...DURATIONS, Number(form.duration_minutes)])].sort((a, b) => a - b).map((d) => (
              <option key={d} value={d}>{d < 60 ? `${d} min` : `${d / 60} h`}</option>
            ))}
          </select>
        </Field>
      </div>

      {!appointment && !isTest && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Repeat">
            <select value={form.repeat} onChange={set('repeat')} className={inputClass}>
              {REPEATS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </Field>
          {form.repeat && (
            <Field label="How many times in total">
              <input type="number" min="2" max="52" value={form.repeat_count} onChange={set('repeat_count')} className={inputClass} />
            </Field>
          )}
        </div>
      )}

      {isTest ? (
        <Field label="Clinic (optional)">
          <input value={form.location} onChange={set('location')} placeholder="Clinic name or address" className={inputClass} />
        </Field>
      ) : (<>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Where">
          <select value={form.location_type} onChange={set('location_type')} className={inputClass}>
            <option value="">Not set</option>
            {Object.entries(LOCATION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
        <Field label="Address or place">
          <input value={form.location} onChange={set('location')} placeholder="Hotel, room, address" className={inputClass} />
        </Field>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Field label="Rate ($)">
          <input type="number" min="0" step="0.01" inputMode="decimal" value={form.rate} onChange={set('rate')} className={inputClass} />
        </Field>
        <Field label="Paid so far ($)">
          <input type="number" min="0" step="0.01" inputMode="decimal" value={form.amount_paid} onChange={set('amount_paid')} placeholder="0" className={inputClass} />
        </Field>
        <Field label="Paid by">
          <input list="payment-methods" value={form.payment_method} onChange={set('payment_method')} placeholder="Cash" className={inputClass} />
          <datalist id="payment-methods">
            {['Cash', 'Bank transfer', 'Card', 'Cash App', 'Venmo', 'PayPal', 'Crypto', 'Gift card'].map((m) => <option key={m} value={m} />)}
          </datalist>
        </Field>
      </div>
      {rate !== null && rate > 0 && paid < rate && (
        <div className="flex flex-wrap gap-3">
          {depositPercent > 0 && paid < rate * depositPercent / 100 && (
            <button type="button" onClick={() => setForm({ ...form, amount_paid: String(Math.round(rate * depositPercent) / 100) })} className="text-xs text-sworkr-600 hover:text-sworkr-800">
              Deposit paid ({depositPercent}%: {money(rate * depositPercent / 100)})
            </button>
          )}
          <button type="button" onClick={() => setForm({ ...form, amount_paid: String(rate) })} className="text-xs text-sworkr-600 hover:text-sworkr-800">
            Mark as paid in full
          </button>
        </div>
      )}
      </>)}

      {appointment && (
        <Field label="Status">
          <select value={form.status} onChange={set('status')} className={inputClass}>
            <option value="scheduled">Scheduled</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </Field>
      )}

      {!isTest && (
      <div className="rounded-lg border border-gray-200 px-3 py-2">
        <label className="flex items-start gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.safety_checkin} onChange={set('safety_checkin')} className="mt-1" />
          <span>
            Safety check-in
            <span className="block text-xs text-gray-500">
              {safety?.armed
                ? `If you don't check in within ${safety.grace_minutes} minutes of the end, ${safety.contact_name || safety.contact_email} gets an email.`
                : 'Reminds you in the app to check in afterwards.'}
            </span>
          </span>
        </label>
        {form.safety_checkin && safety && !safety.armed && (
          <p className="mt-2 text-xs rounded px-2 py-1 bg-amber-50 text-amber-800">
            No alert will be sent to anyone yet: {!safety.contact_email ? 'add a trusted contact' : 'email sending is not set up'} (Account → Safety check-in).
          </p>
        )}
      </div>
      )}

      {!isTest && <SplitEditor split={split} onChange={setSplit} base={paid} kind="booking" handledLabel="Who was paid" />}

      <Field label="Notes">
        <textarea rows={3} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {warnings && (
        <div ref={warningBox} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900" role="alert">
          <p className="font-semibold">Check this before saving</p>
          <ul className="mt-1 list-disc pl-5 space-y-0.5">
            {warnings.map((w, i) => (
              <li key={i}>
                {w.type === 'overlap'
                  ? `Overlaps with ${w.client_name || w.service_type || 'another appointment'} on ${dayLabel(new Date(w.starts_at), { weekday: 'short', month: 'short', day: 'numeric' })} at ${formatTime(new Date(w.starts_at))}`
                  : w.message}
              </li>
            ))}
          </ul>
          <div className="flex gap-2 mt-3">
            <button type="button" disabled={saving} onClick={() => submit(null, true)} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm hover:bg-amber-700 disabled:opacity-50">
              Save anyway
            </button>
            <button type="button" onClick={() => setWarnings(null)} className={quietButtonClass}>Go back</button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
        {appointment ? (
          <span className="flex flex-wrap gap-3">
            <button type="button" onClick={() => remove('one')} className="text-sm text-red-500 hover:text-red-700">
              {isTest ? 'Delete test' : 'Delete appointment'}
            </button>
            {appointment.series_id && (
              <button type="button" onClick={() => remove('following')} className="text-sm text-red-500 hover:text-red-700">
                Delete this and later repeats
              </button>
            )}
          </span>
        ) : <span />}
        {!warnings && (
          <button type="submit" disabled={saving} className={buttonClass}>
            {saving ? 'Saving…' : appointment ? 'Save changes' : isTest ? 'Add test' : form.repeat ? 'Add appointments' : 'Add appointment'}
          </button>
        )}
      </div>
    </form>
  );
}
