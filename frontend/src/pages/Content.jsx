import { useCallback, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from '../components/Modal';
import { PersonaSelect } from '../components/Personas';
import { Campaigns, Toolkit, useCampaigns, usePlaces, useSnippets } from '../components/Promo';
import Listings from '../components/Listings';
import Customs from '../components/Customs';
import { dayLabel, formatTime, fromDateTimeInputs, money, repeatDates, toDateInput, toTimeInput } from '../colors';

/** Suggestions only: any platform, ad site or your own website can be typed in. */
export const PLATFORM_GROUPS = {
  'Ad sites': ['Tryst', 'Eros', 'Slixa', 'Private Delights', 'AdultWork', 'Scarlet Blue', 'Leolist', 'Skip the Games', 'My website'],
  Social: ['X', 'Instagram', 'Reddit', 'TikTok', 'Bluesky', 'Threads', 'Telegram', 'Snapchat'],
  'Fan & clip sites': ['OF', 'Fansly', 'Fanvue', 'LoyalFans', 'Patreon', 'ManyVids', 'Clips4Sale', 'Pornhub'],
};
export const PLATFORMS = Object.values(PLATFORM_GROUPS).flat();
const PAID_PLATFORMS = new Set(PLATFORM_GROUPS['Fan & clip sites'].map((p) => p.toLowerCase()));
const STATUS = {
  idea: { label: 'Idea', badge: 'bg-gray-100 text-gray-600' },
  ready: { label: 'Ready', badge: 'bg-sky-100 text-sky-700' },
  scheduled: { label: 'Scheduled', badge: 'bg-sworkr-50 text-sworkr-600' },
  posted: { label: 'Posted', badge: 'bg-emerald-100 text-emerald-700' },
  skipped: { label: 'Skipped', badge: 'bg-gray-100 text-gray-400 line-through' },
};
const thumbUrl = (path, size = 256) => `/api/content/thumbnail?path=${encodeURIComponent(path)}&size=${size}`;
const whenText = (iso) => (iso ? `${dayLabel(new Date(iso), { weekday: 'short', month: 'short', day: 'numeric' })}, ${formatTime(new Date(iso))}` : 'No time set');

// Four sections. Each address still works; several lead to the same section.
const SECTIONS = [['library', '/content', 'Library'], ['promote', '/content/campaigns', 'Promote'], ['customs', '/content/customs', 'Customs']];
const SECTION_OF = { campaigns: 'promote', promote: 'promote', ads: 'promote', toolkit: 'promote', customs: 'customs' };

/** The two halves of a section, as a small switch under the main tabs. */
function Switch({ label, options }) {
  return (
    <div className="inline-flex rounded-lg bg-white/20 p-0.5 text-sm backdrop-blur-sm" role="group" aria-label={label}>
      {options.map(([to, text, active]) => (
        <Link key={to} to={to} aria-current={active ? 'page' : undefined} className={`px-3 py-1 rounded-md font-medium ${active ? 'bg-white text-sworkr-600 shadow' : 'text-white hover:bg-white/20'}`}>{text}</Link>
      ))}
    </div>
  );
}

/** Content: your library, promoting (campaigns, ads, your platforms) and custom orders. Planning lives on the calendar. */
export default function Content() {
  const { tab = 'library' } = useParams();
  const [modal, setModal] = useState(null); // { post } (post may be a draft with files)
  const [version, setVersion] = useState(0);
  const plan = (draft) => setModal({ post: draft });
  const section = SECTION_OF[tab] || 'library';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Content</h1>
        <nav className="flex gap-1 overflow-x-auto rounded-full bg-white/20 p-1 backdrop-blur-sm" aria-label="Content">
          {SECTIONS.map(([id, to, label]) => (
            <Link key={id} to={to} aria-current={section === id ? 'page' : undefined}
              className={`whitespace-nowrap px-3 sm:px-4 py-1.5 rounded-full text-sm font-medium ${section === id ? 'bg-white text-sworkr-600 shadow' : 'text-white hover:bg-white/20'}`}>
              {label}
            </Link>
          ))}
        </nav>
      </div>
      {section === 'promote' && (
        <Switch label="Promote" options={[['/content/campaigns', 'Campaigns & ads', tab !== 'toolkit'], ['/content/toolkit', 'Platforms & saved text', tab === 'toolkit']]} />
      )}
      {tab === 'toolkit' ? <Toolkit platforms={PLATFORMS} />
            : section === 'promote' ? (
              <>
                <Campaigns version={version} onPlan={plan} />
                <Listings sites={PLATFORM_GROUPS['Ad sites']} />
              </>
            )
              : section === 'customs' ? <Customs />
                : <Library onPlan={plan} version={version} />}
      {modal && (
        <Modal title={modal.post.id ? 'Edit post' : 'Plan a post'} onClose={() => setModal(null)} wide>
          <PostForm post={modal.post} onDone={() => { setModal(null); setVersion((v) => v + 1); }} />
        </Modal>
      )}
    </div>
  );
}

// ==================== LIBRARY ====================

function Library({ onPlan, version }) {
  const [path, setPath] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notSetUp, setNotSetUp] = useState(false);
  const [selected, setSelected] = useState([]);

  const load = useCallback(async () => {
    setData(null);
    try {
      const { data: d } = await axios.get('/api/content/browse', { params: { path } });
      setData(d);
      setError('');
    } catch (err) {
      if (err?.response?.status === 409) setNotSetUp(true);
      else setError(errorMessage(err, "Couldn't open your library."));
    }
  }, [path]);
  useEffect(() => { load(); setSelected([]); }, [load, version]);

  if (notSetUp) {
    return (
      <div className="bg-white rounded-2xl shadow-lg p-5 sm:p-6">
        <h2 className="font-semibold text-gray-800">Connect your content folder</h2>
        <p className="text-sm text-gray-600 mt-1">
          Point sworkr at the folder you keep your photos and videos in, for ads, socials and fan sites: Nextcloud, a Synology
          or other NAS, or a folder mounted into sworkr. Each subfolder becomes a set. sworkr only reads it, and never copies your content.
          You can plan posts and ad renewals on the calendar without connecting a folder.
        </p>
        <Link to="/account/connections#content" className={`${buttonClass} inline-block mt-3`}>Connect a folder</Link>
      </div>
    );
  }

  const crumbs = path ? path.split('/') : [];
  const files = data?.entries.filter((e) => !e.folder) || [];
  const toggle = (p) => setSelected((s) => (s.includes(p) ? s.filter((x) => x !== p) : [...s, p]));

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-2 mb-4 text-sm">
        <button onClick={() => setPath('')} className={`font-semibold ${path ? 'text-sworkr-600 hover:text-sworkr-800' : 'text-gray-800'}`}>Library</button>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-2">
            <span className="text-gray-300">/</span>
            <button onClick={() => setPath(crumbs.slice(0, i + 1).join('/'))} className={i === crumbs.length - 1 ? 'font-semibold text-gray-800' : 'text-sworkr-600 hover:text-sworkr-800'}>{c}</button>
          </span>
        ))}
        <span className="ml-auto flex gap-2">
          {data?.web_link && <a href={data.web_link} target="_blank" rel="noreferrer noopener" className={quietButtonClass}>Open in Nextcloud ↗</a>}
          {path && <button onClick={() => onPlan({ set_path: path, file_paths: selected })} className={buttonClass}>
            Plan a post{selected.length ? ` with ${selected.length} file${selected.length === 1 ? '' : 's'}` : ' with this set'}
          </button>}
        </span>
      </div>
      {data?.demo && <p className="text-xs text-gray-400 mb-3">Demo: a made-up library with placeholder pictures.</p>}
      {error && <p className="text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700 mb-3">{error}</p>}
      {!data ? <p className="text-sm text-gray-400 py-6">{error ? '' : 'Opening…'}</p> : (
        <>
          {data.entries.filter((e) => e.folder).length > 0 && (
            <ul className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 mb-5">
              {data.entries.filter((e) => e.folder).map((f) => (
                <li key={f.path}>
                  <button onClick={() => setPath(f.path)} className="w-full text-left rounded-xl border border-gray-100 p-3 hover:shadow-sm hover:border-sworkr-200">
                    <span className="text-2xl" aria-hidden="true">📁</span>
                    <span className="block font-medium text-sm text-gray-800 truncate">{f.name}</span>
                    <span className="block text-xs text-gray-500">
                      {f.platforms?.length ? `Posted: ${f.platforms.join(', ')}` : f.file_posts || f.posts.length ? 'Planned' : 'Not posted yet'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {files.length > 0 ? (
            <>
              <p className="text-xs text-gray-500 mb-2">Tick files to plan a post with them. The badges show where each one has gone.</p>
              <ul className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
                {files.map((f) => (
                  <li key={f.path} className={`rounded-xl border overflow-hidden ${selected.includes(f.path) ? 'border-sworkr-500 ring-2 ring-sworkr-300' : 'border-gray-100'}`}>
                    <button onClick={() => toggle(f.path)} className="block w-full aspect-square bg-gray-100 relative" aria-pressed={selected.includes(f.path)} aria-label={`Select ${f.name}`}>
                      {f.kind === 'other' ? <span className="absolute inset-0 flex items-center justify-center text-3xl">📄</span> : (
                        <img src={thumbUrl(f.path)} alt="" loading="lazy" className="w-full h-full object-cover"
                          onError={(e) => { e.currentTarget.replaceWith(Object.assign(document.createElement('span'), { className: 'absolute inset-0 flex items-center justify-center text-3xl', textContent: f.kind === 'video' ? '🎬' : '🖼' })); }} />
                      )}
                      {f.kind === 'video' && <span className="absolute bottom-1 left-1 text-[10px] px-1.5 rounded bg-black/60 text-white">video</span>}
                      <span className={`absolute top-1 left-1 w-5 h-5 rounded border-2 ${selected.includes(f.path) ? 'bg-sworkr-500 border-sworkr-500 text-white text-xs leading-4 text-center' : 'bg-white/80 border-white'}`}>{selected.includes(f.path) ? '✓' : ''}</span>
                    </button>
                    <div className="px-2 py-1.5">
                      <p className="text-xs text-gray-700 truncate" title={f.name}>{f.name}</p>
                      <div className="flex flex-wrap gap-1 mt-0.5 min-h-[18px]">
                        {f.posts.slice(0, 3).map((p) => (
                          <span key={p.post_id} title={`${STATUS[p.status].label}${p.when ? ` · ${whenText(p.when)}` : ''}`}
                            className={`text-[10px] px-1.5 rounded-full ${p.status === 'posted' ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>
                            {p.status === 'posted' ? '✓ ' : ''}{p.platform}
                          </span>
                        ))}
                        {f.posts.length > 3 && <span className="text-[10px] text-gray-400">+{f.posts.length - 3}</span>}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          ) : data.entries.length === 0 && <p className="text-sm text-gray-400 py-6 text-center">This folder is empty.</p>}
        </>
      )}
    </div>
  );
}

// ==================== PLANNER ====================

export function Planner({ version, onEdit, onNew }) {
  const [filter, setFilter] = useState('open');
  const [posts, setPosts] = useState(null);
  const [notice, setNotice] = useState('');
  const [campaigns] = useCampaigns(version);
  const [search, setSearch] = useSearchParams();
  const campaignId = search.get('campaign') || '';
  const campaignNames = Object.fromEntries(campaigns.map((c) => [c.id, c.name]));
  const load = useCallback(() => {
    const params = { ...(filter === 'all' ? {} : { status: filter }), ...(campaignId ? { campaign_id: campaignId } : {}) };
    axios.get('/api/posts', { params }).then(({ data }) => setPosts(data)).catch(() => setPosts([]));
  }, [filter, campaignId]);
  useEffect(() => { load(); }, [load, version]);

  const byDay = {};
  for (const p of posts || []) {
    const when = p.posted_at || p.scheduled_at;
    const key = when ? toDateInput(new Date(when)) : 'unscheduled';
    (byDay[key] ||= []).push(p);
  }
  const days = Object.keys(byDay).sort((a, b) => (a === 'unscheduled' ? 1 : b === 'unscheduled' ? -1 : filter === 'posted' ? b.localeCompare(a) : a.localeCompare(b)));

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden text-sm" role="group" aria-label="Show">
          {[['open', 'To do'], ['posted', 'Posted'], ['all', 'All']].map(([id, label]) => (
            <button key={id} onClick={() => setFilter(id)} aria-pressed={filter === id} className={`px-3 py-1.5 ${filter === id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{label}</button>
          ))}
        </div>
        {campaigns.length > 0 && (
          <select value={campaignId} onChange={(e) => setSearch(e.target.value ? { campaign: e.target.value } : {})} aria-label="Campaign"
            className="rounded-lg border border-gray-200 px-2 py-1.5 text-sm text-gray-700 bg-white max-w-[14rem]">
            <option value="">All campaigns</option>
            {campaigns.filter((c) => !c.archived || String(c.id) === campaignId).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <button onClick={() => onNew(campaignId ? { campaign_id: Number(campaignId) } : {})} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New post</button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Plan social posts, fan-site drops, ad renewals and bumps, and tour announcements. sworkr doesn't post for you (sites don't
        allow apps to): it reminds you when one is due (turn on Reminders in settings), you copy the text and post it, then mark it as posted.
      </p>
      {notice && <p className="text-sm text-emerald-700 mb-2">{notice}</p>}
      {!posts ? null : posts.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{filter === 'open' ? 'Nothing planned. Plan a post or an ad renewal from a set in your library, or start a new one.' : 'Nothing here yet.'}</p>
      ) : (
        <div className="space-y-4">
          {days.map((d) => (
            <section key={d}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                {d === 'unscheduled' ? 'No date yet' : dayLabel(new Date(`${d}T12:00:00`), { weekday: 'long', month: 'short', day: 'numeric' })}
              </h3>
              <ul className="divide-y divide-gray-100">
                {byDay[d].map((p) => <PostRow key={p.id} post={p} campaign={campaignNames[p.campaign_id]} onEdit={onEdit} onChanged={(msg) => { setNotice(msg || ''); load(); }} />)}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

/** One post, with Copy caption and Mark as posted. Also used on the dashboard. */
export function PostRow({ post: p, campaign, onEdit, onChanged }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(p.caption || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked: the caption is still visible to copy by hand */ }
  };
  const posted = async () => {
    const url = window.prompt('Posted! Paste the link to the post if you like (or leave empty):', '');
    if (url === null) return;
    try {
      await axios.post(`/api/posts/${p.id}/posted`, { post_url: url.trim() || null });
      onChanged?.('Marked as posted.');
    } catch (err) {
      window.alert(errorMessage(err, 'Could not save'));
    }
  };
  const when = p.posted_at || p.scheduled_at;
  const overdue = p.status !== 'posted' && p.status !== 'skipped' && when && new Date(when) < new Date();
  return (
    <li className="py-2.5 flex flex-wrap items-start gap-x-3 gap-y-1">
      {p.file_paths[0] && <img src={thumbUrl(p.file_paths[0], 128)} alt="" loading="lazy" className="w-12 h-12 rounded-lg object-cover bg-gray-100 shrink-0" onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />}
      <button onClick={() => onEdit?.(p)} className="flex-1 min-w-48 text-left">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-gray-800">{p.platform}</span>
          {p.place && <span className="text-sm text-gray-700">{p.place}</span>}
          {p.account && <span className="text-xs text-gray-500">{p.account}</span>}
          <span className={`text-[10px] px-2 py-0.5 rounded-full ${STATUS[p.status].badge}`}>{STATUS[p.status].label}</span>
          {campaign && <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">{campaign}</span>}
          {p.inquiries != null && <span className="text-xs text-gray-600">{p.inquiries} inquir{p.inquiries === 1 ? 'y' : 'ies'}</span>}
          {p.price != null && <span className="text-xs text-gray-600">{money(p.price)}</span>}
        </span>
        <span className={`block text-xs ${overdue ? 'text-red-600' : 'text-gray-500'}`}>
          {when ? `${overdue ? 'Due ' : ''}${formatTime(new Date(when))}` : 'No time set'}
          {p.set_path && ` · ${p.set_path}`}{p.file_paths.length ? ` · ${p.file_paths.length} file${p.file_paths.length === 1 ? '' : 's'}` : ''}
        </span>
        {p.caption && <span className="block text-sm text-gray-600 line-clamp-2 whitespace-pre-wrap">{p.caption}</span>}
      </button>
      <span className="flex gap-2 shrink-0">
        {p.caption && <button onClick={copy} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">{copied ? 'Copied ✓' : 'Copy caption'}</button>}
        {p.status !== 'posted' && <button onClick={posted} className="text-xs px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">✓ Posted</button>}
        {p.post_url && <a href={p.post_url} target="_blank" rel="noreferrer noopener" className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Open ↗</a>}
      </span>
    </li>
  );
}

// ==================== ONE POST ====================

export function PostForm({ post, onDone }) {
  const editing = !!post.id;
  const start = post.scheduled_at ? new Date(post.scheduled_at) : null;
  const [form, setForm] = useState({
    platform: post.platform || '', account: post.account || '', status: post.status || (editing ? 'idea' : 'scheduled'),
    persona_id: post.persona_id ? String(post.persona_id) : '',
    date: start ? toDateInput(start) : '', time: start ? toTimeInput(start) : '19:00',
    caption: post.caption || '', price: post.price ?? '', notes: post.notes || '', post_url: post.post_url || '',
    repeat: '', repeat_count: '4',
    campaign_id: post.campaign_id ? String(post.campaign_id) : '', place: post.place || '', inquiries: post.inquiries ?? '',
  });
  const [also, setAlso] = useState([]); // the same post on other platforms
  const [campaigns] = useCampaigns();
  const [places] = usePlaces();
  const [snippets] = useSnippets();
  const placesFor = (platform) => places.filter((x) => !x.archived && x.platform.toLowerCase() === platform.trim().toLowerCase());
  const savedPlace = placesFor(form.platform).find((x) => x.name.toLowerCase() === form.place.trim().toLowerCase());
  const [files, setFiles] = useState(post.file_paths || []);
  const [setPath] = useState(post.set_path || null);
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const when = form.date ? fromDateTimeInputs(form.date, form.time || '12:00') : null;
    const body = {
      platform: form.platform.trim(), account: form.account.trim() || null, status: form.status,
      persona_id: form.persona_id ? Number(form.persona_id) : null,
      scheduled_at: when ? when.toISOString() : null, caption: form.caption, price: form.price === '' ? null : Number(form.price),
      set_path: setPath, file_paths: files, notes: form.notes, post_url: form.post_url.trim() || null,
      posted_at: post.posted_at || null,
      campaign_id: form.campaign_id ? Number(form.campaign_id) : null, place: form.place.trim() || null,
      inquiries: form.inquiries === '' ? null : Number(form.inquiries),
    };
    if (!editing) {
      body.also = also.filter((a) => a.platform.trim()).map((a) => ({
        platform: a.platform.trim(), account: a.account.trim() || null, place: a.place.trim() || null, caption: a.caption.trim() || null,
        scheduled_at: form.date && a.time ? fromDateTimeInputs(form.date, a.time).toISOString() : null,
      }));
    }
    if (!editing && form.repeat && when) {
      body.repeat_dates = repeatDates(when, form.repeat, Math.min(Math.max(Number(form.repeat_count) || 2, 2), 52)).map((d) => d.toISOString());
    }
    setSaving(true);
    try {
      const { data } = editing ? await axios.put(`/api/posts/${post.id}`, body) : await axios.post('/api/posts', body);
      if (data.warnings?.length) setWarnings(data.warnings);
      else onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the post'));
    } finally {
      setSaving(false);
    }
  };
  const remove = async (scope) => {
    if (!window.confirm(scope === 'following' ? 'Delete this post and the later repeats?' : 'Delete this post?')) return;
    await axios.delete(`/api/posts/${post.id}`, { params: { scope } }).catch(() => {});
    onDone();
  };

  if (warnings) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-emerald-700">Saved.</p>
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900" role="alert">
          <p className="font-semibold">Heads up</p>
          <ul className="mt-1 list-disc pl-5 space-y-0.5">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
        <div className="flex justify-end"><button onClick={onDone} className={buttonClass}>OK</button></div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Platform *">
          <input required list="post-platforms" value={form.platform} onChange={set('platform')} placeholder="Ad site, social or fan site" className={inputClass} />
          <datalist id="post-platforms">
            {Object.entries(PLATFORM_GROUPS).flatMap(([group, names]) => names.map((p) => <option key={p} value={p}>{group}</option>))}
          </datalist>
        </Field>
        <Field label="Account (optional)">
          <input value={form.account} onChange={set('account')} placeholder="@yourhandle" className={inputClass} />
        </Field>
        <Field label="Account or channel (optional)">
          <input list="post-places" value={form.place} onChange={set('place')} placeholder="Subreddit, channel, group" className={inputClass} />
          <datalist id="post-places">{placesFor(form.platform).map((x) => <option key={x.id} value={x.name} />)}</datalist>
        </Field>
        <PersonaSelect value={form.persona_id} onChange={set('persona_id')} label="Persona" />
        {(campaigns.length > 0 || form.campaign_id) && (
          <Field label="Campaign">
            <select value={form.campaign_id} onChange={set('campaign_id')} className={inputClass}>
              <option value="">None</option>
              {campaigns.filter((c) => !c.archived || String(c.id) === form.campaign_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Status">
          <select value={form.status} onChange={set('status')} className={inputClass}>
            {Object.entries(STATUS).map(([v, s]) => <option key={v} value={v}>{s.label}</option>)}
          </select>
        </Field>
      </div>
      {savedPlace?.rules && (
        <p className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900 whitespace-pre-wrap">
          <b>{savedPlace.name} rules:</b> {savedPlace.rules}
        </p>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Field label="Day"><input type="date" value={form.date} onChange={set('date')} className={inputClass} /></Field>
        <Field label="Time"><input type="time" value={form.time} onChange={set('time')} disabled={!form.date} className={inputClass} /></Field>
        {(PAID_PLATFORMS.has(form.platform.trim().toLowerCase()) || form.price !== '') && (
          <Field label="Price ($, pay-per-view)">
            <input type="number" min="0" step="0.01" inputMode="decimal" value={form.price} onChange={set('price')} placeholder="Free" className={inputClass} />
          </Field>
        )}
        {!editing && form.date && (
          <Field label="Repeat">
            <select value={form.repeat} onChange={set('repeat')} className={inputClass}>
              <option value="">Once</option><option value="day">Every day</option><option value="3days">Every 3 days</option>
              <option value="week">Every week</option><option value="2weeks">Every 2 weeks</option><option value="month">Every month</option>
            </select>
          </Field>
        )}
      </div>
      {!editing && form.repeat && (
        <Field label="How many times in total"><input type="number" min="2" max="52" value={form.repeat_count} onChange={set('repeat_count')} className={`${inputClass} !w-24`} /></Field>
      )}
      <Field label={`Caption (${form.caption.length} characters)`}>
        <textarea rows={4} value={form.caption} onChange={set('caption')} placeholder="Caption or ad text" className={inputClass} />
        {snippets.length > 0 && (
          <span className="flex flex-wrap items-center gap-1 mt-1">
            <span className="text-xs text-gray-400">Add:</span>
            {snippets.map((x) => (
              <button key={x.id} type="button" title={x.body}
                onClick={() => setForm((f) => ({ ...f, caption: f.caption.trim() ? `${f.caption.replace(/\s+$/, '')}\n${x.body}` : x.body }))}
                className="text-xs px-2 py-0.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50">{x.label}</button>
            ))}
          </span>
        )}
      </Field>
      {!editing && (
        <fieldset className="rounded-lg border border-gray-200 px-3 pt-2 pb-3 space-y-2">
          <legend className="px-1 text-xs font-medium text-gray-500">Also post it on</legend>
          {also.length === 0 && <p className="text-xs text-gray-400">The same post on another platform: each gets its own line in the planner to tick off.</p>}
          {also.map((a, i) => {
            const change = (k) => (e) => setAlso(also.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)));
            return (
              <div key={i} className="rounded-lg bg-gray-50 p-2 space-y-2">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <input list="post-platforms" value={a.platform} onChange={change('platform')} placeholder="Platform" aria-label="Platform" className={inputClass} />
                  <input list={`also-places-${i}`} value={a.place} onChange={change('place')} placeholder="Where on it" aria-label="Where on it" className={inputClass} />
                  <datalist id={`also-places-${i}`}>{placesFor(a.platform).map((x) => <option key={x.id} value={x.name} />)}</datalist>
                  <input value={a.account} onChange={change('account')} placeholder="@account" aria-label="Account" className={inputClass} />
                  <span className="flex items-center gap-1">
                    <input type="time" value={a.time} onChange={change('time')} disabled={!form.date} aria-label="Time" className={inputClass} />
                    <button type="button" onClick={() => setAlso(also.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500 px-1" aria-label="Remove">✕</button>
                  </span>
                </div>
                <textarea rows={2} value={a.caption} onChange={change('caption')} placeholder="A different caption for this one (leave empty to use the one above)" aria-label="Caption" className={inputClass} />
              </div>
            );
          })}
          <button type="button" onClick={() => setAlso([...also, { platform: '', place: '', account: '', time: form.time, caption: '' }])} className="text-xs text-sworkr-600 hover:text-sworkr-800">
            + Add a platform
          </button>
        </fieldset>
      )}
      <div>
        <p className="text-xs font-medium text-gray-500 mb-1">Files{setPath ? ` from ${setPath}` : ''}</p>
        {files.length === 0 ? (
          <p className="text-xs text-gray-400">{setPath ? 'The whole set.' : 'None. Plan a post from a set in the Library to attach files.'}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {files.map((f) => (
              <li key={f} className="relative">
                <img src={thumbUrl(f, 128)} alt={f} title={f} className="w-16 h-16 rounded-lg object-cover bg-gray-100" onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />
                <button type="button" onClick={() => setFiles(files.filter((x) => x !== f))} className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-white shadow text-xs text-gray-500 hover:text-red-600" aria-label={`Remove ${f}`}>✕</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {(form.status === 'posted' || form.post_url || form.inquiries !== '') && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <span className="sm:col-span-2"><Field label="Link to the post"><input value={form.post_url} onChange={set('post_url')} placeholder="https://…" className={inputClass} /></Field></span>
          <Field label="Inquiries or sales it brought">
            <input type="number" min="0" step="1" inputMode="numeric" value={form.inquiries} onChange={set('inquiries')} placeholder="If you know" className={inputClass} />
          </Field>
        </div>
      )}
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex flex-wrap items-center justify-between gap-2">
        {editing ? (
          <span className="flex gap-3">
            <button type="button" onClick={() => remove('one')} className="text-sm text-red-500 hover:text-red-700">Delete post</button>
            {post.series_id && <button type="button" onClick={() => remove('following')} className="text-sm text-red-500 hover:text-red-700">Delete this and later repeats</button>}
          </span>
        ) : <span />}
        <button type="submit" disabled={saving} className={buttonClass}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Save post'}</button>
      </div>
    </form>
  );
}

/** Posts due today or overdue, for the dashboard. */
export function PostsDue() {
  const [posts, setPosts] = useState(null);
  const [modal, setModal] = useState(null);
  const load = useCallback(() => {
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    axios.get('/api/posts', { params: { status: 'open', end: end.toISOString() } }).then(({ data }) => setPosts(data)).catch(() => setPosts([]));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (!posts || posts.length === 0) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-1">
        <h2 className="font-semibold text-gray-800">Posts & ads due</h2>
        <Link to="/calendar/posts" className="text-sm text-sworkr-600 hover:text-sworkr-800">All posts →</Link>
      </div>
      <ul className="divide-y divide-gray-100">
        {posts.map((p) => <PostRow key={p.id} post={p} onEdit={(x) => setModal(x)} onChanged={load} />)}
      </ul>
      {modal && (
        <Modal title="Edit post" onClose={() => setModal(null)} wide>
          <PostForm post={modal} onDone={() => { setModal(null); load(); }} />
        </Modal>
      )}
    </div>
  );
}


/** Calendar → Posts: every post to put up, with its caption to copy and a tick when it's done. The calendar shows them by day. */
export function PostsPage() {
  const [modal, setModal] = useState(null);
  const [version, setVersion] = useState(0);
  return (
    <>
      <Planner version={version} onEdit={(p) => setModal({ post: p })} onNew={(draft) => setModal({ post: draft })} />
      {modal && (
        <Modal title={modal.post.id ? 'Edit post' : 'Plan a post'} onClose={() => setModal(null)} wide>
          <PostForm post={modal.post} onDone={() => { setModal(null); setVersion((v) => v + 1); }} />
        </Modal>
      )}
    </>
  );
}
