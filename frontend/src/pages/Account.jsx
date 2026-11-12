import { useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from '../components/Modal';

export default function Account({ user, onLogout }) {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [message, setMessage] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setMessage(null);
    if (form.next !== form.confirm) return setMessage({ error: "New passwords don't match" });
    try {
      await axios.post('/api/auth/change-password', { current_password: form.current, new_password: form.next });
      setForm({ current: '', next: '', confirm: '' });
      setMessage({ ok: 'Password changed. Any other devices have been logged out.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not change password') });
    }
  };

  return (
    <div className="max-w-md bg-white rounded-2xl shadow-lg p-6">
      <h1 className="text-xl font-bold text-gray-800 mb-1">Account</h1>
      <p className="text-sm text-gray-500 mb-6">Logged in as <span className="font-medium text-gray-700">{user.username}</span></p>

      <form onSubmit={submit} className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-600">Change password</h2>
        <Field label="Current password">
          <input required type="password" autoComplete="current-password" value={form.current} onChange={set('current')} className={inputClass} />
        </Field>
        <Field label="New password">
          <input required type="password" minLength={8} autoComplete="new-password" value={form.next} onChange={set('next')} className={inputClass} />
        </Field>
        <Field label="Confirm new password">
          <input required type="password" autoComplete="new-password" value={form.confirm} onChange={set('confirm')} className={inputClass} />
        </Field>
        {message?.error && <p className="text-sm text-red-600">{message.error}</p>}
        {message?.ok && <p className="text-sm text-emerald-600">{message.ok}</p>}
        <button type="submit" className="px-5 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 text-sm">Change password</button>
      </form>

      <button onClick={onLogout} className="mt-8 text-sm text-red-500 hover:text-red-700">Log out</button>
    </div>
  );
}
