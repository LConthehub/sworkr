export const PALETTE = ['#fc4c9c', '#e67eb6', '#a73178', '#542b5c', '#4b86a6'];

export const CATEGORY_COLORS = {
  equipment: '#fc4c9c',
  marketing: '#e67eb6',
  travel: '#a73178',
  cleaning: '#542b5c',
  other: '#4b86a6',
};

export function colorFor(text = '') {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

export function formatDuration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h && m) return `${h}h ${m}m`;
  if (h) return `${h}h`;
  return `${m}min`;
}

export const money = (n) => `$${Number(n || 0).toFixed(2)}`;

export const STATUS_STYLES = {
  scheduled: { label: 'Scheduled', badge: 'bg-sworkr-50 text-sworkr-600' },
  completed: { label: 'Completed', badge: 'bg-emerald-100 text-emerald-700' },
  cancelled: { label: 'Cancelled', badge: 'bg-gray-100 text-gray-500 line-through' },
};

// ----- dates (all in the browser's local time) -----
const pad = (n) => String(n).padStart(2, '0');

export const toDateInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const toTimeInput = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** "2026-11-12" + "19:30" → a Date in local time. */
export function fromDateTimeInputs(date, time) {
  const [y, mo, d] = date.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);
  return new Date(y, mo - 1, d, h, mi);
}

export const sameDay = (a, b) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export const formatTime = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** The 6-week grid (Sunday start) that contains the given month. */
export function monthGrid(month) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first);
  start.setDate(1 - first.getDay());
  return [...Array(42)].map((_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
}
