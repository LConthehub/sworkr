import { useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from '../components/Modal';

/** Shown when not logged in. With `setup`, it creates the first account instead. */
export default function Login({ setup, onLoggedIn }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (setup && password !== confirm) return setError("Passwords don't match");
    setBusy(true);
    try {
      const { data } = await axios.post(setup ? '/api/auth/setup' : '/api/auth/login', { username, password });
      onLoggedIn(data);
    } catch (err) {
      setError(errorMessage(err, 'Could not log in'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl shadow-xl p-6 space-y-4">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-sworkr-500 to-sworkr-800 flex items-center justify-center text-white font-bold text-xl">SW</div>
          <div>
            <h1 className="font-bold text-gray-800 text-lg">Sworkr</h1>
            <p className="text-xs text-gray-500">{setup ? 'Create your account to get started' : 'Log in to continue'}</p>
          </div>
        </div>

        <Field label="Username">
          <input required autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Password">
          <input
            required
            type="password"
            autoComplete={setup ? 'new-password' : 'current-password'}
            minLength={setup ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </Field>
        {setup && (
          <>
            <Field label="Confirm password">
              <input required type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={inputClass} />
            </Field>
            <p className="text-xs text-gray-400">At least 8 characters. There's no password reset yet, so keep it somewhere safe.</p>
          </>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button type="submit" disabled={busy} className="w-full py-2.5 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50 font-medium">
          {busy ? 'Please wait…' : setup ? 'Create account' : 'Log in'}
        </button>
      </form>
    </div>
  );
}
