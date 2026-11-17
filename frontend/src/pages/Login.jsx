import { useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from '../components/Modal';
import { passkeyCancelled, passkeysSupported, signInWithPasskey } from '../passkeys';
import { readDiscreet } from '../components/Discreet';

/**
 * Shown when not logged in. With `setup`, it creates the first account instead.
 * `passkeyHint`: passwords may be turned off from this address, so the page points at the passkey button.
 * On the demo copy, `demoLogin` ({ username, password }) is shown under the form with a button to fill it in.
 */
export default function Login({ setup, demoLogin, passkeyHint, onLoggedIn }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [twoStep, setTwoStep] = useState(null);   // { challenge, method, sent_to } while waiting for the code
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState(false);   // typing a recovery code instead
  const [info, setInfo] = useState('');
  const discreet = readDiscreet();

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (setup && password !== confirm) return setError("Passwords don't match");
    setBusy(true);
    try {
      const { data } = await axios.post(setup ? '/api/auth/setup' : '/api/auth/login', { username, password });
      if (data.two_step) {
        setTwoStep(data);
        setPassword('');
      } else {
        onLoggedIn(data);
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not log in'));
    } finally {
      setBusy(false);
    }
  };

  const sendCode = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const { data } = await axios.post('/api/auth/login/code', { challenge: twoStep.challenge, code });
      onLoggedIn(data);
    } catch (err) {
      setError(errorMessage(err, "That code didn't work"));
      if (/run out|Start again/.test(err?.response?.data?.detail || '')) { setTwoStep(null); setRecovery(false); setCode(''); }
    } finally {
      setBusy(false);
    }
  };
  const resend = async () => {
    setError('');
    setInfo('');
    try {
      const { data } = await axios.post('/api/auth/login/code/resend', { challenge: twoStep.challenge });
      setInfo(`A new code is on its way to ${data.sent_to}.`);
    } catch (err) {
      setError(errorMessage(err, "Couldn't send another code"));
    }
  };
  const passkey = async () => {
    setError('');
    setBusy(true);
    try {
      onLoggedIn(await signInWithPasskey());
    } catch (err) {
      if (!passkeyCancelled(err)) setError(errorMessage(err, "The passkey didn't work"));
    } finally {
      setBusy(false);
    }
  };

  // In discreet mode the card doesn't say "Sworkr" either.
  const header = (
    <div className="flex items-center gap-3 mb-2">
      {!discreet.enabled && <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-sworkr-500 to-sworkr-800 flex items-center justify-center text-white font-bold text-xl">SW</div>}
      <div>
        <h1 className="font-bold text-gray-800 text-lg">{discreet.enabled ? (discreet.title || 'Notes') : 'Sworkr'}</h1>
        <p className="text-xs text-gray-500">{setup ? 'Create your account to get started' : twoStep ? (recovery ? 'Use a recovery code' : twoStep.method === 'app' ? 'Open your authenticator app' : 'Check your email') : 'Log in to continue'}</p>
      </div>
    </div>
  );

  if (twoStep) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3 px-4 py-8">
        <form onSubmit={sendCode} className="w-full max-w-sm bg-white rounded-2xl shadow-xl p-6 space-y-4">
          {header}
          {recovery ? (
            <>
              <p className="text-sm text-gray-700">Type one of the recovery codes you saved. Each works once.</p>
              <Field label="Recovery code">
                <input key="recovery" required autoFocus autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={14}
                  value={code} onChange={(e) => setCode(e.target.value)} className={`${inputClass} text-xl tracking-widest text-center font-mono`} />
              </Field>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-700">
                {twoStep.method === 'app'
                  ? 'Type the 6-digit code your authenticator app shows.'
                  : <>We sent a 6-digit code to <strong>{twoStep.sent_to}</strong>. It works for 10 minutes.</>}
              </p>
              <Field label="Code">
                <input key="code" required autoFocus inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]*" maxLength={7}
                  value={code} onChange={(e) => setCode(e.target.value)} className={`${inputClass} text-2xl tracking-[0.4em] text-center`} />
              </Field>
            </>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          {info && <p className="text-sm text-emerald-700">{info}</p>}
          <button type="submit" disabled={busy} className="w-full py-2.5 rounded-full bg-gradient-to-br from-sworkr-500 to-sworkr-600 text-white font-bold hover:brightness-105 hover:shadow-[0_6px_18px_rgba(167,49,120,0.25)] disabled:opacity-50">
            {busy ? 'Checking…' : 'Log in'}
          </button>
          <div className="flex justify-between text-sm">
            {!recovery && twoStep.method !== 'app' && <button type="button" onClick={resend} className="text-sworkr-600 hover:text-sworkr-800">Send a new code</button>}
            <button type="button" onClick={() => { setRecovery(!recovery); setCode(''); setError(''); setInfo(''); }} className="text-sworkr-600 hover:text-sworkr-800">
              {recovery ? 'Use a code instead' : 'Use a recovery code'}
            </button>
            <button type="button" onClick={() => { setTwoStep(null); setRecovery(false); setCode(''); setError(''); setInfo(''); }} className="text-gray-500 hover:text-gray-700">Start over</button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 px-4 py-8">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl shadow-xl p-6 space-y-4">
        {header}

        <Field label="Username">
          <input required autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Password">
          <input
            required
            type="password"
            autoComplete={setup ? 'new-password' : 'current-password'}
            minLength={setup ? 12 : undefined}
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
            <p className="text-xs text-gray-400">At least 12 characters: a few words strung together works well. Keep it somewhere safe.</p>
          </>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
        {passkeyHint && !setup && (
          <p className="text-xs text-gray-500">Away from home? Passwords may be turned off here. Use your passkey.</p>
        )}

        <button type="submit" disabled={busy} className="w-full py-2.5 rounded-full bg-gradient-to-br from-sworkr-500 to-sworkr-600 text-white font-bold hover:brightness-105 hover:shadow-[0_6px_18px_rgba(167,49,120,0.25)] disabled:opacity-50">
          {busy ? 'Please wait…' : setup ? 'Create account' : 'Log in'}
        </button>
        {!setup && !demoLogin && passkeysSupported() && (
          <button type="button" onClick={passkey} disabled={busy}
            className="w-full py-2.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50 font-medium">
            Log in with a passkey
          </button>
        )}
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
