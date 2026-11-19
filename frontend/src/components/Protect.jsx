import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { toDateInput } from '../colors';

const copy = (text) => navigator.clipboard?.writeText(text).catch(() => {});

/** Content > Protect: the paperwork behind what you publish, and getting stolen copies taken down. */
export default function Protect() {
  return (
    <div className="space-y-4">
      <Paperwork />
      <Takedowns />
    </div>
  );
}

// ==================== PAPERWORK ====================

function Paperwork() {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => { axios.get('/api/paperwork').then(({ data: d }) => setData(d)).catch(() => setData({ people: [] })); }, []);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-gray-800">Paperwork</h2>
        {data.release_text && (
          <button type="button" onClick={() => { copy(data.release_text); setCopied(true); }} className={quietButtonClass}>{copied ? 'Copied ✓' : 'Copy a blank release'}</button>
        )}
      </div>
      <p className="text-sm text-gray-600">
        Everyone on camera needs their ID checked and a signed release. Whoever held the camera needs a release too. Sites ask for
        these, sometimes years later. Sworkr keeps the dates and where the copies are, never the ID itself.
      </p>
      {data.released_incomplete > 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="alert">
          {data.released_incomplete} {data.released_incomplete === 1 ? 'person is' : 'people are'} in content that is already out, with paperwork missing.
        </p>
      )}
      {data.people.length === 0 ? (
        <p className="text-sm text-gray-400 py-4 text-center">Nobody yet. Add co-stars and photographers to a shoot (Calendar, Shoots) and they show here.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data.people.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => setEditing(p)} className="w-full text-left py-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="flex-1 min-w-40">
                  <span className="block text-sm font-medium text-gray-800">{p.name} <span className="font-normal text-gray-500">· {p.role}</span></span>
                  <span className="block text-xs text-gray-500">{p.shoot_title}{p.shoot_date ? ` · ${p.shoot_date}` : ''}{p.released ? ' · released' : ''}</span>
                </span>
                {p.missing.length === 0
                  ? <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700">Complete</span>
                  : <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-100 text-red-700">Missing: {p.missing.join(', ')}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-gray-500">The blank release is a starting point, not legal advice. The rules differ by country and by site.</p>
      {editing && (
        <Modal title={`${editing.name}: paperwork`} onClose={() => setEditing(null)}>
          <PaperworkForm person={editing} onDone={() => { setEditing(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}

function PaperworkForm({ person, onDone }) {
  const [form, setForm] = useState({
    id_checked_on: person.id_checked_on || '', release_signed_on: person.release_signed_on || '', records_kept: person.records_kept || '',
  });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const today = toDateInput(new Date());
  const submit = async (e) => {
    e.preventDefault();
    try {
      await axios.put(`/api/shoots/people/${person.id}/paperwork`, {
        id_checked_on: form.id_checked_on || null, release_signed_on: form.release_signed_on || null, records_kept: form.records_kept,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm text-gray-600">{person.shoot_title} · {person.role}</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="ID checked on">
          <input type="date" max={today} value={form.id_checked_on} onChange={set('id_checked_on')} className={inputClass} />
        </Field>
        <Field label="Release signed on">
          <input type="date" max={today} value={form.release_signed_on} onChange={set('release_signed_on')} className={inputClass} />
        </Field>
      </div>
      <Field label="Where the copies are kept">
        <input value={form.records_kept} onChange={set('records_kept')} placeholder="e.g. The locked folder on my drive" className={inputClass} />
      </Field>
      <p className="text-xs text-gray-500">Clear a date if it was not done. Keep the ID copy and the signed release somewhere safe of your own.</p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save</button></div>
    </form>
  );
}

// ==================== TAKEDOWNS ====================

const STATUS = {
  found: { label: 'Found', badge: 'bg-red-100 text-red-700' },
  sent: { label: 'Notice sent', badge: 'bg-amber-100 text-amber-800' },
  removed: { label: 'Removed', badge: 'bg-emerald-100 text-emerald-700' },
  refused: { label: 'Refused', badge: 'bg-gray-200 text-gray-700' },
};
const BLANK = { site: '', url: '', what: '', original_url: '', notes: '', status: 'found', sent_on: '', sent_to: '', removed_on: '' };

function Takedowns() {
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(null);
  const load = useCallback(() => { axios.get('/api/leaks').then(({ data: d }) => setData(d)).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);
  if (!data) return null;
  const done = () => { setModal(null); load(); };
  const move = async (leak, status) => { await axios.post(`/api/leaks/${leak.id}/status`, { status, on: toDateInput(new Date()) }).catch(() => {}); load(); };
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-gray-800">Stolen content</h2>
        <span className="flex gap-2">
          <button type="button" onClick={() => setModal({ settings: data.settings })} className={quietButtonClass}>Notice settings</button>
          <button type="button" onClick={() => setModal({ leak: { ...BLANK, found_on: toDateInput(new Date()) } })} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ Found one</button>
        </span>
      </div>
      <p className="text-sm text-gray-600">
        When your content turns up somewhere it should not be, write it down here. Sworkr writes the takedown notice for you to
        send yourself, and reminds you to chase after {data.chase_days} days without an answer.
      </p>
      {data.to_chase > 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="alert">
          {data.to_chase} {data.to_chase === 1 ? 'notice has' : 'notices have'} had no answer for {data.chase_days} days or more. Send it again, or try the site's host.
        </p>
      )}
      {data.leaks.length === 0 ? (
        <p className="text-sm text-gray-400 py-4 text-center">Nothing here. That's the good kind of empty.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {data.leaks.map((l) => (
            <li key={l.id} className="py-3 flex flex-wrap items-start gap-x-3 gap-y-1">
              <button type="button" onClick={() => setModal({ leak: Object.fromEntries(Object.entries(l).map(([k, v]) => [k, v ?? ''])) })} className="flex-1 min-w-48 text-left">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-800">{l.site}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full ${STATUS[l.status].badge}`}>{STATUS[l.status].label}</span>
                  {l.chase && <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-100 text-red-700">Chase: {l.days_waiting} days</span>}
                </span>
                <span className="block text-xs text-gray-500">
                  {l.what || 'Your content'} · found {l.found_on}{l.sent_on ? ` · sent ${l.sent_on}` : ''}{l.removed_on ? ` · removed ${l.removed_on}` : ''}
                </span>
                {l.url && <span className="block text-xs text-gray-400 break-all">{l.url}</span>}
              </button>
              <span className="flex flex-wrap gap-2 shrink-0">
                {l.status !== 'removed' && <button type="button" onClick={() => setModal({ notice: l })} className={quietButtonClass}>Write the notice</button>}
                {l.status === 'found' && <button type="button" onClick={() => move(l, 'sent')} className="text-xs px-2.5 py-1.5 rounded-lg bg-sworkr-500 text-white hover:bg-sworkr-600">Sent it</button>}
                {l.status === 'sent' && <button type="button" onClick={() => move(l, 'removed')} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">It's gone</button>}
                {l.status === 'sent' && <button type="button" onClick={() => move(l, 'refused')} className={quietButtonClass}>They refused</button>}
                {(l.status === 'removed' || l.status === 'refused') && <button type="button" onClick={() => move(l, 'found')} className={quietButtonClass}>{l.status === 'removed' ? "It's back" : 'Try again'}</button>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {modal?.leak && (
        <Modal title={modal.leak.id ? 'Stolen content' : 'Where did you find it?'} onClose={() => setModal(null)}>
          <LeakForm leak={modal.leak} onDone={done} />
        </Modal>
      )}
      {modal?.notice && (
        <Modal title="Takedown notice" onClose={() => setModal(null)} wide>
          <Notice leak={modal.notice} onSent={async () => { await move(modal.notice, 'sent'); setModal(null); }} />
        </Modal>
      )}
      {modal?.settings && (
        <Modal title="Notice settings" onClose={() => setModal(null)}>
          <NoticeSettings settings={modal.settings} onDone={done} />
        </Modal>
      )}
    </div>
  );
}

function LeakForm({ leak, onDone }) {
  const [form, setForm] = useState(leak);
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...form, sent_on: form.sent_on || null, removed_on: form.removed_on || null };
    try {
      if (form.id) await axios.put(`/api/leaks/${form.id}`, body);
      else await axios.post('/api/leaks', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Couldn't save"));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this entry? It cannot be brought back.')) return;
    await axios.delete(`/api/leaks/${form.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-[1fr_auto] gap-3">
        <Field label="The site or account *"><input required autoFocus value={form.site} onChange={set('site')} placeholder="e.g. a forum, a tube site" className={inputClass} /></Field>
        <Field label="Found on"><input type="date" required value={form.found_on} onChange={set('found_on')} className={inputClass} /></Field>
      </div>
      <Field label="The exact link"><input value={form.url} onChange={set('url')} placeholder="https://" className={inputClass} /></Field>
      <Field label="What it is"><input value={form.what} onChange={set('what')} placeholder="e.g. The red lace set, 12 photos" className={inputClass} /></Field>
      <Field label="Where the real one is sold or posted"><input value={form.original_url} onChange={set('original_url')} placeholder="https://" className={inputClass} /></Field>
      <Field label="Where the notice goes (an address or a form)"><input value={form.sent_to} onChange={set('sent_to')} placeholder="e.g. abuse@ or the site's copyright form" className={inputClass} /></Field>
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} placeholder="Screenshots kept, who replied, what they said" className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {form.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

function Notice({ leak, onSent }) {
  const [notice, setNotice] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { axios.get(`/api/leaks/${leak.id}/notice`).then(({ data }) => setNotice(data)).catch(() => {}); }, [leak.id]);
  if (!notice) return null;
  return (
    <div className="space-y-3">
      {notice.missing.length > 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">Still to fill in: {notice.missing.join(', ')}.</p>
      )}
      <p className="text-sm font-medium text-gray-800">{notice.subject}</p>
      <textarea readOnly rows={14} value={notice.body} className={`${inputClass} font-mono text-xs`} />
      <p className="text-xs text-gray-500">
        Copy it and send it to the site's copyright or abuse address. A notice normally needs a real name, or an agent's: someone
        you trust or a takedown service can send it for you, so your own name stays off it. This is a common form of notice, not legal advice.
      </p>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => { copy(`${notice.subject}\n\n${notice.body}`); setCopied(true); }} className={quietButtonClass}>{copied ? 'Copied ✓' : 'Copy'}</button>
        {leak.status === 'found' && <button type="button" onClick={onSent} className={buttonClass}>I sent it</button>}
      </div>
    </div>
  );
}

function NoticeSettings({ settings, onDone }) {
  const [form, setForm] = useState(settings);
  const submit = async (e) => {
    e.preventDefault();
    await axios.put('/api/leaks/settings', form).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Sign notices as"><input autoFocus value={form.sign_as} onChange={(e) => setForm({ ...form, sign_as: e.target.value })} placeholder="Your name, or your agent's" className={inputClass} /></Field>
      <Field label="Contact address for replies"><input value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} placeholder="An email kept for this" className={inputClass} /></Field>
      <p className="text-xs text-gray-500">Use an email address kept only for this, not your personal one. These are only ever put into the notice text.</p>
      <div className="flex justify-end"><button type="submit" className={buttonClass}>Save</button></div>
    </form>
  );
}
