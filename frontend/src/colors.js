export const PALETTE = ['#fc4c9c', '#e67eb6', '#a73178', '#542b5c', '#4b86a6'];

export const CATEGORY_COLORS = {
  workspace: '#c2410c', fees: '#b45309', health: '#0f9488', wardrobe: '#fc4c9c', gear: '#7c3aed',
  marketing: '#e67eb6', travel: '#a73178', fitness: '#65a30d', other: '#4b86a6',
  room_rent: '#c2410c', cleaning: '#c2410c', medical: '#0f9488', equipment: '#7c3aed',
};

// Expense categories are each user's own (useCategories in api.js). These are only the fallbacks for the
// built-in ones, used before that list has loaded.
export const CATEGORY_LABELS = {
  workspace: 'Workspace', fees: 'Fees & licenses', health: 'Health & safety', wardrobe: 'Look & wardrobe',
  gear: 'Gear & tech', marketing: 'Marketing', travel: 'Travel', fitness: 'Fitness & training', other: 'Other',
  room_rent: 'Room & board', cleaning: 'Cleaning & laundry', medical: 'Tests & doctor', equipment: 'Equipment & toys',
};
export const categoryLabel = (c) => CATEGORY_LABELS[c] || c;

export const INCOME_KINDS = {
  shift: 'Shift', payout: 'Payout', tips: 'Tips', sale: 'Sale (PPV, custom, clips)', subscription: 'Subscriptions',
  booking: 'Booking (paid outside the calendar)', allowance: 'Allowance', gift: 'Gift', other: 'Other',
};
export const SOURCE_KINDS = {
  brothel: 'Brothel', club: 'Club or bar', agency: 'Agency', platform: 'Platform or site', phone: 'Phone or chat line',
  studio: 'Dungeon or studio', event: 'Event or convention', other: 'Other',
};
// How often a place charges you. Read as "$120 a day".
export const CADENCES = {
  per_booking: 'a booking', per_shift: 'a shift', per_day: 'a day', per_week: 'a week', per_month: 'a month',
  per_quarter: 'a quarter', per_year: 'a year', per_stay: 'a stay', once: 'once',
};
export const GOAL_COLORS = ['#059669', '#4f46e5', '#db2777', '#0284c7', '#d97706', '#7c3aed', '#65a30d', '#c2410c'];

// ----- health tests, tours and time off -----
export const TEST_TYPES = { weekly: 'Weekly test', monthly: 'Monthly test', yearly: 'Yearly test' };
export const TEST_COLOR = '#0f9488';
export const TOUR_COLOR = '#7c3aed';
export const TIME_OFF_LABELS = { day_off: 'Day off', vacation: 'Vacation' };
export const periodLabel = (p) => (p.kind === 'tour'
  ? p.name
  : [TIME_OFF_LABELS[p.time_off_type] || 'Time off', p.name].filter(Boolean).join(' · '));

/** "2026-03-05" → a local Date at midnight. */
export const fromDateInput = (value) => {
  const [y, m, d] = value.split('-').map(Number);
  return new Date(y, m - 1, d);
};

/** The request body for a tour or time off: its local days, and the same days as exact times. */
export function periodTimes(startDate, endDate) {
  const start = fromDateInput(startDate);
  const end = fromDateInput(endDate);
  const after = new Date(end.getFullYear(), end.getMonth(), end.getDate() + 1);
  return { start_date: startDate, end_date: endDate, starts_at: start.toISOString(), ends_at: after.toISOString() };
}

/** Whole days from first to last, counting both. */
export const daysBetween = (startDate, endDate) =>
  Math.round((fromDateInput(endDate) - fromDateInput(startDate)) / 86400000) + 1;

/** Tours or time off that cover a given local day. */
export const periodsOn = (periods, day) => {
  const key = toDateInput(day);
  return periods.filter((p) => p.start_date <= key && p.end_date >= key);
};

/** Days until the next birthday (0 = today), and the age the client turns then. */
export function nextBirthday(birthday, today = new Date()) {
  if (!birthday) return null;
  const [y, m, d] = birthday.split('-').map(Number);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  let next = new Date(start.getFullYear(), m - 1, d);
  if (next < start) next = new Date(start.getFullYear() + 1, m - 1, d);
  return { days: Math.round((next - start) / 86400000), turns: next.getFullYear() - y, date: next };
}

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

/**
 * Currencies sworkr can show. Every amount the server sends has a currency code with it; only USD is used
 * for now. To add one, add it here and in backend/currencies.py.
 */
export const CURRENCIES = {
  USD: { symbol: '$', decimals: 2 },
};

export const money = (n, currency = 'USD') => {
  const value = Number(n || 0);
  const c = CURRENCIES[currency] || CURRENCIES.USD;
  return `${value < 0 ? '-' : ''}${c.symbol}${Math.abs(value).toFixed(c.decimals)}`;
};

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

export const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes());
/** The Sunday that starts the week containing d. */
export const startOfWeek = (d) => addDays(startOfDay(d), -d.getDay());
export const endOf = (appt) => new Date(new Date(appt.scheduled_date).getTime() + appt.duration_minutes * 60000);

export const dayLabel = (d, opts = { weekday: 'long', month: 'short', day: 'numeric' }) =>
  d.toLocaleDateString(undefined, opts);

/** Whole amounts for tight spaces: $1,250 */
export const moneyShort = (n, currency = 'USD') =>
  `${(CURRENCIES[currency] || CURRENCIES.USD).symbol}${Math.round(Number(n || 0)).toLocaleString()}`;

export const PAYMENT_STYLES = {
  none: null,
  unpaid: { label: 'Unpaid', badge: 'bg-amber-100 text-amber-800' },
  partial: { label: 'Part paid', badge: 'bg-amber-100 text-amber-800' },
  paid: { label: 'Paid', badge: 'bg-emerald-100 text-emerald-700' },
};

export const SCREENING_STYLES = {
  unscreened: { label: 'Not screened', badge: 'bg-gray-100 text-gray-600' },
  pending: { label: 'Screening pending', badge: 'bg-amber-100 text-amber-800' },
  verified: { label: 'Verified', badge: 'bg-emerald-100 text-emerald-700' },
  declined: { label: 'Declined', badge: 'bg-red-100 text-red-700' },
};

export const LOCATION_LABELS = { incall: 'Incall', outcall: 'Outcall', other: 'Other' };

/** Start times for a repeating appointment, in local time so the clock time never drifts. */
export function repeatDates(first, every, count) {
  const dates = [];
  for (let i = 1; i < count; i++) {
    const d = new Date(first);
    if (every === 'day') d.setDate(first.getDate() + i);
    else if (every === '3days') d.setDate(first.getDate() + 3 * i);
    else if (every === 'week') d.setDate(first.getDate() + 7 * i);
    else if (every === '2weeks') d.setDate(first.getDate() + 14 * i);
    else if (every === 'month') {
      d.setDate(1);
      d.setMonth(first.getMonth() + i);
      // the 31st in a shorter month becomes that month's last day
      const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
      d.setDate(Math.min(first.getDate(), lastDay));
    }
    dates.push(d);
  }
  return dates;
}

// Chart colors, checked for colorblind-safe separation on a white background.
export const CHART = { income: '#1789c4', expenses: '#d6336c' };

/** A booking's colour: grey once done, teal for a health test, otherwise by service. */
export const apptColorFor = (a) => (a.status === 'completed' ? '#6b7280' : a.kind === 'test' ? TEST_COLOR : colorFor(a.service_type));
