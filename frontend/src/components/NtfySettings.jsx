import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

const LEADS = [[0, 'No heads-up'], [15, '15 minutes before'], [30, '30 minutes before'], [60, 'An hour before'], [120, '2 hours before'], [240, '4 hours before']];
const HOURS = [['off', 'No daily summary'], ...Array.from({ length: 15 }, (_, i) => [String(i + 5), `${(i + 5) % 12 || 12}:00 ${i + 5 < 12 ? 'am' : 'pm'}`])];

/** A long random name for the topic your phone listens to: on the public server, anyone who guesses it can read it. */
function randomTopic() {
  const letters = 'abcdefghijkmnpqrstuvwxyz23456789';
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => letters[b % letters.length]).join('');
}

/** Settings → Notifications → Phone notifications: ntfy, a free app that shows a message when sworkr says so. */
export default function NtfySettings() {
  const [s, setS] = useState(null);
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState(null);
  const [working, setWorking] = useState('');

  useEffect(() => {
    axios.get('/api/ntfy/settings').then(({ data }) => {
      setS(data);
      setForm({
        enabled: data.enabled, server: data.server, topic: data.topic, token: '', clear_token: false, lead_minutes: data.lead_minutes,
        digest_hour: data.digest_hour == null ? 'off' : String(data.digest_hour), details: data.details,
      });
    }).catch((err) => setMessage({ error: errorMessage(err, 'Could not load notification settings') }));
  }, []);

  if (!form) return message?.error ? <p className="text-sm text-red-600">{message.error}</p> : null;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const body = () => ({
    ...form, lead_minutes: Number(form.lead_minutes), digest_hour: form.digest_hour === 'off' ? null : Number(form.digest_hour),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  });
  const run = async (what, fn) => {
    setWorking(what);
    setMessage(null);
    try { await fn(); } catch (err) { setMessage({ error: errorMessage(err, 'Something went wrong') }); } finally { setWorking(''); }
  };
  const save = (e) => {
    e.preventDefault();
    run('save', async () => {
      const { data } = await axios.put('/api/ntfy/settings', body());
      setS(data);
      setForm({ ...form, server: data.server, topic: data.topic, token: '', clear_token: false });
      setMessage({ ok: data.enabled ? 'Saved. Send a test to check your phone gets it.' : 'Saved. Notifications are off.' });
    });
  };
  const test = () => run('test', async () => {
    await axios.post('/api/ntfy/test');
    setMessage({ ok: 'Sent. It should show up on your phone in a moment.' });
  });
  const publicServer = (form.server || '').replace(/\/$/, '').endsWith('ntfy.sh');

  return (
    <form onSubmit={save} className="space-y-3">
      {s.demo && (
        <p className="rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-sm text-red-800" role="alert">
          <strong>This is a demo. Notifications are turned off here.</strong> Never enter real details in a demo.
        </p>
      )}
      <p className="text-sm text-gray-600">
        Get a message on your phone before a booking, and a short summary each morning, even when sworkr isn't open. It uses
        <b> ntfy</b>, a free app (iPhone and Android). Nothing is sent unless you turn this on.
      </p>
      <ol className="list-decimal pl-5 text-sm text-gray-700 space-y-1">
        <li>Install the <b>ntfy</b> app on your phone.</li>
        <li>Choose a topic below (the <i>Make one</i> button picks a good one), turn this on and save.</li>
        <li>In the app, tap <b>+</b> and subscribe to the same topic{publicServer ? '' : ' on your server'}. Then send a test.</li>
      </ol>

      <fieldset disabled={s.demo} className="space-y-3 disabled:opacity-60">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.enabled} onChange={set('enabled')} /> Send me notifications
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Server">
            <input value={form.server} onChange={set('server')} placeholder="https://ntfy.sh" autoComplete="off" className={inputClass} />
            {form.server !== 'https://ntfy.sh' && (
              <button type="button" onClick={() => setForm((f) => ({ ...f, server: 'https://ntfy.sh' }))}
                className="mt-1 text-xs px-2 py-0.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">Use ntfy.sh (public)</button>
            )}
          </Field>
          <Field label="Topic">
            <span className="flex gap-2">
              <input value={form.topic} onChange={set('topic')} placeholder="a long random name" autoComplete="off" spellCheck={false} className={inputClass} />
              <button type="button" onClick={() => setForm({ ...form, topic: randomTopic() })} className={`${quietButtonClass} whitespace-nowrap`}>Make one</button>
            </span>
          </Field>
        </div>
        <p className={`text-xs rounded-lg px-3 py-2 ${publicServer ? 'bg-amber-50 border border-amber-200 text-amber-900' : 'bg-gray-50 text-gray-600'}`}>
          {publicServer
            ? "On the public server (ntfy.sh), anyone who knows your topic can read what's sent to it. That's why it has to be long and random: keep it to yourself, and leave names out (below). For real privacy, run your own ntfy server and put its address here."
            : 'On your own server, a short topic is fine, and you can protect it with an access token.'}
        </p>
        <Field label={`Access token (only if your server asks for one)${s.has_token ? ': saved' : ''}`}>
          <input type="password" value={form.token} onChange={set('token')} autoComplete="new-password" placeholder={s.has_token ? 'Saved. Leave empty to keep it.' : ''} className={`${inputClass} max-w-md`} />
          {s.has_token && <label className="flex items-center gap-2 text-xs text-gray-600 mt-1"><input type="checkbox" checked={form.clear_token} onChange={set('clear_token')} /> Forget the saved token</label>}
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Before a booking">
            <select value={form.lead_minutes} onChange={set('lead_minutes')} className={inputClass}>
              {LEADS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Daily summary">
            <select value={form.digest_hour} onChange={set('digest_hour')} className={inputClass}>
              {HOURS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
        </div>
        <label className="flex items-start gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.details} onChange={set('details')} className="mt-1" />
          <span>Name clients in the messages <span className="text-xs text-gray-500">(otherwise it just says "A booking starts at 7:00 PM". Names pass through the ntfy server, so keep this off on the public one.)</span></span>
        </label>
        <p className="text-xs text-gray-500">
          The daily summary is counts: bookings today, tasks, posts to put up, deposits to collect, health tests, ads running out, inquiries to answer, late customs,
          shoots coming up, documents running out. It's only sent on days there's something in it.
        </p>
      </fieldset>

      {message?.error && <p className="text-sm text-red-600">{message.error}</p>}
      {message?.ok && <p className="text-sm text-emerald-600">{message.ok}</p>}
      {!s.demo && (
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={!!working} className={buttonClass}>{working === 'save' ? 'Saving…' : 'Save'}</button>
          <button type="button" onClick={test} disabled={!!working || !s.topic} className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            {working === 'test' ? 'Sending…' : 'Send a test'}
          </button>
        </div>
      )}
    </form>
  );
}
