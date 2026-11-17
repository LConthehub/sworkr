import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';

const NETWORKS = { bluesky: 'Bluesky', mastodon: 'Mastodon', reddit: 'Reddit' };
const LABELS = {
  none: 'No label',
  suggestive: 'Suggestive',
  nudity: 'Nudity',
  porn: 'Explicit',
};
const HELP = {
  bluesky: 'Make an app password in Bluesky: Settings → Privacy and security → App passwords. Not your main password.',
  mastodon: 'On your server: Preferences → Development → New application. Tick read:statuses, write:statuses and write:media, then copy "Your access token".',
  reddit: 'Make your own app at reddit.com/prefs/apps: choose "script", any redirect address (like http://localhost). The id is under the app\'s name. Text posts only for now.',
};

// One fetch shared by every post on the page (a list can show dozens).
let cached = null;
let pending = null;
const fetchAccounts = (fresh) => {
  if (fresh || !pending) {
    pending = axios.get('/api/social/accounts').then(({ data }) => { cached = data; return data; }).catch(() => []);
  }
  return pending;
};

/** Connected accounts, shared by the Social page and the post buttons. */
export function useSocialAccounts() {
  const [accounts, setAccounts] = useState(cached || []);
  const load = useCallback((fresh = true) => { fetchAccounts(fresh).then(setAccounts); }, []);
  useEffect(() => { load(false); }, [load]);
  return [accounts, load];
}

/** The accounts that can post a planned post (same network as its platform). */
export function accountsFor(accounts, platform) {
  const p = (platform || '').trim().toLowerCase();
  return accounts.filter((a) => a.network === p);
}

/** On a planned post: "Post now" and "Post at its time", when a matching account is connected. */
export function PublishButtons({ post, accounts, onChanged }) {
  const usable = accountsFor(accounts, post.platform);
  const [busy, setBusy] = useState(false);
  if (!usable.length || post.status === 'posted' || post.status === 'skipped') {
    return post.post_error && post.status !== 'posted' ? <span className="text-xs text-red-600">{post.post_error}</span> : null;
  }
  const account = usable.find((a) => a.id === post.social_account_id) || usable[0];
  const go = async (when) => {
    if (when === 'now' && !window.confirm(`Post this to ${account.display || account.handle} now?`)) return;
    setBusy(true);
    try {
      await axios.post(`/api/posts/${post.id}/publish`, { account_id: account.id, when });
      onChanged?.(when === 'now' ? 'Posted.' : 'It will post itself at its time (sworkr needs to be running then).');
    } catch (err) {
      window.alert(errorMessage(err, "Couldn't post it"));
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };
  const stop = async () => {
    await axios.delete(`/api/posts/${post.id}/publish`).catch(() => {});
    onChanged?.('It won\'t post itself.');
  };
  return (
    <span className="flex flex-wrap items-center gap-2">
      <button disabled={busy} onClick={() => go('now')} className="text-xs px-2.5 py-1.5 rounded-full bg-sworkr-500 text-white hover:bg-sworkr-600 disabled:opacity-50">
        Post to {NETWORKS[account.network]}
      </button>
      {post.auto_post
        ? <button onClick={stop} className="text-xs px-2.5 py-1.5 rounded-full border border-sworkr-200 text-sworkr-600">Posts itself ✕</button>
        : post.scheduled_at && new Date(post.scheduled_at) > new Date()
          && <button disabled={busy} onClick={() => go('scheduled')} className="text-xs px-2.5 py-1.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">Post at its time</button>}
      {post.post_error && <span className="text-xs text-red-600 basis-full">{post.post_error}</span>}
    </span>
  );
}

function AddAccount({ onAdded }) {
  const [form, setForm] = useState({ network: 'bluesky', server: '', handle: '', password: '', token: '', client_id: '', client_secret: '', label: 'none' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      await axios.post('/api/social/accounts', form);
      setForm({ ...form, password: '', token: '', client_secret: '' });
      onAdded();
    } catch (err) {
      setError(errorMessage(err, "Couldn't connect it"));
    } finally {
      setSaving(false);
    }
  };
  const n = form.network;
  return (
    <form onSubmit={submit} className="space-y-3 border-t border-gray-100 pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Network">
          <select value={n} onChange={set('network')} className={inputClass}>
            {Object.entries(NETWORKS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Content label on every post">
          <select value={form.label} onChange={set('label')} className={inputClass}>
            {Object.entries(LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        {n !== 'reddit' && (
          <Field label={n === 'bluesky' ? 'Server (leave empty for bsky.social)' : 'Server'}>
            <input value={form.server} onChange={set('server')} required={n === 'mastodon'} placeholder={n === 'bluesky' ? 'bsky.social' : 'mastodon.example'} className={inputClass} />
          </Field>
        )}
        {n !== 'mastodon' && (
          <Field label={n === 'bluesky' ? 'Handle' : 'Reddit username'}>
            <input value={form.handle} onChange={set('handle')} required autoComplete="off" className={inputClass} />
          </Field>
        )}
        {n === 'bluesky' && (
          <Field label="App password">
            <input type="password" value={form.password} onChange={set('password')} required autoComplete="new-password" className={inputClass} />
          </Field>
        )}
        {n === 'mastodon' && (
          <Field label="Access token">
            <input type="password" value={form.token} onChange={set('token')} required autoComplete="off" className={inputClass} />
          </Field>
        )}
        {n === 'reddit' && (
          <>
            <Field label="Reddit password">
              <input type="password" value={form.password} onChange={set('password')} required autoComplete="new-password" className={inputClass} />
            </Field>
            <Field label="App id">
              <input value={form.client_id} onChange={set('client_id')} required autoComplete="off" className={inputClass} />
            </Field>
            <Field label="App secret">
              <input type="password" value={form.client_secret} onChange={set('client_secret')} required autoComplete="off" className={inputClass} />
            </Field>
          </>
        )}
      </div>
      <p className="text-xs text-gray-500">{HELP[n]} sworkr signs in once to check, then keeps it sealed on this computer.</p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Checking…' : 'Connect'}</button>
    </form>
  );
}

function Accounts() {
  const [accounts, load] = useSocialAccounts();
  const [adding, setAdding] = useState(false);
  const setLabel = async (a, label) => { await axios.put(`/api/social/accounts/${a.id}`, { label }).catch(() => {}); load(); };
  const remove = async (a) => {
    if (!window.confirm(`Disconnect ${a.display || a.handle}? Posts already made stay on ${NETWORKS[a.network]}.`)) return;
    await axios.delete(`/api/social/accounts/${a.id}`).catch(() => {});
    load();
  };
  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-gray-800">Accounts</h2>
        {!adding && <button onClick={() => setAdding(true)} className={quietButtonClass}>+ Connect an account</button>}
      </div>
      <p className="text-sm text-gray-600">
        Post planned posts straight to Bluesky, Mastodon or Reddit, now or at their time. Your own login, no company account
        in between. The content label tells each network how adult a post is, so it follows their rules.
      </p>
      {accounts.length > 0 && (
        <ul className="divide-y divide-gray-100">
          {accounts.map((a) => (
            <li key={a.id} className="py-2 flex flex-wrap items-center gap-3">
              <span className="flex-1 min-w-40">
                <span className="font-medium text-gray-800">{a.display || a.handle}</span>
                <span className="block text-xs text-gray-500">{NETWORKS[a.network]}</span>
              </span>
              <select value={a.label} onChange={(e) => setLabel(a, e.target.value)} aria-label="Content label" className={`${inputClass} !w-auto !py-1.5`}>
                {Object.entries(LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <button onClick={() => remove(a)} className="text-xs text-gray-500 hover:text-red-600">Disconnect</button>
            </li>
          ))}
        </ul>
      )}
      {adding && <AddAccount onAdded={() => { setAdding(false); load(); }} />}
    </div>
  );
}

function Numbers() {
  const [days, setDays] = useState(90);
  const [data, setData] = useState(null);
  const [message, setMessage] = useState('');
  const load = useCallback(() => {
    axios.get('/api/social/stats', { params: { days } }).then(({ data: d }) => setData(d)).catch(() => setData({ platforms: [], posts: [] }));
  }, [days]);
  useEffect(() => { load(); }, [load]);
  const refresh = async () => {
    setMessage('Fetching…');
    try {
      const { data: r } = await axios.post('/api/social/stats/refresh');
      setMessage([`Updated ${r.updated} post${r.updated === 1 ? '' : 's'}.`, ...r.problems].join(' '));
      load();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't fetch the numbers"));
    }
  };
  const upload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const { data: r } = await axios.post('/api/social/stats/import', await file.text(), { headers: { 'Content-Type': 'text/csv' } });
      setMessage(`Matched ${r.matched} post${r.matched === 1 ? '' : 's'} by link${r.unmatched ? `; ${r.unmatched} rows didn't match a post with that link` : ''}.`);
      load();
    } catch (err) {
      setMessage(errorMessage(err, "Couldn't read that file"));
    }
  };
  if (!data) return null;
  const n = (v) => (v == null ? '–' : v.toLocaleString());
  return (
    <div className="bg-white rounded-2xl border border-line shadow-sm p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-gray-800">Numbers</h2>
        <span className="flex flex-wrap gap-2">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period" className={`${inputClass} !w-auto !py-1.5`}>
            {[30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
          <button onClick={refresh} className={quietButtonClass}>Fetch latest</button>
          <label className={`${quietButtonClass} cursor-pointer`}>
            Import CSV<input type="file" accept=".csv,text/csv" onChange={upload} className="hidden" />
          </label>
        </span>
      </div>
      <p className="text-xs text-gray-500">
        Posts made from sworkr get their numbers fetched. For anything else, import the platform's CSV export: rows are matched
        to your posted posts by their link, so save the link when you mark a post as posted.
      </p>
      {message && <p className="text-sm text-gray-700">{message}</p>}
      {data.platforms.length === 0 ? <p className="text-sm text-gray-500">Nothing posted in this period yet.</p> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-500 text-left">
                <tr><th className="py-1 pr-3">Platform</th><th className="pr-3">Posts</th><th className="pr-3">Likes</th><th className="pr-3">Reposts</th><th className="pr-3">Replies</th><th className="pr-3">Views</th><th>Inquiries</th></tr>
              </thead>
              <tbody className="tabular-nums">
                {data.platforms.map((t) => (
                  <tr key={t.platform} className="border-t border-gray-100">
                    <td className="py-1.5 pr-3 font-medium text-gray-800">{t.platform}</td>
                    <td className="pr-3">{n(t.posts)}</td><td className="pr-3">{n(t.likes)}</td><td className="pr-3">{n(t.reposts)}</td>
                    <td className="pr-3">{n(t.replies)}</td><td className="pr-3">{t.views ? n(t.views) : '–'}</td><td>{n(t.inquiries)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="divide-y divide-gray-100 text-sm">
            {data.posts.slice(0, 50).map((p) => (
              <li key={p.id} className="py-2 flex flex-wrap items-baseline gap-x-3">
                <span className="w-24 shrink-0 text-xs text-gray-500">{p.posted_at?.slice(0, 10)} · {p.platform}</span>
                <span className="flex-1 min-w-40 text-gray-700 line-clamp-1">{p.caption || p.place || '(no caption)'}</span>
                <span className="text-xs text-gray-600 tabular-nums">
                  ♥ {n(p.likes)} · ↻ {n(p.reposts)} · 💬 {n(p.replies)}{p.views ? ` · 👁 ${n(p.views)}` : ''}
                </span>
                {p.post_url && <a href={p.post_url} target="_blank" rel="noreferrer noopener" className="text-xs text-sworkr-600">Open ↗</a>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** Content → Social: connected accounts and how posts did. */
export default function Social() {
  return (
    <div className="space-y-4">
      <Numbers />
      <Accounts />
    </div>
  );
}
