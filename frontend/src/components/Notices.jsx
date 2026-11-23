import { useEffect, useState } from 'react';

/**
 * Update notes and the one-time "Life Is" suggestion.
 * Everything here is stored on this device only (nothing is sent anywhere, nothing is tracked),
 * so dismissing is private and permanent.
 */

// Newest first. Add a note by putting an entry at the top; give it a new id so it shows once.
export const NOTES = [
  { id: 'life-is', title: 'Planning your home life?', after: 14,
    body: "Check out Life Is: list what you own and plan when to use it. It's a separate app, and nothing is shared with sworkr.",
    link: 'https://lifeis.living', linkLabel: 'Take a look' },
];

const KEY_SEEN = 'sworkr:notes-dismissed';
const KEY_FIRST = 'sworkr:first-seen';
const DAY = 86400000;

const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: it just shows again */ } };

function daysHere() {
  let first = read(KEY_FIRST, null);
  if (!first) { first = Date.now(); write(KEY_FIRST, first); }
  return (Date.now() - first) / DAY;
}

export function useDismissed() {
  const [gone, setGone] = useState(() => read(KEY_SEEN, []));
  const dismiss = (id) => setGone((g) => { const next = [...new Set([...g, id])]; write(KEY_SEEN, next); return next; });
  return [gone, dismiss];
}

/** Dashboard banner: the newest note that is due and not yet dismissed. One at a time. */
export function NoticeBanner() {
  const [gone, dismiss] = useDismissed();
  const [days, setDays] = useState(0);
  useEffect(() => { setDays(daysHere()); }, []);
  const note = NOTES.find((n) => !gone.includes(n.id) && days >= (n.after || 0));
  if (!note) return null;
  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 flex items-start gap-3" role="note">
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-gray-800 text-sm">{note.title}</p>
        <p className="text-sm text-gray-600 mt-0.5">{note.body}</p>
        {note.link && (
          <a href={note.link} target="_blank" rel="noopener noreferrer" onClick={() => dismiss(note.id)}
            className="inline-block mt-2 text-sm font-medium text-sworkr-600 hover:underline">{note.linkLabel || 'Open'}</a>
        )}
      </div>
      <button onClick={() => dismiss(note.id)} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-500" aria-label="Dismiss">✕</button>
    </div>
  );
}

/** Settings → Look → What's new: the last 5 notes, including ones already dismissed. */
export function WhatsNew() {
  return (
    <ul className="divide-y divide-gray-100">
      {NOTES.slice(0, 5).map((n) => (
        <li key={n.id} className="py-2">
          <p className="text-sm font-medium text-gray-800">{n.title}</p>
          <p className="text-sm text-gray-600">{n.body}</p>
          {n.link && <a href={n.link} target="_blank" rel="noopener noreferrer" className="text-sm text-sworkr-600 hover:underline">{n.linkLabel || 'Open'}</a>}
        </li>
      ))}
    </ul>
  );
}
