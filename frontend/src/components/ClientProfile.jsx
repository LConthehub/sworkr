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
  const filled = p.languages || p.translator || p.culture || p.talk_about || p.avoid || p.deceased;
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
        </dl>
      ) : (
        <p className="mt-1 text-xs text-gray-400">Languages, cultural practices, what to talk about and what to avoid.</p>
      )}
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
    talk_about: profile.talk_about || '', avoid: profile.avoid || '', deceased_on: profile.deceased_on || '' });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    try {
      const { data } = await axios.put(`/api/clients/${clientId}/profile`, { ...form, deceased_on: form.deceased && form.deceased_on ? form.deceased_on : null });
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
