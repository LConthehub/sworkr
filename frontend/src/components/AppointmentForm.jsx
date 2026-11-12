import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';
import { toDateInput, toTimeInput, fromDateTimeInputs } from '../colors';

const DURATIONS = [30, 45, 60, 90, 120, 180, 240, 480, 720];

/**
 * Create an appointment (pass `defaultDate`) or edit one (pass `appointment`).
 * Times are entered in the browser's local time and sent to the server in UTC.
 */
export default function AppointmentForm({ appointment, defaultDate, onSaved, onDeleted }) {
  const start = appointment ? new Date(appointment.scheduled_date) : defaultDate || new Date();
  const [form, setForm] = useState({
    client_id: appointment?.client_id ? String(appointment.client_id) : '',
    service_type: appointment?.service_type || '',
    date: toDateInput(start),
    time: appointment ? toTimeInput(start) : '19:00',
    duration_minutes: String(appointment?.duration_minutes || 60),
    status: appointment?.status || 'scheduled',
    notes: appointment?.notes || '',
  });
  const [clients, setClients] = useState([]);
  const [serviceTypes, setServiceTypes] = useState([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  useEffect(() => {
    axios.get('/api/clients', { params: { limit: 200 } }).then(({ data }) => setClients(data)).catch(() => {});
    axios.get('/api/appointments/service-types').then(({ data }) => setServiceTypes(data)).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.client_id) return setError('Choose a client');
    setSaving(true);
    const body = {
      client_id: Number(form.client_id),
      service_type: form.service_type.trim(),
      duration_minutes: Number(form.duration_minutes),
      scheduled_date: fromDateTimeInputs(form.date, form.time).toISOString(),
      status: form.status,
      notes: form.notes.trim() || null,
    };
    try {
      const { data } = appointment
        ? await axios.put(`/api/appointments/${appointment.id}`, body)
        : await axios.post('/api/appointments', body);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save appointment'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm('Delete this appointment?')) return;
    try {
      await axios.delete(`/api/appointments/${appointment.id}`);
      onDeleted?.();
    } catch (err) {
      setError(errorMessage(err, 'Could not delete appointment'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Client *">
        <select required value={form.client_id} onChange={set('client_id')} className={inputClass}>
          <option value="">Choose a client…</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>{c.name}{c.is_active ? '' : ' (inactive)'}</option>
          ))}
        </select>
      </Field>
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
      <div className="grid grid-cols-3 gap-3">
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
      {appointment && (
        <Field label="Status">
          <select value={form.status} onChange={set('status')} className={inputClass}>
            <option value="scheduled">Scheduled</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </Field>
      )}
      <Field label="Notes">
        <textarea rows={3} value={form.notes} onChange={set('notes')} className={inputClass} />
      </Field>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex items-center justify-between pt-2">
        {appointment ? (
          <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">
            Delete appointment
          </button>
        ) : <span />}
        <button
          type="submit"
          disabled={saving}
          className="px-5 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50 text-sm"
        >
          {saving ? 'Saving…' : appointment ? 'Save changes' : 'Add appointment'}
        </button>
      </div>
    </form>
  );
}
