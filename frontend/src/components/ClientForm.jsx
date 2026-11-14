import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass } from './Modal';
import { PersonaSelect } from './Personas';
import { BadDateWarning } from './Blocklist';
import { SCREENING_STYLES } from '../colors';
import { fetchAll } from '../api';

const PLATFORMS = ['Instagram', 'X (Twitter)', 'OnlyFans', 'Fansly', 'TikTok', 'Snapchat', 'Telegram', 'WhatsApp',
  'Signal', 'Reddit', 'Discord', 'Bluesky', 'Facebook', 'LinkedIn', 'Tryst', 'Eros'];
const INDUSTRIES = ['Finance', 'Tech', 'Law', 'Medicine', 'Real estate', 'Sales', 'Entertainment', 'Hospitality', 'Construction',
  'Government', 'Education', 'Sports', 'Business owner', 'Retired', 'Student', 'Unknown'];

/**
 * Create a contact (no `client` prop; `initial` can fill some fields in, e.g. from an email) or edit one.
 * A name is optional: sometimes a handle is all that's known.
 */
export default function ClientForm({ client, initial, onSaved, onDeleted }) {
  const [handles, setHandles] = useState(
    client?.handles?.length ? client.handles.map((h) => ({ platform: h.platform || '', handle: h.handle })) : [{ platform: '', handle: '' }],
  );
  const [showAs, setShowAs] = useState(client?.display_handle != null ? String(client.display_handle) : 'name');
  const [form, setForm] = useState({
    name: client?.name || initial?.name || '',
    industry: client?.industry || '',
    persona_id: client?.persona_id ? String(client.persona_id) : '',
    role: client?.role || initial?.role || 'client',
    email: client?.email || initial?.email || '',
    contact_phone: client?.contact_phone || '',
    bio: client?.bio || initial?.bio || '',
    tags: (client?.tags || []).join(', '),
    is_active: client ? !!client.is_active : true,
    screening_status: client?.screening_status || 'unscreened',
    screening_notes: client?.screening_notes || '',
    references: client?.references || '',
    do_not_see: client?.do_not_see || false,
    do_not_see_reason: client?.do_not_see_reason || '',
    birthday: client?.birthday || '',
    drink_preferences: client?.drink_preferences || '',
    food_preferences: client?.food_preferences || '',
    couple_with: client?.couple_with ? String(client.couple_with) : '',
  });
  const [contacts, setContacts] = useState([]);
  useEffect(() => {
    fetchAll('/api/clients', { sort: 'name', role: 'client' }, 200).then(setContacts).catch(() => {});
  }, []);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    const filled = handles.map((h, i) => ({ ...h, i })).filter((h) => h.handle.trim());
    if (!form.name.trim() && filled.length === 0) {
      setSaving(false);
      return setError('Give a name or at least one social media handle');
    }
    const shownIndex = showAs === 'name' ? -1 : filled.findIndex((h) => String(h.i) === showAs);
    const body = {
      name: form.name.trim() || null,
      handles: filled.map((h) => ({ platform: h.platform.trim() || null, handle: h.handle.trim() })),
      display_handle: shownIndex < 0 ? null : shownIndex,
      industry: form.industry.trim() || null,
      persona_id: form.persona_id ? Number(form.persona_id) : null,
      role: form.role,
      couple_with: form.couple_with ? Number(form.couple_with) : null,
      email: form.email.trim() || null,
      contact_phone: form.contact_phone.trim() || null,
      bio: form.bio.trim() || null,
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
      is_active: form.is_active,
      screening_status: form.screening_status,
      screening_notes: form.screening_notes.trim() || null,
      references: form.references.trim() || null,
      do_not_see: form.do_not_see,
      do_not_see_reason: form.do_not_see ? form.do_not_see_reason.trim() || null : null,
      birthday: form.birthday || null,
      drink_preferences: form.drink_preferences.trim() || null,
      food_preferences: form.food_preferences.trim() || null,
    };
    try {
      const { data } = client
        ? await axios.put(`/api/clients/${client.id}`, body)
        : await axios.post('/api/clients', body);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save the contact'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete ${client.display_name}? This also deletes their appointments and notes.`)) return;
    try {
      await axios.delete(`/api/clients/${client.id}`);
      onDeleted?.();
    } catch (err) {
      setError(errorMessage(err, 'Could not delete the contact'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Who they are">
        {[['client', 'Client'], ['partner', 'Co-worker (another worker)'], ['crew', 'Photographer or crew'], ['other', 'Other']].map(([value, label]) => (
          <button key={value} type="button" role="radio" aria-checked={form.role === value} onClick={() => setForm({ ...form, role: value })}
            className={`px-3 py-1 rounded-full text-xs border ${form.role === value ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            {label}
          </button>
        ))}
      </div>
      <Field label="Name">
        <input autoFocus value={form.name} onChange={set('name')} placeholder="If you know it" className={inputClass} />
      </Field>

      <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-2">
        <legend className="px-1 text-xs font-medium text-gray-500">Social media and messaging</legend>
        <datalist id="handle-platforms">{PLATFORMS.map((x) => <option key={x} value={x} />)}</datalist>
        {handles.map((h, i) => (
          <div key={i} className="flex flex-wrap sm:flex-nowrap items-center gap-2">
            <input list="handle-platforms" value={h.platform} placeholder="Where (e.g. Instagram)" aria-label="Platform"
              onChange={(e) => setHandles(handles.map((x, j) => (j === i ? { ...x, platform: e.target.value } : x)))}
              className={`${inputClass} sm:!w-40`} />
            <input value={h.handle} placeholder="@handle, username or link" aria-label="Handle"
              onChange={(e) => setHandles(handles.map((x, j) => (j === i ? { ...x, handle: e.target.value } : x)))}
              className={inputClass} />
            <label className="flex items-center gap-1 text-xs text-gray-600 whitespace-nowrap" title="Show this contact by this handle">
              <input type="radio" name="show-as" checked={showAs === String(i)} onChange={() => setShowAs(String(i))} disabled={!h.handle.trim()} />
              Show as
            </label>
            <button type="button" onClick={() => {
              setHandles(handles.length > 1 ? handles.filter((_, j) => j !== i) : [{ platform: '', handle: '' }]);
              if (showAs === String(i)) setShowAs('name');
            }} className="text-gray-300 hover:text-red-500 text-sm px-1" aria-label="Remove this handle">✕</button>
          </div>
        ))}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" onClick={() => setHandles([...handles, { platform: '', handle: '' }])} className="text-xs text-sworkr-600 hover:text-sworkr-800">
            + Add another
          </button>
          <label className="flex items-center gap-1 text-xs text-gray-600">
            <input type="radio" name="show-as" checked={showAs === 'name'} onChange={() => setShowAs('name')} />
            Show by name (or the first handle if there's no name)
          </label>
        </div>
      </fieldset>

      {form.role === 'client' && (
        <Field label="Part of a couple with (optional)">
          <select value={form.couple_with} onChange={set('couple_with')} className={inputClass}>
            <option value="">Not a couple</option>
            {contacts.filter((c) => c.id !== client?.id).map((c) => (
              <option key={c.id} value={c.id}>{c.display_name}{c.couple_with && c.couple_with !== client?.id ? ` (now with ${c.couple_name})` : ''}</option>
            ))}
          </select>
          <span className="block text-xs text-gray-400 mt-1">Each of you keeps your own details; bookings can include both.</span>
        </Field>
      )}

      <PersonaSelect value={form.persona_id} onChange={set('persona_id')} />
      <Field label="Industry (what they do for work)">
        <input list="industries" value={form.industry} onChange={set('industry')} placeholder="e.g. Finance, Tech, Law" className={inputClass} />
        <datalist id="industries">{INDUSTRIES.map((x) => <option key={x} value={x} />)}</datalist>
      </Field>
      <BadDateWarning phone={form.contact_phone} email={form.email} handles={handles.map((h) => h.handle)} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Email">
          <input type="email" value={form.email} onChange={set('email')} className={inputClass} />
        </Field>
        <Field label="Phone">
          <input type="tel" value={form.contact_phone} onChange={set('contact_phone')} className={inputClass} />
        </Field>
      </div>
      <Field label="Tags (comma separated)">
        <input value={form.tags} onChange={set('tags')} placeholder="regular, travel" className={inputClass} />
      </Field>
      <Field label="About this contact">
        <textarea rows={2} value={form.bio} onChange={set('bio')} className={inputClass} />
      </Field>

      <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-3">
        <legend className="px-1 text-xs font-medium text-gray-500">Preferences</legend>
        <Field label="Birthday">
          <input type="date" value={form.birthday} onChange={set('birthday')} max={new Date().toISOString().slice(0, 10)} className={inputClass} />
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Drinks">
            <textarea rows={2} value={form.drink_preferences} onChange={set('drink_preferences')} placeholder="e.g. Dry martini, no ice" className={inputClass} />
          </Field>
          <Field label="Food">
            <textarea rows={2} value={form.food_preferences} onChange={set('food_preferences')} placeholder="e.g. Loves sushi, no shellfish" className={inputClass} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-3">
        <legend className="px-1 text-xs font-medium text-gray-500">Screening</legend>
        <Field label="Status">
          <select value={form.screening_status} onChange={set('screening_status')} className={inputClass}>
            {Object.entries(SCREENING_STYLES).map(([value, s]) => <option key={value} value={value}>{s.label}</option>)}
          </select>
        </Field>
        <Field label="References">
          <textarea rows={2} value={form.references} onChange={set('references')} placeholder="Who vouched for them, and how to reach those people" className={inputClass} />
        </Field>
        <Field label="Screening notes">
          <textarea rows={2} value={form.screening_notes} onChange={set('screening_notes')} placeholder="What you checked and when" className={inputClass} />
        </Field>
      </fieldset>

      <div className={`rounded-lg border px-3 py-2 ${form.do_not_see ? 'border-red-300 bg-red-50' : 'border-gray-200'}`}>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.do_not_see} onChange={set('do_not_see')} />
          <span>Do not see <span className="text-xs text-gray-500">(warns you if you try to book them)</span></span>
        </label>
        {form.do_not_see && (
          <input value={form.do_not_see_reason} onChange={set('do_not_see_reason')} placeholder="Reason" aria-label="Reason" className={`${inputClass} mt-2 bg-white`} />
        )}
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.is_active} onChange={set('is_active')} />
        Active contact
      </label>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex items-center justify-between pt-2">
        {client ? (
          <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">
            Delete contact
          </button>
        ) : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>
          {saving ? 'Saving…' : client ? 'Save changes' : 'Add contact'}
        </button>
      </div>
    </form>
  );
}
