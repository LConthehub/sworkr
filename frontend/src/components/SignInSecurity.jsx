import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass, Notice } from './Modal';
import { addPasskey, passkeyCancelled, passkeysSupported } from '../passkeys';

const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'never');
const whenExactly = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '');

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
    setMessage(null);
    try {
      await axios.delete(`/api/account/passkeys/${k.id}`);
    } catch (err) {
      setMessage({ error: errorMessage(err, "The passkey couldn't be removed") });
    }
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
        Nobody can phish it, and it skips the two-step code. Each web address needs its own: a passkey made on {here} only
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

/** Recovery codes, shown once: to print or copy before leaving the page. */
function RecoveryCodes({ codes, onDone }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(codes.join('\n')); setCopied(true); } catch { /* select and copy by hand */ }
  };
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
      <p className="text-sm text-amber-900">
        <strong>Save these recovery codes now.</strong> Each one works once in place of a sign-in code, for the day your
        phone or email is gone. They won't be shown again. Keep them on paper or in a password manager, not in a note
        called “sworkr”.
      </p>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-sm text-gray-800 select-all">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={copy} className={quietButtonClass}>{copied ? 'Copied' : 'Copy'}</button>
        <button type="button" onClick={() => window.print()} className={quietButtonClass}>Print</button>
        <button type="button" onClick={onDone} className={buttonClass}>I've saved them</button>
      </div>
    </div>
  );
}

const codeInput = `${inputClass} w-40 text-center tracking-[0.3em]`;

/** Two-step sign-in: after the password, a code from an authenticator app or by email. */
export function TwoStepSettings() {
  const [status, setStatus] = useState(null);
  const [method, setMethod] = useState('app');
  const [address, setAddress] = useState('');
  const [label, setLabel] = useState('');
  const [pending, setPending] = useState(null);   // email: { challenge, sent_to }; app: { challenge, secret, uri, qr }
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [codes, setCodes] = useState(null);       // recovery codes just made
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
  const start = (e) => {
    e.preventDefault();
    run(async () => {
      const { data } = method === 'app'
        ? await axios.post('/api/account/two-step/app/start', { label })
        : await axios.post('/api/account/two-step/start', { address });
      setPending({ ...data, method });
    });
  };
  const confirm = (e) => {
    e.preventDefault();
    run(async () => {
      const url = pending.method === 'app' ? '/api/account/two-step/app/confirm' : '/api/account/two-step/confirm';
      const { data } = await axios.post(url, { challenge: pending.challenge, code });
      setPending(null);
      setCode('');
      setCodes(data.recovery_codes || null);
      setMessage({ ok: 'Two-step sign-in is on.' });
      load();
    });
  };
  const off = () => run(async () => {
    await axios.post('/api/account/two-step/off', { password });
    setPassword('');
    setMessage({ ok: 'Two-step sign-in is off.' });
    load();
  });
  const newCodes = () => run(async () => {
    const { data } = await axios.post('/api/account/recovery-codes', { password });
    setPassword('');
    setCodes(data.recovery_codes);
    load();
  });

  if (!status) return null;
  if (codes) return <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />;

  if (status.enabled) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-emerald-800 bg-emerald-50 rounded-lg px-3 py-2">
          {status.method === 'app'
            ? <>On. After your password, sworkr asks for the code from your authenticator app.</>
            : <>On. After your password, a code goes to <strong>{status.address}</strong>{status.via === 'own' ? ', sent from your own connected email.' : '.'}</>}
        </p>
        <p className={`text-sm rounded-lg px-3 py-2 ${status.recovery_codes > 2 ? 'text-gray-700 bg-gray-50' : 'text-amber-800 bg-amber-50'}`}>
          {status.recovery_codes === 0
            ? 'You have no recovery codes left. Make new ones below, so losing your phone or email never locks you out.'
            : `${status.recovery_codes} recovery ${status.recovery_codes === 1 ? 'code' : 'codes'} left.`}
        </p>
        <form onSubmit={(e) => e.preventDefault()} className="flex flex-wrap items-end gap-2">
          <Field label="Your password, to change any of this">
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
          </Field>
          <button type="button" disabled={busy || !password} onClick={newCodes} className={quietButtonClass}>Make new recovery codes</button>
          <button type="button" disabled={busy || !password} onClick={off} className={quietButtonClass}>Turn two-step off</button>
        </form>
        <Notice message={message} />
        <p className="text-xs text-gray-500">To switch between the app and email, turn two-step off, then on again.</p>
      </div>
    );
  }

  const emailReady = !!status.via;
  return (
    <div className="space-y-3">
      {!pending && (
        <form onSubmit={start} className="space-y-3">
          <fieldset className="space-y-2">
            <label className="flex items-start gap-2 text-sm text-gray-700">
              <input type="radio" name="two-step-method" checked={method === 'app'} onChange={() => setMethod('app')} className="mt-1" />
              <span><strong>Authenticator app</strong> (recommended). Codes come from an app on your phone. Works without email or signal.</span>
            </label>
            <label className="flex items-start gap-2 text-sm text-gray-700">
              <input type="radio" name="two-step-method" checked={method === 'email'} onChange={() => setMethod('email')} className="mt-1" />
              <span><strong>Email.</strong> sworkr emails you a code each time.</span>
            </label>
          </fieldset>
          {method === 'app' && (
            <Field label="What to call it in the app (optional; leave it plain if someone might see your phone)">
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Sign-in" maxLength={30} className={inputClass} />
            </Field>
          )}
          {method === 'email' && !emailReady && (
            <p className="text-sm text-gray-700">
              sworkr needs a way to send you codes first: <Link to="/account/connections#email" className="text-sworkr-600 hover:underline">connect your email</Link>{' '}
              (with its outgoing server), and codes will be sent from your own address to itself.
            </p>
          )}
          {method === 'email' && emailReady && (status.via === 'own' ? (
            <p className="text-sm text-gray-700">Codes will be sent from your connected email to itself: <strong>{status.address}</strong>.</p>
          ) : (
            <Field label="Send codes to">
              <input type="email" required value={address} onChange={(e) => setAddress(e.target.value)} placeholder="you@example.com" className={inputClass} />
            </Field>
          ))}
          {(method === 'app' || emailReady) && (
            <button type="submit" disabled={busy} className={buttonClass}>
              {method === 'app' ? 'Set up the app' : busy ? 'Sending…' : 'Send a test code'}
            </button>
          )}
        </form>
      )}
      {pending && (
        <form onSubmit={confirm} className="space-y-3">
          {pending.method === 'app' ? (
            <>
              <p className="text-sm text-gray-700">
                In your authenticator app, add an account and scan this code. On this phone, <a href={pending.uri} className="text-sworkr-600 hover:underline">open it in the app</a> instead.
              </p>
              {pending.qr && <img src={pending.qr} alt="QR code for your authenticator app" className="w-44 h-44 rounded-lg border border-gray-200 bg-white" />}
              <p className="text-sm text-gray-700">
                Can't scan? Type this key into the app: <span className="font-mono text-gray-900 select-all break-all">{pending.secret}</span>
              </p>
              <p className="text-sm text-gray-700">Then type the 6-digit code the app shows.</p>
            </>
          ) : (
            <p className="text-sm text-gray-700">A code is on its way to <strong>{pending.sent_to}</strong>. Type it here to turn two-step sign-in on.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <input required autoFocus inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code}
              onChange={(e) => setCode(e.target.value)} aria-label="Code" className={codeInput} />
            <button type="submit" disabled={busy} className={buttonClass}>Turn on</button>
            <button type="button" onClick={() => { setPending(null); setCode(''); }} className={quietButtonClass}>Cancel</button>
          </div>
        </form>
      )}
      <Notice message={message} />
      <p className="text-xs text-gray-500">
        After your password, sworkr only lets you in once the code is typed, so a stolen password isn't enough. You'll
        also get recovery codes to keep on paper.
      </p>
    </div>
  );
}

/** Passkeys only away from home, and emails about new sign-ins. */
export function AwayFromHome() {
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState(null);
  useEffect(() => { axios.get('/api/account/access').then(({ data }) => setStatus(data)).catch(() => {}); }, []);

  const save = async (change, ok) => {
    setMessage(null);
    try {
      const { data } = await axios.put('/api/account/access', change);
      setStatus(data);
      setMessage({ ok });
    } catch (err) {
      setMessage({ error: errorMessage(err, "That couldn't be saved") });
    }
  };

  if (!status) return null;
  return (
    <div className="space-y-4">
      <label className="flex items-start gap-3 text-sm text-gray-700">
        <input type="checkbox" checked={status.passkey_only} className="mt-1"
          onChange={(e) => save({ passkey_only: e.target.checked }, e.target.checked
            ? 'On. From the internet, only a passkey signs you in now.'
            : 'Off. Your password works everywhere again.')} />
        <span>
          <strong>Passkeys only away from home.</strong> Turns your password off for anyone reaching sworkr over the
          internet: only a passkey gets in there. Your password still works on the computer sworkr runs on and on your
          home network, so a lost phone can't lock you out.
          {status.remote_passkeys === 0 && ' First add a passkey while you have sworkr open at its public address.'}
        </span>
      </label>
      <label className="flex items-start gap-3 text-sm text-gray-700">
        <input type="checkbox" checked={status.alerts} className="mt-1"
          onChange={(e) => save({ alerts: e.target.checked }, e.target.checked ? 'On.' : 'Off.')} />
        <span>
          <strong>Email me about new sign-ins.</strong> When a browser that hasn't signed in to your account before does.
          {status.alerts_address
            ? <> Goes to {status.alerts_address}. The email just says “New sign-in”.</>
            : <> sworkr has no way to email you yet: <Link to="/account/connections#email" className="text-sworkr-600 hover:underline">connect your email</Link> first.</>}
        </span>
      </label>
      <Notice message={message} />
      <p className={`text-xs rounded-lg px-3 py-2 ${status.local ? 'bg-gray-50 text-gray-600' : 'bg-sky-50 text-sky-800'}`}>
        Right now sworkr sees you as <strong>{status.local ? 'at home' : 'on the internet'}</strong> (address {status.ip}).
        {status.local && ' If you are in fact away from home, whatever sits in front of sworkr isn’t passing visitors’ addresses on, and this setting can’t protect you until it does.'}
      </p>
    </div>
  );
}

const METHODS = { password: 'password', code: 'emailed code', app: 'app code', passkey: 'passkey', recovery: 'recovery code' };
const OUTCOMES = {
  ok: null,
  wrong_password: 'Wrong password',
  wrong_code: 'Wrong code',
  password_off: 'Password refused (passkeys only)',
  decoy: 'The decoy password was used',
};

/** Where this account is signed in, and what has happened at the front door lately. */
export function SignedInDevices() {
  const [sessions, setSessions] = useState(null);
  const [events, setEvents] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [message, setMessage] = useState(null);
  const load = useCallback(() => {
    axios.get('/api/account/sessions').then(({ data }) => setSessions(data)).catch(() => setSessions([]));
    axios.get('/api/account/sign-ins').then(({ data }) => setEvents(data)).catch(() => setEvents([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const end = async (s) => {
    await axios.delete(`/api/account/sessions/${s.id}`).catch(() => {});
    load();
  };
  const endOthers = async () => {
    setMessage(null);
    try {
      const { data } = await axios.post('/api/account/sessions/log-out-others');
      setMessage({ ok: data.logged_out ? `Logged out ${data.logged_out} other ${data.logged_out === 1 ? 'device' : 'devices'}.` : 'No other devices were signed in.' });
    } catch (err) {
      setMessage({ error: errorMessage(err, "That didn't work") });
    }
    load();
  };

  if (!sessions || !events) return null;
  const shown = showAll ? events : events.slice(0, 8);
  return (
    <div className="space-y-4">
      <ul className="divide-y divide-gray-100">
        {sessions.map((s) => (
          <li key={s.id} className="flex items-center gap-3 py-2 text-sm">
            <span className="flex-1">
              <span className="block text-gray-800">
                {s.device}{s.current && <span className="ml-2 text-xs text-emerald-700 bg-emerald-50 rounded px-1.5 py-0.5">this device</span>}
              </span>
              <span className="block text-xs text-gray-500">
                {s.ip ? `${s.ip} · ` : ''}signed in {whenExactly(s.created_at)}{s.method ? ` with a ${METHODS[s.method] || s.method}` : ''} · last used {whenExactly(s.last_seen_at)}
              </span>
            </span>
            {!s.current && <button type="button" onClick={() => end(s)} className="text-xs text-red-500 hover:text-red-700">Log out</button>}
          </li>
        ))}
      </ul>
      {sessions.length > 1 && <button type="button" onClick={endOthers} className={quietButtonClass}>Log out every other device</button>}
      <Notice message={message} />

      <div>
        <h3 className="text-sm font-medium text-gray-700">Recent sign-ins</h3>
        {events.length === 0 ? (
          <p className="text-sm text-gray-500 mt-1">Nothing yet. Sign-ins from now on are listed here for 90 days.</p>
        ) : (
          <ul className="mt-1 divide-y divide-gray-100">
            {shown.map((ev) => (
              <li key={ev.id} className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-sm">
                <span className="w-32 shrink-0 text-xs text-gray-500">{whenExactly(ev.at)}</span>
                <span className={`flex-1 ${OUTCOMES[ev.outcome] ? 'text-red-700' : 'text-gray-800'}`}>
                  {OUTCOMES[ev.outcome] || `Signed in with a ${METHODS[ev.method] || ev.method || 'password'}`}
                </span>
                <span className="text-xs text-gray-500">{ev.device}{ev.ip ? ` · ${ev.ip}` : ''}</span>
              </li>
            ))}
          </ul>
        )}
        {events.length > 8 && (
          <button type="button" onClick={() => setShowAll(!showAll)} className="mt-1 text-xs text-sworkr-600 hover:underline">
            {showAll ? 'Show fewer' : `Show all ${events.length}`}
          </button>
        )}
      </div>
      <p className="text-xs text-gray-500">
        See something that wasn't you? Change your password (that logs every other device out), then check your passkeys.
      </p>
    </div>
  );
}
