import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

/** Settings > Security & privacy > Decoy password. */
export default function DecoyPassword() {
  const [enabled, setEnabled] = useState(null);
  const [form, setForm] = useState({ current_password: '', decoy_password: '' });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { axios.get('/api/account/decoy').then(({ data }) => setEnabled(data.enabled)).catch(() => setEnabled(false)); }, []);
  if (enabled === null) return null;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const finish = (data, text) => { setEnabled(data.enabled); setForm({ current_password: '', decoy_password: '' }); setError(''); setMessage(text); };
  const save = async (e) => {
    e.preventDefault();
    try {
      const { data } = await axios.put('/api/account/decoy', form);
      finish(data, 'Saved. Log out and try it once, so you know what it looks like.');
    } catch (err) {
      setMessage('');
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  const remove = async () => {
    if (!form.current_password) { setError('Type your real password first.'); return; }
    if (!window.confirm('Remove the decoy password, and everything in the decoy account?')) return;
    try {
      const { data } = await axios.post('/api/account/decoy/remove', { current_password: form.current_password });
      finish(data, 'The decoy is gone.');
    } catch (err) {
      setMessage('');
      setError(errorMessage(err, "Couldn't remove it"));
    }
  };
  return (
    <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-gray-600">
        A second password for the moment someone makes you unlock Sworkr. Type it instead of your real one, and Sworkr opens a
        separate account with none of your records in it, under the same username.
      </p>
      <ul className="text-xs text-gray-500 list-disc pl-5 space-y-1">
        <li>Log in with the decoy password once and add a few plain things, so it doesn't look unused.</li>
        <li>If it's ever used, your real account's sign-in history says so.</li>
        <li>It hides your records from someone looking at the screen. It can't hide them from someone who takes the computer Sworkr runs on.</li>
      </ul>
      <p className="text-sm text-gray-800">{enabled ? 'A decoy password is set.' : 'No decoy password yet.'}</p>
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Your real password"><input type="password" autoComplete="current-password" required value={form.current_password} onChange={set('current_password')} className={inputClass} /></Field>
        <Field label={enabled ? 'New decoy password' : 'Decoy password'}><input type="password" autoComplete="new-password" minLength={12} value={form.decoy_password} onChange={set('decoy_password')} className={inputClass} /></Field>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-emerald-700">{message}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {enabled && <button type="button" onClick={remove} className={quietButtonClass}>Remove the decoy</button>}
        <button type="submit" disabled={!form.decoy_password} className={`${buttonClass} disabled:opacity-50`}>{enabled ? 'Change it' : 'Set it'}</button>
      </div>
    </form>
  );
}
