import { useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from '../components/Modal';

/**
 * Shown when not logged in. With `setup`, it creates the first account instead.
 * On the demo copy, `demoLogin` ({ username, password }) is shown under the form with a button to fill it in.
 */
export default function Login({ setup, demoLogin, onLoggedIn }) {
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
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 px-4 py-8">
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

      {demoLogin && !setup && (
        <div className="w-full max-w-sm rounded-2xl bg-white/95 shadow-lg p-4 text-sm text-gray-700" role="note">
          <p>
            <strong className="text-sworkr-600">Demo.</strong> Every client and number here is made up, and it's all
            reset to the sample data each night. Try anything, then share your feedback.
          </p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg bg-gray-50 px-3 py-2">
            <dt className="text-gray-500">Username</dt>
            <dd className="font-mono font-semibold text-gray-800 select-all break-all">{demoLogin.username}</dd>
            <dt className="text-gray-500">Password</dt>
            <dd className="font-mono font-semibold text-gray-800 select-all break-all">{demoLogin.password}</dd>
          </dl>
          <button
            type="button"
            onClick={() => { setUsername(demoLogin.username); setPassword(demoLogin.password); setError(''); }}
            className="mt-3 w-full py-2 rounded-lg border border-sworkr-300 text-sworkr-600 font-medium hover:bg-sworkr-50"
          >
            Fill in the demo login for me
          </button>
        </div>
      )}
    </div>
  );
}
