import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass, Notice } from './Modal';
import { addPasskey, passkeyCancelled, passkeysSupported } from '../passkeys';

const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'never');

/** Passkeys: sign in with this device's own lock instead of a password. */
export function PasskeySettings() {
  const [keys, setKeys] = useState(null);
  const [name, setName] = useState('');
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { axios.get('/api/account/passkeys').then(({ data }) => setKeys(data)).catch(() => setKeys([])); }, []);
  useEffect(() => { load(); }, [load]);

  const add = async (e) => {
    e.preventDefault();
    setMessage(null);
    setBusy(true);
    try {
      const { name: saved } = await addPasskey(name.trim() || guessDevice());
      setName('');
      setMessage({ ok: `Added “${saved}”. Next time, choose “Log in with a passkey”.` });
      load();
    } catch (err) {
      if (!passkeyCancelled(err)) setMessage({ error: errorMessage(err, "The passkey couldn't be added") });
    } finally {
      setBusy(false);
    }
  };
  const remove = async (k) => {
    if (!window.confirm(`Remove the passkey “${k.name}”? Also delete it from that device's password manager.`)) return;
    await axios.delete(`/api/account/passkeys/${k.id}`).catch(() => {});
    load();
  };

  const here = window.location.hostname;
  return (
    <div className="space-y-3">
      {keys && keys.length > 0 && (
        <ul className="divide-y divide-gray-100">
          {keys.map((k) => (
            <li key={k.id} className="flex items-center gap-3 py-2 text-sm">
              <span className="flex-1">
                <span className="block text-gray-800">{k.name}</span>
                <span className="block text-xs text-gray-500">
                  For {k.rp_id}{k.rp_id !== here ? ' (another address)' : ''} · added {when(k.created_at)} · last used {when(k.last_used_at)}
                </span>
              </span>
              <button type="button" onClick={() => remove(k)} className="text-xs text-red-500 hover:text-red-700">Remove</button>
            </li>
          ))}
        </ul>
      )}
      {passkeysSupported() ? (
        <form onSubmit={add} className="flex flex-wrap gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={`Name it, e.g. ${guessDevice()}`} aria-label="Passkey name" className={`${inputClass} flex-1 min-w-40`} />
          <button type="submit" disabled={busy} className={buttonClass}>{busy ? 'Waiting for your device…' : 'Add a passkey on this device'}</button>
        </form>
      ) : (
        <p className="text-sm text-amber-800 bg-amber-50 rounded-lg px-3 py-2">
          This browser can't make passkeys here. They need a secure (https) address, or localhost on the computer sworkr runs on.
        </p>
      )}
      <Notice message={message} />
      <p className="text-xs text-gray-500">
        A passkey lives in this phone or computer (or its password manager) and opens with its face, fingerprint or PIN.
        Nobody can phish it, and it skips the emailed code. Each web address needs its own: a passkey made on {here} only
        works on {here}.
      </p>
    </div>
  );
}

function guessDevice() {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return 'iPhone';
  if (/iPad/.test(ua)) return 'iPad';
  if (/Android/.test(ua)) return 'Android phone';
  if (/Mac/.test(ua)) return 'Mac';
  if (/Windows/.test(ua)) return 'Windows computer';
  return 'This device';
}

/** Two-step sign-in: a code by email after the password. */
export function TwoStepSettings() {
  const [status, setStatus] = useState(null);
  const [address, setAddress] = useState('');
  const [pending, setPending] = useState(null);   // { challenge, sent_to }
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    axios.get('/api/account/two-step').then(({ data }) => { setStatus(data); setAddress(data.via === 'server' ? data.address || '' : ''); }).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (fn) => {
    setMessage(null);
    setBusy(true);
    try { await fn(); } catch (err) { setMessage({ error: errorMessage(err, 'Something went wrong') }); } finally { setBusy(false); }
  };
  const start = (e) => { e.preventDefault(); run(async () => { const { data } = await axios.post('/api/account/two-step/start', { address }); setPending(data); }); };
  const confirm = (e) => {
    e.preventDefault();
    run(async () => {
      await axios.post('/api/account/two-step/confirm', { challenge: pending.challenge, code });
      setPending(null);
      setCode('');
      setMessage({ ok: 'Two-step sign-in is on. Next time, sworkr will email you a code after your password.' });
      load();
    });
  };
  const off = (e) => {
    e.preventDefault();
    run(async () => {
      await axios.post('/api/account/two-step/off', { password });
      setPassword('');
      setMessage({ ok: 'Two-step sign-in is off.' });
      load();
    });
  };

  if (!status) return null;
  if (status.enabled) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-emerald-800 bg-emerald-50 rounded-lg px-3 py-2">
          On. After your password, a code goes to <strong>{status.address}</strong>
          {status.via === 'own' ? ', sent from your own connected email.' : '.'}
        </p>
        {status.passkeys === 0 && (
          <p className="text-sm text-amber-800 bg-amber-50 rounded-lg px-3 py-2">
            Add a passkey too: if your email ever stops working, it's how you'd still get in.
          </p>
        )}
        <form onSubmit={off} className="flex flex-wrap items-end gap-2">
          <Field label="Your password, to turn it off">
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
          </Field>
          <button type="submit" disabled={busy} className={quietButtonClass}>Turn off</button>
        </form>
        <Notice message={message} />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!status.via ? (
        <p className="text-sm text-gray-700">
          sworkr needs a way to send you codes first: <Link to="/account/connections#email" className="text-sworkr-600 hover:underline">connect your email</Link>{' '}
          (with its outgoing server), and codes will be sent from your own address to itself.
        </p>
      ) : !pending ? (
        <form onSubmit={start} className="space-y-2">
          {status.via === 'own' ? (
            <p className="text-sm text-gray-700">Codes will be sent from your connected email to itself: <strong>{status.address}</strong>.</p>
          ) : (
            <Field label="Send codes to">
              <input type="email" required value={address} onChange={(e) => setAddress(e.target.value)} placeholder="you@example.com" className={inputClass} />
            </Field>
          )}
          <button type="submit" disabled={busy} className={buttonClass}>{busy ? 'Sending…' : 'Send a test code'}</button>
        </form>
      ) : (
        <form onSubmit={confirm} className="space-y-2">
          <p className="text-sm text-gray-700">A code is on its way to <strong>{pending.sent_to}</strong>. Type it here to turn two-step sign-in on.</p>
          <div className="flex gap-2">
            <input required autoFocus inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code}
              onChange={(e) => setCode(e.target.value)} aria-label="Code" className={`${inputClass} w-40 text-center tracking-[0.3em]`} />
            <button type="submit" disabled={busy} className={buttonClass}>Turn on</button>
            <button type="button" onClick={() => setPending(null)} className={quietButtonClass}>Cancel</button>
          </div>
        </form>
      )}
      <Notice message={message} />
      <p className="text-xs text-gray-500">
        After your password, sworkr emails a 6-digit code and only lets you in once it's typed, so a stolen password isn't
        enough. The email just says “Sign-in code”.
      </p>
    </div>
  );
}
