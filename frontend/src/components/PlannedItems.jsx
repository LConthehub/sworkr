import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { formatTime, toDateInput } from '../colors';

/**
 * What's planned, for the calendar: posts to put up, shoots, and the day an ad runs out. They sit on the same
 * days as bookings, so one look shows what the week holds.
 */
export const LAYERS = [
  { id: 'posts', label: 'Posts', color: '#fc4c9c' },
  { id: 'shoots', label: 'Shoots', color: '#7c3aed' },
  { id: 'ads', label: 'Ad dates', color: '#d97706' },
];
const STORE = 'sworkr.calendarLayers';

export function useLayers() {
  const [layers, setLayers] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (saved && typeof saved === 'object') return { posts: true, shoots: true, ads: true, ...saved };
    } catch { /* storage unavailable */ }
    return { posts: true, shoots: true, ads: true };
  });
  const toggle = (id) => setLayers((l) => {
    const next = { ...l, [id]: !l[id] };
    try { localStorage.setItem(STORE, JSON.stringify(next)); } catch { /* private window */ }
    return next;
  });
  return [layers, toggle];
}

const postWhen = (p) => p.posted_at || p.scheduled_at;

/** The planned things between two instants, as { key, type, day (YYYY-MM-DD), time, label, color, raw }. */
export function usePlanned(rangeStart, rangeEnd, layers, version = 0) {
  const [posts, setPosts] = useState([]);
  const [shoots, setShoots] = useState([]);
  const [ads, setAds] = useState([]);
  const first = toDateInput(new Date(rangeStart));
  const last = toDateInput(new Date(rangeEnd - 1));

  useEffect(() => {
    if (!layers.posts) { setPosts([]); return; }
    axios.get('/api/posts', { params: { start: new Date(rangeStart).toISOString(), end: new Date(rangeEnd).toISOString(), limit: 2000 } })
      .then(({ data }) => setPosts(data)).catch(() => setPosts([]));
  }, [rangeStart, rangeEnd, layers.posts, version]);
  useEffect(() => {
    if (!layers.shoots) { setShoots([]); return; }
    axios.get('/api/shoots', { params: { show: 'all' } }).then(({ data }) => setShoots(data)).catch(() => setShoots([]));
  }, [layers.shoots, version]);
  useEffect(() => {
    if (!layers.ads) { setAds([]); return; }
    axios.get('/api/listings').then(({ data }) => setAds(data.listings)).catch(() => setAds([]));
  }, [layers.ads, version]);

  const items = useMemo(() => {
    const out = [];
    for (const p of posts) {
      const when = postWhen(p);
      if (!when || p.status === 'skipped') continue;
      const d = new Date(when);
      const overdue = p.status !== 'posted' && d < new Date();
      out.push({
        key: `post${p.id}`, type: 'post', day: toDateInput(d), time: formatTime(d), sort: d.getTime(), raw: p,
        label: `${p.platform}${p.place ? ` · ${p.place}` : ''}`,
        color: p.status === 'posted' ? '#059669' : p.status === 'idea' ? '#6b7280' : overdue ? '#dc2626' : '#fc4c9c',
      });
    }
    for (const s of shoots) {
      if (!s.shoot_date || s.status === 'cancelled' || s.shoot_date < first || s.shoot_date > last) continue;
      out.push({ key: `shoot${s.id}`, type: 'shoot', day: s.shoot_date, time: s.start_time || '', sort: 0, raw: s, label: s.title, color: '#7c3aed' });
    }
    for (const l of ads) {
      if (!l.end_date || l.paused || l.end_date < first || l.end_date > last) continue;
      out.push({ key: `ad${l.id}`, type: 'ad', day: l.end_date, time: '', sort: 0, raw: l, label: `${l.site}${l.title ? ` · ${l.title}` : ''} ad ends`, color: '#d97706' });
    }
    return out.sort((a, b) => a.sort - b.sort || a.label.localeCompare(b.label));
  }, [posts, shoots, ads, first, last]);

  const onDay = useCallback((day) => {
    const key = toDateInput(day);
    return items.filter((i) => i.day === key);
  }, [items]);
  return { items, onDay };
}

const ICON = { post: '📣', shoot: '📷', ad: '⏳' };

/** A planned thing, small enough for a day in the month grid. */
export function PlannedChip({ item, onOpen }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onOpen(item); }}
      className="block w-full text-left rounded px-1.5 py-0.5 text-[11px] truncate text-white hover:opacity-90"
      style={{ background: item.color }}
      title={`${ICON[item.type]} ${item.time ? `${item.time} ` : ''}${item.label}${item.raw.caption ? `\n${item.raw.caption}` : ''}`}
    >
      {ICON[item.type]} {item.time ? `${item.time} ` : ''}{item.label}
    </button>
  );
}

/** A planned shoot or ad, as a row (posts use PostRow, which has their buttons). */
export function PlannedRow({ item }) {
  const to = item.type === 'shoot' ? `/calendar/shoots?shoot=${item.raw.id}` : '/content/campaigns';
  return (
    <li className="py-2 flex items-center gap-3">
      <span className="w-1.5 self-stretch rounded" style={{ background: item.color }} />
      <span className="flex-1 min-w-0 text-sm">
        <span className="block text-gray-800">{ICON[item.type]} {item.label}</span>
        <span className="block text-xs text-gray-500">
          {item.type === 'shoot'
            ? [item.time, item.raw.location_name, item.raw.summary?.warnings?.[0]].filter(Boolean).join(' · ') || 'Shoot'
            : `Renew it, or let it lapse${item.raw.cost != null ? ` · $${item.raw.cost} to renew` : ''}`}
        </span>
      </span>
      <Link to={to} className="text-xs text-sworkr-600 hover:text-sworkr-800">{item.type === 'shoot' ? 'Open' : 'Ads'}</Link>
    </li>
  );
}

/** The switch between what's on the calendar: tick each kind of planning you want to see. */
export function LayerToggles({ layers, onToggle }) {
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="text-gray-400">Planning:</span>
      {LAYERS.map((l) => (
        <label key={l.id} className="flex items-center gap-1.5">
          <input type="checkbox" checked={layers[l.id]} onChange={() => onToggle(l.id)} />
          <span className="w-2 h-2 rounded-sm" style={{ background: l.color }} aria-hidden="true" />
          {l.label}
        </label>
      ))}
    </span>
  );
}

/** The pages that make up the calendar: the calendar itself, and the lists behind its planning. */
export function CalendarSwitch({ current }) {
  const tabs = [['calendar', '/calendar', 'Calendar'], ['posts', '/calendar/posts', 'Posts'], ['shoots', '/calendar/shoots', 'Shoots'], ['meals', '/calendar/meals', 'Meals']];
  return (
    <nav className="flex gap-1 overflow-x-auto rounded-full bg-white/20 p-1 backdrop-blur-sm" aria-label="Calendar and planning">
      {tabs.map(([id, to, label]) => (
        <Link key={id} to={to} aria-current={current === id ? 'page' : undefined}
          className={`whitespace-nowrap px-3 sm:px-4 py-1.5 rounded-full text-sm font-medium ${current === id ? 'bg-white text-sworkr-600 shadow' : 'text-white hover:bg-white/20'}`}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
