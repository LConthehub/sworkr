import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';

const HELP = {
  gmail: <>Turn on 2-Step Verification in your Google account, then make an <b>app password</b> at myaccount.google.com → Security → App passwords. Use your full Gmail address as the username.</>,
  icloud: <>Make an <b>app-specific password</b> at account.apple.com → Sign-In and Security → App-Specific Passwords. The username is your iCloud email address (…@icloud.com).</>,
  fastmail: <>Make an <b>app password</b> in Fastmail → Settings → Privacy &amp; Security → App passwords, with access to IMAP and SMTP.</>,
  yahoo: <>Make an <b>app password</b> in Yahoo → Account Security → Generate app password.</>,
  proton: <>Proton Mail only works through the <b>Proton Mail Bridge</b> app running on the same computer as sworkr. Use the username and password the Bridge shows you.</>,
  other: <>Your email provider's help pages list its IMAP (incoming) and SMTP (outgoing) servers. Use an app password if it offers them. Outlook.com and Hotmail no longer allow app passwords, so they can't be connected this way.</>,
};

/** Each person's own email account: read over IMAP, reply over SMTP. */
function EmailAccountForm({ account, onChanged }) {
  const [s, setS] = useState(null);
  const [form, setForm] = useState(null);
  const [provider, setProvider] = useState('other');
  const [message, setMessage] = useState(null);
  const [working, setWorking] = useState('');

  useEffect(() => {
    axios.get('/api/mail/settings', { params: { account } }).then(({ data }) => {
      setS(data);
      const match = Object.entries(data.providers).find(([, p]) => p.imap_host && p.imap_host === data.imap_host);
      setProvider(match ? match[0] : data.imap_host ? 'other' : 'gmail');
      setForm({
        enabled: data.enabled, imap_host: data.imap_host || '', imap_port: data.imap_port, imap_security: data.imap_security,
        smtp_host: data.smtp_host || '', smtp_port: data.smtp_port, smtp_security: data.smtp_security,
        username: data.username || '', password: '', from_name: data.from_name || '', from_address: data.from_address || '',
        folder: data.folder || 'INBOX', label: data.label || '',
      });
      if (!data.imap_host) {
        const p = data.providers.gmail;
        setForm((f) => ({ ...f, ...pick(p) }));
      }
    }).catch((err) => setMessage({ error: errorMessage(err, 'Could not load your email settings') }));
  }, [account]);

  if (!form) return message?.error ? <p className="text-sm text-red-600">{message.error}</p> : null;

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const choose = (key) => {
    setProvider(key);
    setForm({ ...form, ...pick(s.providers[key]) });
  };
  const body = () => ({ ...form, imap_port: Number(form.imap_port), smtp_port: Number(form.smtp_port), from_address: form.from_address || null });
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
    const { data } = await axios.post('/api/mail/test', body(), { params: { account } });
    setMessage({ ok: `Connected. ${data.unread} unread email${data.unread === 1 ? '' : 's'} in your inbox.` });
  });
  const save = (e) => {
    e.preventDefault();
    run('save', async () => {
      const { data } = await axios.put('/api/mail/settings', body(), { params: { account } });
      setS(data);
      setForm({ ...form, password: '' });
      onChanged?.();
      setMessage({ ok: data.enabled ? 'Saved. Your email shows on the dashboard.' : 'Saved. Email is off.' });
    });
  };

  return (
    <div className="space-y-4">
      {s.demo && (
        <p className="rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-sm text-red-800" role="alert">
          <strong>This is a demo. Don't connect a real email account here.</strong> Other people use this demo login.
          The dashboard shows a made-up inbox instead, and replies aren't sent anywhere.
        </p>
      )}
      <Field label="What to call this account (optional)">
        <input value={form.label} onChange={set('label')} maxLength={40} placeholder="e.g. Work, Personal, a persona's name" className={`${inputClass} max-w-xs`} />
      </Field>
      <p className="text-sm text-gray-600">
        Shows your unread and important (flagged or starred) emails on the dashboard, so you can reply and add senders as
        contacts. Emails are read straight from your mail server and are never stored in sworkr. They're shown as plain
        text only, so nothing in an email can run or track you.
      </p>

      <form onSubmit={save} className="space-y-3">
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Email provider">
          {Object.entries(s.providers).map(([key, p]) => (
            <button key={key} type="button" role="radio" aria-checked={provider === key} onClick={() => choose(key)} disabled={s.demo}
              className={`px-3 py-1.5 rounded-full text-sm border ${provider === key ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
              {p.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500">{HELP[provider]}</p>

        <fieldset disabled={s.demo} className="space-y-3 disabled:opacity-60">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Username (usually your email address)">
              <input value={form.username} onChange={set('username')} autoComplete="off" className={inputClass} />
            </Field>
            <Field label="App password">
              <input type="password" value={form.password} onChange={set('password')} autoComplete="new-password"
                placeholder={s.has_password ? 'Saved. Leave empty to keep it.' : ''} className={inputClass} />
            </Field>
            <Field label="Your name on replies (optional)">
              <input value={form.from_name} onChange={set('from_name')} placeholder="e.g. your working name" className={inputClass} />
            </Field>
            <Field label="Send from (if not the username)">
              <input type="email" value={form.from_address} onChange={set('from_address')} className={inputClass} />
            </Field>
          </div>

          <details className="rounded-lg border border-gray-200 px-3 py-2" open={provider === 'other'}>
            <summary className="cursor-pointer text-sm font-medium text-gray-700">Servers</summary>
            <div className="grid grid-cols-[1fr_5rem_7rem] gap-2 mt-2">
              <Field label="Incoming (IMAP)"><input value={form.imap_host} onChange={set('imap_host')} placeholder="imap.example.com" className={inputClass} /></Field>
              <Field label="Port"><input type="number" value={form.imap_port} onChange={set('imap_port')} className={inputClass} /></Field>
              <Field label="Security">
                <select value={form.imap_security} onChange={set('imap_security')} className={inputClass}>
                  <option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option><option value="none">None</option>
                </select>
              </Field>
              <Field label="Outgoing (SMTP)"><input value={form.smtp_host} onChange={set('smtp_host')} placeholder="smtp.example.com" className={inputClass} /></Field>
              <Field label="Port"><input type="number" value={form.smtp_port} onChange={set('smtp_port')} className={inputClass} /></Field>
              <Field label="Security">
                <select value={form.smtp_security} onChange={set('smtp_security')} className={inputClass}>
                  <option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option><option value="none">None</option>
                </select>
              </Field>
            </div>
            <Field label="Folder to show">
              <input value={form.folder} onChange={set('folder')} className={`${inputClass} mt-1`} />
            </Field>
          </details>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.enabled} onChange={set('enabled')} /> Show my email on the dashboard
          </label>
        </fieldset>

        {message?.error && <p className="text-sm text-red-600">{message.error}</p>}
        {message?.ok && <p className="text-sm text-emerald-600">{message.ok}</p>}

        {!s.demo && (
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={!!working} className="px-5 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50 text-sm">
              {working === 'save' ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={test} disabled={!!working} className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
              {working === 'test' ? 'Testing…' : 'Test connection'}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}

function pick(p) {
  return {
    imap_host: p.imap_host, imap_port: p.imap_port, imap_security: p.imap_security,
    smtp_host: p.smtp_host, smtp_port: p.smtp_port, smtp_security: p.smtp_security,
  };
}

/** Email accounts: up to five, each with its own servers and app password. */
export default function EmailSettings() {
  const [list, setList] = useState(null);
  const [account, setAccount] = useState(1);
  const load = () => axios.get('/api/mail/accounts').then(({ data }) => { setList(data); return data; }).catch(() => setList({ accounts: [], next: null }));
  useEffect(() => { load(); }, []);
  if (!list) return null;
  const tabs = list.accounts.some((a) => a.account === account) || account === list.next ? list.accounts : [...list.accounts];
  const isNew = !list.accounts.some((a) => a.account === account);
  const remove = async () => {
    if (!window.confirm('Remove this email account from sworkr? Nothing is deleted from the mailbox itself.')) return;
    await axios.delete('/api/mail/settings', { params: { account } }).catch(() => {});
    const data = await load();
    setAccount(data.accounts?.[0]?.account || 1);
  };
  return (
    <div className="space-y-4">
      {(list.accounts.length > 1 || list.next !== null) && list.accounts.length > 0 && (
        <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Email accounts">
          {tabs.map((a) => (
            <button key={a.account} type="button" role="tab" aria-selected={account === a.account} onClick={() => setAccount(a.account)}
              className={`px-3 py-1.5 rounded-full text-sm border ${account === a.account ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
              {a.label}{!a.enabled && ' (off)'}
            </button>
          ))}
          {list.next !== null && (
            <button type="button" onClick={() => setAccount(list.next)}
              className={`px-3 py-1.5 rounded-full text-sm border border-dashed ${account === list.next && isNew ? 'bg-sworkr-50 text-sworkr-700 border-sworkr-300' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
              + Add another account
            </button>
          )}
        </div>
      )}
      <EmailAccountForm key={account} account={account} onChanged={load} />
      {!isNew && list.accounts.length > 0 && (
        <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Remove this account</button>
      )}
    </div>
  );
}
