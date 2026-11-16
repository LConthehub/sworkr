import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { Field, inputClass, errorMessage, buttonClass, quietButtonClass } from './Modal';
import { dayLabel, formatTime, fromDateInput } from '../colors';

/** Load a list once, and again whenever `version` changes. */
function useList(url, version = 0) {
  const [items, setItems] = useState([]);
  const load = useCallback(() => axios.get(url).then(({ data }) => setItems(data)).catch(() => setItems([])), [url]);
  useEffect(() => { load(); }, [load, version]);
  return [items, load];
}
export const useCampaigns = (version) => useList('/api/campaigns', version);
export const usePlaces = (version) => useList('/api/post-places', version);
export const useSnippets = (version) => useList('/api/snippets', version);

const shortDay = (value) => dayLabel(fromDateInput(value), { month: 'short', day: 'numeric' });
const dateSpan = (c) => (c.start_date && c.end_date ? `${shortDay(c.start_date)} – ${shortDay(c.end_date)}`
  : c.start_date ? `From ${shortDay(c.start_date)}` : c.end_date ? `Until ${shortDay(c.end_date)}` : '');

// ==================== CAMPAIGNS ====================

/** Content → Campaigns: each push with how far along it is. */
export function Campaigns({ version, onPlan }) {
  const [campaigns, reload] = useCampaigns(version);
  const [editing, setEditing] = useState(null); // {} for a new one
  const [showOld, setShowOld] = useState(false);
  const shown = campaigns.filter((c) => showOld || !c.archived);
  const done = () => { setEditing(null); reload(); };
  const [notice, setNotice] = useState('');
  const suggest = async (c) => {
    const answer = window.prompt('Which platforms should the tour posts be for? Separate them with commas.', c.platforms.join(', ') || 'X');
    if (answer === null) return;
    try {
      // 12 noon here, as an hour in UTC
      const { data } = await axios.post(`/api/campaigns/${c.id}/plan`, { platforms: answer.split(','), hour_utc: new Date(2000, 0, 1, 12).getUTCHours() });
      setNotice(data.created ? `Added ${data.created} post idea${data.created === 1 ? '' : 's'} to ${c.name}. Open "See its posts" to rewrite and schedule them.` : 'Nothing to add: those posts are already there, or the dates have passed.');
      reload();
    } catch (err) {
      setNotice(errorMessage(err, 'Could not add the posts'));
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h2 className="font-semibold text-gray-800">Campaigns</h2>
        <button onClick={() => setEditing({})} className="px-4 py-2 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">+ New campaign</button>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        A campaign is one push: a tour announcement, a set launch, a week you want to fill. Put its posts together here so you can see
        what's gone out, what's late and what it brought in.
      </p>
      {notice && <p className="text-sm text-emerald-700 mb-3">{notice}</p>}
      {shown.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">No campaigns yet. Start one for your next tour or set.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {shown.map((c) => (
            <li key={c.id} className={`rounded-xl border border-gray-100 p-4 ${c.archived ? 'opacity-60' : ''}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="font-medium text-gray-800 break-words">{c.name}</h3>
                  <p className="text-xs text-gray-500">
                    {[dateSpan(c), c.tour_name && `Tour: ${c.tour_name}`, c.set_path && `Set: ${c.set_path}`].filter(Boolean).join(' · ') || 'No dates'}
                  </p>
                </div>
                <button onClick={() => setEditing(c)} className="text-xs text-sworkr-600 hover:text-sworkr-800 shrink-0">Edit</button>
              </div>
              {c.goal && <p className="text-sm text-gray-600 mt-1">{c.goal}</p>}
              <div className="mt-3 h-2 rounded bg-gray-100 overflow-hidden" role="img" aria-label={`${c.posted} of ${c.posts} posted`}>
                <div className="h-full bg-emerald-500" style={{ width: `${c.posts ? (c.posted / c.posts) * 100 : 0}%` }} />
              </div>
              <p className="text-xs text-gray-600 mt-1">
                {c.posts === 0 ? 'No posts yet' : `${c.posted} of ${c.posts} posted`}
                {c.overdue > 0 && <span className="text-red-600"> · {c.overdue} overdue</span>}
                {c.next_due && ` · next ${dayLabel(new Date(c.next_due), { weekday: 'short', month: 'short', day: 'numeric' })}, ${formatTime(new Date(c.next_due))}`}
                {c.inquiries != null && ` · ${c.inquiries} inquir${c.inquiries === 1 ? 'y' : 'ies'}`}
              </p>
              {c.platforms.length > 0 && (
                <p className="flex flex-wrap gap-1 mt-2">
                  {c.platforms.map((p) => <span key={p} className="text-[10px] px-1.5 rounded-full bg-gray-100 text-gray-600">{p}</span>)}
                </p>
              )}
              <div className="flex flex-wrap gap-2 mt-3">
                <button onClick={() => onPlan({ campaign_id: c.id, set_path: c.set_path || null })} className={buttonClass}>+ Post</button>
                {c.tour_id && <button onClick={() => suggest(c)} className={quietButtonClass} title="Adds the usual run of tour posts as ideas">Suggest tour posts</button>}
                <Link to={`/content/planner?campaign=${c.id}`} className={quietButtonClass}>See its posts</Link>
              </div>
            </li>
          ))}
        </ul>
      )}
      {campaigns.some((c) => c.archived) && (
        <button onClick={() => setShowOld(!showOld)} className="text-xs text-gray-500 hover:text-gray-700 mt-3">
          {showOld ? 'Hide finished campaigns' : 'Show finished campaigns'}
        </button>
      )}
      {editing && (
        <Modal title={editing.id ? 'Edit campaign' : 'New campaign'} onClose={() => setEditing(null)}>
          <CampaignForm campaign={editing} onDone={done} />
        </Modal>
      )}
    </div>
  );
}

function CampaignForm({ campaign, onDone }) {
  const [form, setForm] = useState({
    name: campaign.name || '', goal: campaign.goal || '', start_date: campaign.start_date || '', end_date: campaign.end_date || '',
    tour_id: campaign.tour_id ? String(campaign.tour_id) : '', set_path: campaign.set_path || '', notes: campaign.notes || '',
    archived: !!campaign.archived,
  });
  const [tours, setTours] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    axios.get('/api/tours').then(({ data }) => setTours(data.filter((t) => t.kind === 'tour'))).catch(() => {});
  }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const pickTour = (e) => {
    const tour = tours.find((t) => String(t.id) === e.target.value);
    // A tour's campaign usually runs from two weeks before it until it ends.
    const before = tour ? new Date(fromDateInput(tour.start_date).getTime() - 14 * 86400000) : null;
    setForm({
      ...form, tour_id: e.target.value,
      name: form.name || (tour ? `${tour.name || tour.location || 'Tour'} tour` : ''),
      start_date: form.start_date || (before ? before.toISOString().slice(0, 10) : ''),
      end_date: form.end_date || (tour ? tour.end_date : ''),
    });
  };
  const submit = async (e) => {
    e.preventDefault();
    const body = {
      ...form, start_date: form.start_date || null, end_date: form.end_date || null,
      tour_id: form.tour_id ? Number(form.tour_id) : null, set_path: form.set_path.trim() || null,
    };
    try {
      if (campaign.id) await axios.put(`/api/campaigns/${campaign.id}`, body);
      else await axios.post('/api/campaigns', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save the campaign'));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this campaign? Its posts stay in the planner.')) return;
    await axios.delete(`/api/campaigns/${campaign.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      {tours.length > 0 && (
        <Field label="For a tour (optional)">
          <select value={form.tour_id} onChange={pickTour} className={inputClass}>
            <option value="">Not for a tour</option>
            {tours.map((t) => <option key={t.id} value={t.id}>{t.name || t.location || 'Tour'} ({shortDay(t.start_date)} – {shortDay(t.end_date)})</option>)}
          </select>
        </Field>
      )}
      <Field label="Name *"><input required autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Chicago tour, Red lace launch" className={inputClass} /></Field>
      <Field label="Goal"><input value={form.goal} onChange={set('goal')} placeholder="e.g. 6 bookings, 30 new subscribers" className={inputClass} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Starts"><input type="date" value={form.start_date} onChange={set('start_date')} className={inputClass} /></Field>
        <Field label="Ends"><input type="date" value={form.end_date} onChange={set('end_date')} className={inputClass} /></Field>
      </div>
      <Field label="Set in your library (optional)">
        <input value={form.set_path} onChange={set('set_path')} placeholder="The folder's name, e.g. 2026-11 Red lace" className={inputClass} />
      </Field>
      <Field label="Notes"><textarea rows={2} value={form.notes} onChange={set('notes')} className={inputClass} /></Field>
      {campaign.id && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.archived} onChange={set('archived')} /> Finished (hide it from the list)
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {campaign.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete campaign</button> : <span />}
        <button type="submit" className={buttonClass}>{campaign.id ? 'Save changes' : 'Save campaign'}</button>
      </div>
    </form>
  );
}

// ==================== PLACES AND SAVED TEXT ====================

/** Content → Places & text: where you post, with each place's rules, and bits of text you reuse. */
export function Toolkit({ platforms }) {
  const [places, reloadPlaces] = usePlaces();
  const [snippets, reloadSnippets] = useSnippets();
  const [place, setPlace] = useState(null);
  const [snippet, setSnippet] = useState(null);
  const [copied, setCopied] = useState(null);
  const now = new Date();
  const copy = async (s) => {
    try {
      await navigator.clipboard.writeText(s.body);
      setCopied(s.id);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked: the text is on screen to copy by hand */ }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="font-semibold text-gray-800">Your platforms</h2>
          <button onClick={() => setPlace({})} className={buttonClass}>+ Add a platform</button>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Each platform you post on, and each channel within one that has its own rules (a subreddit, a group). Write the rules
          down once and say how often you may post there. The planner then warns you when a post is too soon after the last one.
        </p>
        {places.length === 0 ? <p className="text-sm text-gray-400 py-4 text-center">None yet.</p> : (
          <ul className="divide-y divide-gray-100">
            {places.map((p) => {
              const waiting = p.free_from && new Date(p.free_from) > now;
              return (
                <li key={p.id} className={`py-2.5 flex flex-wrap items-start gap-x-3 gap-y-1 ${p.archived ? 'opacity-50' : ''}`}>
                  <button onClick={() => setPlace(p)} className="flex-1 min-w-48 text-left">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-gray-800">{p.name}</span>
                      <span className="text-xs text-gray-500">{p.platform}</span>
                      {p.wait_days ? <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">every {p.wait_days} day{p.wait_days === 1 ? '' : 's'}</span> : null}
                      {p.wait_days ? (
                        <span className={`text-[10px] px-2 py-0.5 rounded-full ${waiting ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-700'}`}>
                          {waiting ? `Wait until ${dayLabel(new Date(p.free_from), { weekday: 'short', month: 'short', day: 'numeric' })}` : 'OK to post'}
                        </span>
                      ) : null}
                    </span>
                    {p.rules && <span className="block text-sm text-gray-600 whitespace-pre-wrap">{p.rules}</span>}
                    <span className="block text-xs text-gray-400">
                      {p.posted ? `Posted ${p.posted} time${p.posted === 1 ? '' : 's'}, last on ${dayLabel(new Date(p.last_posted), { month: 'short', day: 'numeric' })}` : 'Nothing posted here yet'}
                    </span>
                  </button>
                  {p.link && <a href={p.link} target="_blank" rel="noreferrer noopener" className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">Open ↗</a>}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="font-semibold text-gray-800">Saved text</h2>
          <button onClick={() => setSnippet({})} className={buttonClass}>+ Add text</button>
        </div>
        <p className="text-xs text-gray-500 mb-3">Links, hashtags, a sign-off, your booking line. Add them to a caption with one tap when you plan a post.</p>
        {snippets.length === 0 ? <p className="text-sm text-gray-400 py-4 text-center">None yet.</p> : (
          <ul className="divide-y divide-gray-100">
            {snippets.map((s) => (
              <li key={s.id} className="py-2.5 flex flex-wrap items-start gap-x-3 gap-y-1">
                <button onClick={() => setSnippet(s)} className="flex-1 min-w-48 text-left">
                  <span className="font-medium text-gray-800">{s.label}</span>
                  <span className="block text-sm text-gray-600 whitespace-pre-wrap line-clamp-3">{s.body}</span>
                </button>
                <button onClick={() => copy(s)} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">{copied === s.id ? 'Copied ✓' : 'Copy'}</button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {place && (
        <Modal title={place.id ? 'Edit platform' : 'Add a platform'} onClose={() => setPlace(null)}>
          <PlaceForm place={place} platforms={platforms} onDone={() => { setPlace(null); reloadPlaces(); }} />
        </Modal>
      )}
      {snippet && (
        <Modal title={snippet.id ? 'Edit text' : 'Add text'} onClose={() => setSnippet(null)}>
          <SnippetForm snippet={snippet} onDone={() => { setSnippet(null); reloadSnippets(); }} />
        </Modal>
      )}
    </div>
  );
}

function PlaceForm({ place, platforms, onDone }) {
  const [form, setForm] = useState({
    platform: place.platform || '', name: place.name || '', rules: place.rules || '',
    wait_days: place.wait_days ?? '', link: place.link || '', archived: !!place.archived,
  });
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...form, wait_days: form.wait_days === '' ? null : Number(form.wait_days), link: form.link.trim() || null };
    try {
      if (place.id) await axios.put(`/api/post-places/${place.id}`, body);
      else await axios.post('/api/post-places', body);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save it'));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this platform entry? Posts that name it are kept.')) return;
    await axios.delete(`/api/post-places/${place.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Platform *">
          <input required list="place-platforms" value={form.platform} onChange={set('platform')} placeholder="e.g. Reddit" className={inputClass} />
          <datalist id="place-platforms">{platforms.map((p) => <option key={p} value={p} />)}</datalist>
        </Field>
        <Field label="Account or channel *"><input required value={form.name} onChange={set('name')} placeholder="e.g. @myhandle, r/example, my channel" className={inputClass} /></Field>
      </div>
      <Field label="Its rules">
        <textarea rows={3} value={form.rules} onChange={set('rules')} placeholder="Title format, what's allowed, verification, flair…" className={inputClass} />
      </Field>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="At most one post every (days)">
          <input type="number" min="0" max="3650" value={form.wait_days} onChange={set('wait_days')} placeholder="No limit" className={inputClass} />
        </Field>
        <Field label="Link"><input value={form.link} onChange={set('link')} placeholder="https://…" className={inputClass} /></Field>
      </div>
      {place.id && (
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={form.archived} onChange={set('archived')} /> I don't post here any more
        </label>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {place.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}

function SnippetForm({ snippet, onDone }) {
  const [form, setForm] = useState({ label: snippet.label || '', body: snippet.body || '' });
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (snippet.id) await axios.put(`/api/snippets/${snippet.id}`, form);
      else await axios.post('/api/snippets', form);
      onDone();
    } catch (err) {
      setError(errorMessage(err, 'Could not save'));
    }
  };
  const remove = async () => {
    if (!window.confirm('Delete this saved text?')) return;
    await axios.delete(`/api/snippets/${snippet.id}`).catch(() => {});
    onDone();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Name *"><input required autoFocus value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="e.g. Links, Hashtags, Booking line" className={inputClass} /></Field>
      <Field label="Text *"><textarea required rows={4} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} className={inputClass} /></Field>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-between">
        {snippet.id ? <button type="button" onClick={remove} className="text-sm text-red-500 hover:text-red-700">Delete</button> : <span />}
        <button type="submit" className={buttonClass}>Save</button>
      </div>
    </form>
  );
}
