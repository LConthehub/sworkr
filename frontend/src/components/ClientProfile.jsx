import { useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass } from './Modal';

/** "Getting to know them": languages, culture, what to talk about and avoid; deceased. On the client's page. */
export default function ClientProfile({ clientId, onChanged }) {
  const [p, setP] = useState(null);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    axios.get(`/api/clients/${clientId}/profile`).then(({ data }) => setP(data)).catch(() => {});
  }, [clientId]);
  if (!p) return null;
  const filled = p.languages || p.translator || p.culture || p.talk_about || p.avoid || p.deceased || p.outdates || p.outdate_notes;
  return (
    <div className="mt-4 rounded-xl border border-gray-100 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Getting to know them</p>
        <button onClick={() => setEditing(true)} className="text-xs text-sworkr-600 hover:text-sworkr-800">{filled ? 'Edit' : '+ Add'}</button>
      </div>
      {p.deceased && <p className="mt-1 text-sm text-gray-700">🕊 Passed away{p.deceased_on ? ` (${p.deceased_on})` : ''}</p>}
      {filled ? (
        <dl className="mt-1 grid sm:grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {(p.languages || p.translator) && <><dt className="text-gray-500">Language</dt><dd className="text-gray-800">{p.languages}{p.translator && <span className="ml-1 text-xs px-1.5 rounded bg-amber-100 text-amber-800">needs a translator</span>}</dd></>}
          {p.culture && <><dt className="text-gray-500">Culture</dt><dd className="text-gray-800 whitespace-pre-wrap">{p.culture}</dd></>}
          {p.talk_about && <><dt className="text-gray-500">Talk about</dt><dd className="text-gray-800 whitespace-pre-wrap">{p.talk_about}</dd></>}
          {p.avoid && <><dt className="text-gray-500">Avoid</dt><dd className="text-gray-800 whitespace-pre-wrap">{p.avoid}</dd></>}
          {(p.outdates || p.outdate_notes) && <><dt className="text-gray-500">Outdates</dt><dd className="text-gray-800 whitespace-pre-wrap">{p.outdates === 'yes' ? 'Yes' : p.outdates === 'no' ? 'No' : ''}{p.outdates && p.outdate_notes ? ': ' : ''}{p.outdate_notes}</dd></>}
        </dl>
      ) : (
        <p className="mt-1 text-xs text-gray-400">Languages, cultural practices, what to talk about and what to avoid.</p>
      )}
      <ReviewHistory clientId={clientId} />
      {editing && (
        <Modal title="Getting to know them" onClose={() => setEditing(false)}>
          <ProfileForm clientId={clientId} profile={p} onSaved={(data) => { setP(data); setEditing(false); if (data.deceased) onChanged?.(); }} />
        </Modal>
      )}
    </div>
  );
}

function ProfileForm({ clientId, profile, onSaved }) {
  const [form, setForm] = useState({ ...profile, languages: profile.languages || '', culture: profile.culture || '',
    talk_about: profile.talk_about || '', avoid: profile.avoid || '', deceased_on: profile.deceased_on || '',
    outdates: profile.outdates || '', outdate_notes: profile.outdate_notes || '' });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    try {
      const { data } = await axios.put(`/api/clients/${clientId}/profile`, { ...form, outdates: form.outdates || null, deceased_on: form.deceased && form.deceased_on ? form.deceased_on : null });
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3 items-end">
        <Field label="Languages they speak"><input value={form.languages} onChange={set('languages')} placeholder="e.g. Spanish, a little English" className={inputClass} /></Field>
        <label className="flex items-center gap-2 text-sm text-gray-700 pb-2"><input type="checkbox" checked={form.translator} onChange={set('translator')} /> Needs a translator</label>
      </div>
      <Field label="Cultural practices to remember"><textarea rows={2} value={form.culture} onChange={set('culture')} placeholder="e.g. Shoes off indoors, doesn't drink, prays at sunset" className={inputClass} /></Field>
      <Field label="Good to talk about"><textarea rows={2} value={form.talk_about} onChange={set('talk_about')} placeholder="e.g. Football, their dog, travel" className={inputClass} /></Field>
      <Field label="Avoid"><textarea rows={2} value={form.avoid} onChange={set('avoid')} placeholder="e.g. Their work, their ex" className={inputClass} /></Field>
      {(profile.outdates_possible || profile.outdates || profile.outdate_notes) && (
        <div className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-3 border-t border-gray-100 pt-3">
          <Field label="Outdates">
            <select value={form.outdates} onChange={set('outdates')} className={inputClass}>
              <option value="">Not asked</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </Field>
          <Field label="About their outdates"><input value={form.outdate_notes} onChange={set('outdate_notes')} placeholder="e.g. Dinner in town, likes four hours" className={inputClass} /></Field>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 border-t border-gray-100 pt-3">
        <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={form.deceased} onChange={set('deceased')} /> Passed away</label>
        {form.deceased && <input type="date" value={form.deceased_on} onChange={set('deceased_on')} aria-label="When" className={`${inputClass} !w-auto`} />}
        {form.deceased && <span className="text-xs text-gray-500">Their history stays; they're set inactive, so no reminders.</span>}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save</button></div>
    </form>
  );
}

const RATING = { great: 'Great', fine: 'Fine', bad: 'Not good' };
const AGAIN = { yes: 'Yes', maybe: 'Maybe', no: 'No' };

function Choice({ options, value, onChange, label }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 mb-1">{label}</p>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={label}>
        {Object.entries(options).map(([v, l]) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(value === v ? null : v)}
            className={`px-3 py-1.5 rounded-full text-sm border ${value === v ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>{l}</button>
        ))}
      </div>
    </div>
  );
}

/** After a booking: a few quick questions, saved to the client's profile. */
export function BookingReview({ appointment, onClose }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get(`/api/appointments/${appointment.id}/review`)
      .then(({ data }) => setForm({ rating: data?.rating || null, again: data?.again || null, talked_about: data?.talked_about || '', notes: data?.notes || '' }))
      .catch(() => setForm({ rating: null, again: null, talked_about: '', notes: '' }));
  }, [appointment.id]);
  const submit = async (e) => {
    e.preventDefault();
    try {
      await axios.put(`/api/appointments/${appointment.id}/review`, form);
      onClose(true);
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  return (
    <Modal title={`How did it go${appointment.client_name ? ` with ${appointment.client_name}` : ''}?`} onClose={() => onClose(false)}>
      {form && (
        <form onSubmit={submit} className="space-y-3">
          <Choice label="How it went" options={RATING} value={form.rating} onChange={(v) => setForm({ ...form, rating: v })} />
          <Choice label="See them again?" options={AGAIN} value={form.again} onChange={(v) => setForm({ ...form, again: v })} />
          <Field label="What you talked about"><textarea rows={2} value={form.talked_about} onChange={(e) => setForm({ ...form, talked_about: e.target.value })} placeholder="Things to remember for next time" className={inputClass} /></Field>
          <Field label="Notes"><textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputClass} /></Field>
          {form.again === 'no' && <p className="text-xs text-amber-800 bg-amber-50 rounded-lg px-3 py-2">If you never want to see them again, you can also tick <b>Do not see</b> on their contact.</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end"><button type="submit" className={buttonClass}>Save</button></div>
        </form>
      )}
    </Modal>
  );
}

/** On the client's page: how bookings with them have gone. */
export function ReviewHistory({ clientId }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    axios.get(`/api/clients/${clientId}/reviews`).then(({ data: d }) => setData(d)).catch(() => {});
  }, [clientId]);
  if (!data || data.reviews.length === 0) return null;
  const count = (obj, labels) => Object.entries(obj).filter(([, n]) => n).map(([k, n]) => `${n} ${labels[k].toLowerCase()}`).join(', ');
  return (
    <div className="mt-3 border-t border-gray-100 pt-2">
      <p className="text-xs text-gray-500">After bookings: {count(data.ratings, RATING) || 'no ratings'} · see again: {count(data.again, AGAIN) || '–'}</p>
      <ul className="mt-1 space-y-1 text-sm">
        {data.reviews.slice(0, 5).filter((r) => r.talked_about || r.notes).map((r) => (
          <li key={r.appointment_id} className="text-gray-700">
            <span className="text-xs text-gray-400 mr-2">{r.scheduled_date?.slice(0, 10)}</span>
            {[r.talked_about, r.notes].filter(Boolean).join(' · ')}
          </li>
        ))}
      </ul>
    </div>
  );
}
