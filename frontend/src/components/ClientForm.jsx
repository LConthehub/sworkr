import { useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';

/** Create a client (no `client` prop) or edit one. */
export default function ClientForm({ client, onSaved, onDeleted }) {
  const [form, setForm] = useState({
    name: client?.name || '',
    email: client?.email || '',
    contact_phone: client?.contact_phone || '',
    bio: client?.bio || '',
    tags: (client?.tags || []).join(', '),
    is_active: client ? !!client.is_active : true,
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    const body = {
      name: form.name.trim(),
      email: form.email.trim() || null,
      contact_phone: form.contact_phone.trim() || null,
      bio: form.bio.trim() || null,
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
      is_active: form.is_active,
    };
    try {
      const { data } = client
        ? await axios.put(`/api/clients/${client.id}`, body)
        : await axios.post('/api/clients', body);
      onSaved(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not save client'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete ${client.name}? This also deletes their appointments.`)) return;
    try {
      await axios.delete(`/api/clients/${client.id}`);
      onDeleted?.();
    } catch (err) {
      setError(errorMessage(err, 'Could not delete client'));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Name *">
        <input required autoFocus value={form.name} onChange={set('name')} className={inputClass} />
      </Field>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Email">
          <input type="email" value={form.email} onChange={set('email')} className={inputClass} />
        </Field>
        <Field label="Phone">
          <input value={form.contact_phone} onChange={set('contact_phone')} className={inputClass} />
        </Field>
      </div>
      <Field label="Tags (comma separated)">
        <input value={form.tags} onChange={set('tags')} placeholder="regular, verified" className={inputClass} />
      </Field>
      <Field label="Notes">
        <textarea rows={3} value={form.bio} onChange={set('bio')} className={inputClass} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={form.is_active} onChange={set('is_active')} />
        Active client
      </label>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex items-center justify-between pt-2">
        {client ? (
          <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">
            Delete client
          </button>
        ) : <span />}
        <button
          type="submit"
          disabled={saving}
          className="px-5 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50 text-sm"
        >
          {saving ? 'Saving…' : client ? 'Save changes' : 'Add client'}
        </button>
      </div>
    </form>
  );
}
