import { useEffect, useState } from 'react';
import axios from 'axios';
import { Field, inputClass, errorMessage } from './Modal';
import { PLATFORMS } from '../pages/Content';

const SOURCES = {
  nextcloud: 'Nextcloud',
  webdav: 'Synology / WebDAV',
  folder: 'Mounted folder',
};

/** Where your content lives. sworkr only reads it; nothing is copied. */
export default function ContentSettings() {
  const [s, setS] = useState(null);
  const [form, setForm] = useState(null);
  const [waits, setWaits] = useState([]);
  const [message, setMessage] = useState(null);
  const [working, setWorking] = useState('');

  useEffect(() => {
    axios.get('/api/content/settings').then(({ data }) => {
      setS(data);
      const server = data.kind === 'nextcloud' && data.url ? data.url.split('/remote.php/')[0] : data.url || '';
      setForm({
        kind: data.kind || 'nextcloud', url: server, folder: data.folder || '', username: data.username || '', password: '',
        use_calendar_login: data.use_calendar_login,
      });
      setWaits(Object.entries(data.repost_days || {}).map(([platform, days]) => ({ platform, days: String(days) })));
    }).catch((err) => setMessage({ error: errorMessage(err, 'Could not load content settings') }));
  }, []);

  if (!form) return message?.error ? <p className="text-sm text-red-600">{message.error}</p> : null;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const body = () => ({
    ...form,
    repost_days: Object.fromEntries(waits.filter((w) => w.platform.trim() && w.days !== '').map((w) => [w.platform.trim(), Number(w.days)])),
  });
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
    const { data } = await axios.post('/api/content/test', body());
    setMessage({ ok: `Connected. Found ${data.sets} set${data.sets === 1 ? '' : 's'} (folders) and ${data.files} loose file${data.files === 1 ? '' : 's'}.` });
  });
  const save = (e) => {
    e.preventDefault();
    run('save', async () => {
      const { data } = await axios.put('/api/content/settings', body());
      setS(data);
      setForm({ ...form, password: '' });
      setMessage({ ok: 'Saved. Open Content to see your sets.' });
    });
  };
  const k = form.kind;

  return (
    <div className="space-y-4">
      {s.demo && (
        <p className="rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-sm text-red-800" role="alert">
          <strong>This is a demo. Don't connect a real folder or account here.</strong> The demo shows a made-up library.
        </p>
      )}
      <p className="text-sm text-gray-600">
        Point sworkr at the folder you keep your photos and videos in, whatever you use them for: ads, socials or fan sites. Each subfolder is a set. sworkr only reads the folder,
        never changes or copies anything, and makes thumbnails in memory without saving them.
      </p>
      <form onSubmit={save} className="space-y-3">
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Where your content is">
          {Object.entries(SOURCES).map(([key, label]) => (
            <button key={key} type="button" role="radio" aria-checked={k === key} disabled={s.demo} onClick={() => setForm({ ...form, kind: key })}
              className={`px-3 py-1.5 rounded-full text-sm border ${k === key ? 'bg-sworkr-500 text-white border-sworkr-500' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
              {label}
            </button>
          ))}
        </div>

        <fieldset disabled={s.demo} className="space-y-3 disabled:opacity-60">
          {k === 'nextcloud' && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Nextcloud address"><input value={form.url} onChange={set('url')} placeholder="https://cloud.example.com" className={inputClass} /></Field>
                <Field label="Folder in your Nextcloud"><input value={form.folder} onChange={set('folder')} placeholder="Content" className={inputClass} /></Field>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={form.use_calendar_login} onChange={set('use_calendar_login')} />
                Use the same login as calendar sync
              </label>
              <p className="text-xs text-gray-500">Nextcloud also makes the thumbnails, so videos get previews too.</p>
            </>
          )}
          {k === 'webdav' && (
            <>
              <Field label="Folder address (WebDAV)">
                <input value={form.url} onChange={set('url')} placeholder="https://192.168.1.20:5006/Content" className={inputClass} />
              </Field>
              <div className="text-xs text-gray-500 space-y-1">
                <p><b>Synology:</b> in Package Center install <b>WebDAV Server</b>, open it and turn on HTTPS (port 5006). The address is
                  https://<i>your-NAS</i>:5006/<i>shared folder</i>/<i>subfolder</i>, for example https://192.168.1.20:5006/photo/Content.</p>
                <p>Make a separate DSM user for sworkr with <b>read-only</b> access to that shared folder, and use it here.</p>
                <p>Other NAS and cloud drives that offer WebDAV (QNAP, TrueNAS, Box, Koofr…) work the same way.</p>
              </div>
            </>
          )}
          {(k === 'nextcloud' && !form.use_calendar_login) || k === 'webdav' ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label="Username"><input value={form.username} onChange={set('username')} autoComplete="off" className={inputClass} /></Field>
              <Field label="App password">
                <input type="password" value={form.password} onChange={set('password')} autoComplete="new-password"
                  placeholder={s.has_password ? 'Saved. Leave empty to keep it.' : ''} className={inputClass} />
              </Field>
            </div>
          ) : null}
          {k === 'folder' && (
            <>
              <Field label={`Folder inside ${s.content_root}`}>
                <input value={form.folder} onChange={set('folder')} placeholder="(leave empty for the whole folder)" className={inputClass} />
              </Field>
              <div className="text-xs text-gray-500 space-y-1">
                <p>
                  For a folder on this computer, a NAS share or an external drive. It has to be mounted into sworkr's
                  container first, read-only. In <code>docker-compose.yml</code>, under <code>api:</code> → <code>volumes:</code>, add
                  a line like <code>- D:/Content:{s.content_root}:ro</code> (Windows) or <code>- /mnt/nas/Content:{s.content_root}:ro</code>, then restart sworkr.
                </p>
                <p><b>Synology:</b> either mount the shared folder on the computer that runs sworkr (SMB), or run sworkr on the Synology
                  itself in Container Manager and mount <code>/volume1/photo/Content</code> as {s.content_root}.</p>
              </div>
            </>
          )}

          <div className="rounded-lg border border-gray-200 px-3 py-2">
            <p className="text-sm font-medium text-gray-700">Wait before reposting</p>
            <p className="text-xs text-gray-500 mb-2">When you plan a post, sworkr warns you if the same file went to that platform recently.</p>
            <datalist id="wait-platforms">{PLATFORMS.map((p) => <option key={p} value={p} />)}</datalist>
            {waits.map((w, i) => (
              <div key={i} className="flex items-center gap-2 mb-1">
                <input list="wait-platforms" value={w.platform} onChange={(e) => setWaits(waits.map((x, j) => (j === i ? { ...x, platform: e.target.value } : x)))} placeholder="Platform" className={inputClass} aria-label="Platform" />
                <input type="number" min="0" max="3650" value={w.days} onChange={(e) => setWaits(waits.map((x, j) => (j === i ? { ...x, days: e.target.value } : x)))} className={`${inputClass} !w-24`} aria-label="Days" />
                <span className="text-xs text-gray-500">days</span>
                <button type="button" onClick={() => setWaits(waits.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500" aria-label="Remove">✕</button>
              </div>
            ))}
            <button type="button" onClick={() => setWaits([...waits, { platform: '', days: '90' }])} className="text-xs text-sworkr-600 hover:text-sworkr-800">+ Add a wait</button>
          </div>
        </fieldset>

        {message?.error && <p className="text-sm text-red-600">{message.error}</p>}
        {message?.ok && <p className="text-sm text-emerald-600">{message.ok}</p>}
        {!s.demo && (
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={!!working} className="px-5 py-2 bg-sworkr-500 text-white rounded-lg hover:bg-sworkr-600 disabled:opacity-50 text-sm">{working === 'save' ? 'Saving…' : 'Save'}</button>
            <button type="button" onClick={test} disabled={!!working} className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">{working === 'test' ? 'Testing…' : 'Test connection'}</button>
          </div>
        )}
      </form>
    </div>
  );
}
