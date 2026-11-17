import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';

const PROVIDERS = {
  nextcloud: {
    label: 'Nextcloud',
    address: 'https://cloud.example.com',
    username: 'Nextcloud username',
    help: (
      <>
        Use an <b>app password</b>, not your Nextcloud password: in Nextcloud, open Settings → Security → Devices &amp;
        sessions, type "sworkr" and press <i>Create new app password</i>. The address is the one you open Nextcloud at.
      </>
    ),
  },
  icloud: {
    label: 'iCloud (Apple)',
    address: 'https://caldav.icloud.com',
    username: 'Apple ID email',
    help: (
      <>
        Use an <b>app-specific password</b>, never your Apple ID password: sign in at account.apple.com → Sign-In and
        Security → App-Specific Passwords → add one called "sworkr". The address is <b>https://caldav.icloud.com</b>.
        Tasks can't go to iCloud: Apple's Reminders app doesn't accept them from other apps. Your bookings and tours will
        still sync.
      </>
    ),
  },
  other: {
    label: 'Other (CalDAV)',
    address: 'https://dav.example.com',
    username: 'Username',
    help: (
      <>
        Most calendar services that aren't Google speak CalDAV (Fastmail, Proton via its bridge, mailbox.org, a
        Synology or Radicale server…). Use the CalDAV address and an app password from that service.
      </>
    ),
  },
};

const guessProvider = (url) => (/icloud\.com/i.test(url || '') ? 'icloud' : url && !/cloud|nextcloud/i.test(url) ? 'other' : 'nextcloud');

/** Each person's own calendar sync: their bookings, tours, time off and tasks, copied into their calendar account. */
export default function CalendarSync() {
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState(null);
  const [provider, setProvider] = useState('nextcloud');
  const [message, setMessage] = useState(null);
  const [working, setWorking] = useState('');

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/calendar-sync');
      setStatus(data);
      setForm((f) => {
        if (f) return f;
        setProvider(guessProvider(data.url));
        return { url: data.url, username: data.username, app_password: '', enabled: data.enabled, discreet: data.discreet,
                 events_name: data.events_name, tasks_name: data.tasks_name };
      });
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not load calendar sync') });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // While a sync is running, check back every couple of seconds.
  useEffect(() => {
    if (!status?.busy) return undefined;
    const id = setTimeout(load, 2000);
    return () => clearTimeout(id);
  }, [status, load]);

  if (!form) return message?.error ? <p className="text-sm text-red-600">{message.error}</p> : null;

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const p = PROVIDERS[provider];
  const demo = status.demo;

  const run = async (what, fn) => {
    setWorking(what);
    setMessage(null);
    try {
      await fn();
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Something went wrong') });
    } finally {
      setWorking('');
    }
  };
  const test = () => run('test', async () => {
    const { data } = await axios.post('/api/calendar-sync/test', form);
    setMessage({ ok: `Connected. Found your calendars at ${data.calendar_home}` });
  });
  const save = (e) => {
    e.preventDefault();
    run('save', async () => {
      const { data } = await axios.put('/api/calendar-sync', form);
      setStatus(data);
      setForm({ ...form, url: data.url, app_password: '', events_name: data.events_name, tasks_name: data.tasks_name });
      setMessage({ ok: data.enabled ? 'Saved. Syncing now…' : 'Saved. Calendar sync is off.' });
    });
  };
  const syncNow = () => run('sync', async () => {
    await axios.post('/api/calendar-sync/sync');
    setStatus((s) => ({ ...s, busy: true }));
  });
  const saved = status.enabled && status.url;

  return (
    <div className="space-y-4">
      {demo && (
        <p className="rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-sm text-red-800" role="alert">
          <strong>This is a demo. Don't connect a real calendar account here.</strong> Other people use this demo login and
          could see the address and username. Calendar sync is switched off in the demo; here's how it works in your own copy.
        </p>
      )}

      <div className="text-sm text-gray-600 space-y-2">
        <p>
          Copies your bookings, tours, time off and tasks into a calendar called <b>sworkr</b> (and a task list called
          <b> sworkr tasks</b>) in your own calendar account, so they show on your phone. It goes one way: edits made in
          the calendar app are replaced at the next sync.
        </p>
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-900">
          <b>Nextcloud is the privacy-focused choice.</b> It runs on a server you (or someone you trust) control, so your
          schedule never sits with Apple or Google. With iCloud, Apple holds a copy; turn on <i>Discreet entries</i> below
          so it only ever sees "Appointment".
        </p>
      </div>

      <form onSubmit={save} className="space-y-3">
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Calendar account">
          {Object.entries(PROVIDERS).map(([key, x]) => (
            <button key={key} type="button" role="radio" aria-checked={provider === key} onClick={() => setProvider(key)}
              className={`px-3 py-1.5 rounded-full text-sm border ${provider === key ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
              {x.label}{key === 'nextcloud' && ' (recommended)'}
            </button>
          ))}
        </div>

        <fieldset disabled={demo} className="space-y-3 disabled:opacity-60">
          <Field label="Address">
            <input value={form.url} onChange={set('url')} placeholder={p.address} className={inputClass} />
          </Field>
          <Field label={p.username}>
            <input value={form.username} onChange={set('username')} autoComplete="off" className={inputClass} />
          </Field>
          <Field label="App password">
            <input type="password" value={form.app_password} onChange={set('app_password')} autoComplete="new-password"
              placeholder={status.has_password ? 'Saved. Leave empty to keep it.' : ''} className={inputClass} />
          </Field>
          <p className="text-xs text-gray-500 -mt-1">{p.help}</p>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.enabled} onChange={set('enabled')} />
            Sync to this account
          </label>
          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input type="checkbox" className="mt-1" checked={form.discreet} onChange={set('discreet')} />
            <span>
              Discreet entries
              <span className="block text-xs text-gray-400">
                Bookings just say "Appointment", tours say "Away" and tasks say "Task", with no names, places or notes.
                Recommended for iCloud, and if your calendar shows on a phone lock screen.
              </span>
            </span>
          </label>
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Calendar name">
              <input value={form.events_name ?? ''} onChange={set('events_name')} maxLength={60} placeholder="sworkr" className={inputClass} />
            </Field>
            <Field label="Task list name">
              <input value={form.tasks_name ?? ''} onChange={set('tasks_name')} maxLength={60} placeholder="sworkr tasks" className={inputClass} />
            </Field>
          </div>
          <p className="text-xs text-gray-400 -mt-1">
            What they're called in your calendar app, e.g. "Work" and "To do" so the name doesn't stand out. Changing it
            renames them at the next sync; what's already in them stays.
          </p>
        </fieldset>

        {message?.error && <p className="text-sm text-red-600">{message.error}</p>}
        {message?.ok && <p className="text-sm text-emerald-600">{message.ok}</p>}

        {!demo && (
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={!!working} className="px-5 py-2 bg-sworkr-500 text-white rounded-full hover:bg-sworkr-600 disabled:opacity-50 text-sm">
              {working === 'save' ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={test} disabled={!!working} className="px-4 py-2 border border-gray-200 rounded-full text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
              {working === 'test' ? 'Testing…' : 'Test connection'}
            </button>
            {saved && (
              <button type="button" onClick={syncNow} disabled={!!working || status.busy} className="px-4 py-2 border border-gray-200 rounded-full text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                Sync now
              </button>
            )}
          </div>
        )}

        {saved && (
          <div className="text-xs text-gray-500 space-y-1">
            <p>{status.busy ? 'Syncing…' : status.last_sync_at ? `Last synced ${new Date(status.last_sync_at).toLocaleString()}` : 'Not synced yet'}</p>
            {status.tasks_supported === false && <p>Tasks aren't synced: this account doesn't accept task lists from other apps.</p>}
            {status.last_error && (
              <p className="text-red-600">
                Last problem{status.last_error_at && ` (${new Date(status.last_error_at).toLocaleString()})`}: {status.last_error}
              </p>
            )}
          </div>
        )}
      </form>

      <details className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600">
        <summary className="cursor-pointer font-medium text-gray-700">Google Calendar</summary>
        <div className="mt-2 space-y-2">
          <p>
            Google doesn't let apps write to Google Calendar with an app password: it needs a Google developer
            account and Google's own sign-in setup, which sworkr deliberately avoids. So there's no direct Google sync,
            and keeping your schedule out of your Google account is better for your privacy anyway.
          </p>
          <p>To still see your sworkr calendar in the Google Calendar app on Android:</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Sync sworkr to Nextcloud (above).</li>
            <li>Install <b>DAVx⁵</b> (free on F-Droid, paid on the Play Store) and add your Nextcloud account in it (address, username, app password).</li>
            <li>In DAVx⁵, tick the <b>sworkr</b> calendar (and <b>sworkr tasks</b>, with the free Tasks.org or jtx Board app for tasks).</li>
            <li>Open Google Calendar: the sworkr calendar appears there, stored on your phone and in Nextcloud, not in your Google account.</li>
          </ol>
        </div>
      </details>

      <details className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600">
        <summary className="cursor-pointer font-medium text-gray-700">iPhone and iPad (CalDAV)</summary>
        <div className="mt-2 space-y-2">
          <p>If you sync to iCloud, the sworkr calendar is already on your Apple devices. If you sync to Nextcloud, add it to your iPhone once:</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Open <b>Settings → Apps → Calendar → Calendar Accounts → Add Account → Other → Add CalDAV Account</b> (on older iOS: Settings → Calendar → Accounts).</li>
            <li>Server: your Nextcloud address. User name: your Nextcloud username. Password: a Nextcloud app password (make a separate one for the phone).</li>
            <li>Tap Next. The <b>sworkr</b> calendar shows in the Calendar app, and <b>sworkr tasks</b> in the Reminders app.</li>
          </ol>
          <p>On a Mac: Calendar → Settings → Accounts → + → Other CalDAV Account, with the same details.</p>
        </div>
      </details>
    </div>
  );
}
