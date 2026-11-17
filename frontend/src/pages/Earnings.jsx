import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import Modal, { buttonClass, errorMessage, quietButtonClass } from '../components/Modal';
import TourForm from '../components/TourForm';
import AppointmentForm from '../components/AppointmentForm';
import { AppointmentItem } from './AppointmentCalendar';
import { useCategories } from '../api';
import { usePersonas } from '../components/Personas';
import { TourPlanning } from '../components/TourPlan';
import { useTestKinds } from '../components/TestKinds';
import FoundViaCompare from '../components/FoundVia';
import BusyTimes from '../components/BusyTimes';
import {
  CHART, dayLabel, fromDateInput, INCOME_KINDS, money, moneyShort, toDateInput, TOUR_COLOR,
} from '../colors';

const VIEWS = [
  { id: 'tour', label: 'By tour' },
  { id: 'month', label: 'By month' },
  { id: 'week', label: 'By week' },
  { id: 'work', label: 'By type of work' },
  { id: 'place', label: 'By place' },
  { id: 'persona', label: 'By persona', needsPersonas: true },
  { id: 'found', label: 'By how they found you' },
  { id: 'busy', label: 'Busy times' },
];
const BY_SOURCE = { work: 'work_type', place: 'source', persona: 'persona' };
const METRICS = [
  { id: 'profit', label: 'Profit' },
  { id: 'profit_per_day', label: 'Profit per working day' },
  { id: 'income', label: 'Income' },
];
const shortDay = (value) => dayLabel(fromDateInput(value), { month: 'short', day: 'numeric' });
const dateSpan = (first, last) => (first === last ? shortDay(first) : `${shortDay(first)} – ${shortDay(last)}`);
const rowLabel = (by, row) => (by === 'month'
  ? fromDateInput(`${row.key}-01`).toLocaleDateString(undefined, { month: 'long' })
  : `Week of ${shortDay(row.start_date)}`);

/**
 * Compare earnings: one tour against another, or (for full-time work) one month or week against another.
 * Every comparison counts working days, so days off and vacations don't make a stretch look worse.
 */
export default function Earnings() {
  const { labels: TEST_TYPES } = useTestKinds();
  const thisYear = new Date().getFullYear();
  const [view, setView] = useState(null); // decided once the "How I work" setting has loaded
  const personas = usePersonas();
  const [year, setYear] = useState(thisYear);
  const [metric, setMetric] = useState('profit');
  const [tours, setTours] = useState([]);
  const [rows, setRows] = useState([]);
  const [sourceData, setSourceData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [openTour, setOpenTour] = useState(null); // a tour id
  const [modal, setModal] = useState(null);
  const [version, setVersion] = useState(0); // bumped after every change, so the open tour reloads too

  useEffect(() => {
    axios.get('/api/account/settings')
      .then(({ data }) => setView(data.work_style === 'full_time' ? 'month' : 'tour'))
      .catch(() => setView('tour'));
  }, []);

  const load = useCallback(async () => {
    if (!view) return;
    if (view === 'found' || view === 'busy') { setLoading(false); return; }   // that view loads its own figures
    setLoading(true);
    try {
      if (view === 'tour') {
        const { data } = await axios.get('/api/tours/summary');
        setTours(data);
      } else if (BY_SOURCE[view]) {
        const { data } = await axios.get('/api/earnings/by-source', {
          params: { group: BY_SOURCE[view], start: new Date(year, 0, 1).toISOString(), end: new Date(year + 1, 0, 1).toISOString() },
        });
        setSourceData(data);
      } else {
        const { data } = await axios.get('/api/earnings/compare', {
          params: {
            by: view,
            start: new Date(year, 0, 1).toISOString(),
            end: new Date(year + 1, 0, 1).toISOString(),
            tz_offset: new Date(year, 6, 1).getTimezoneOffset(),
          },
        });
        setRows(data.rows);
      }
      setError('');
    } catch (err) {
      if (err?.response?.status !== 401) setError(errorMessage(err, "Couldn't load your earnings."));
    } finally {
      setLoading(false);
    }
  }, [view, year]);

  useEffect(() => { load(); }, [load]);

  // Weeks and months still to come are left out, so the list ends at today.
  const today = toDateInput(new Date());
  const items = useMemo(() => (view === 'tour'
    ? tours.map((t) => ({ id: t.id, label: t.name, sub: dateSpan(t.start_date, t.end_date), figures: t.figures, tour: t }))
    : rows.filter((r) => r.start_date <= today).map((r) => ({
      id: r.key, label: rowLabel(view, r), sub: dateSpan(r.start_date, r.end_date), figures: r.figures,
    })).reverse()), [view, tours, rows, today]);

  const closeAndReload = () => { setModal(null); load(); setVersion((v) => v + 1); };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold text-gray-800">Compare earnings</h2>
            {view && view !== 'tour' && (
              <span className="flex items-center gap-1">
                <button onClick={() => setYear(year - 1)} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600" aria-label="Previous year">←</button>
                <span className="font-semibold text-gray-700">{year}</span>
                <button onClick={() => setYear(year + 1)} disabled={year >= thisYear} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600 disabled:opacity-30" aria-label="Next year">→</button>
              </span>
            )}
            {loading && <span className="w-4 h-4 animate-spin border-2 rounded-full border-sworkr-500/20 border-t-sworkr-500" role="status" aria-label="Loading" />}
          </div>
          <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full">
            <div className="flex max-w-full overflow-x-auto rounded-lg border border-gray-200 whitespace-nowrap" role="group" aria-label="Compare">
              {VIEWS.filter((v) => !v.needsPersonas || personas.length > 0).map((v) => (
                <button
                  key={v.id}
                  onClick={() => { setView(v.id); setOpenTour(null); }}
                  aria-pressed={view === v.id}
                  className={`px-3 py-1.5 text-sm ${view === v.id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                >
                  {v.label}
                </button>
              ))}
            </div>
            {view === 'tour' && (
              <button onClick={() => setModal({ newTour: true })} className="px-4 py-1.5 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600">
                + New tour
              </button>
            )}
          </div>
        </div>

        {error && <p className="mb-3 text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">{error}</p>}

        {view === 'found' ? (
          <FoundViaCompare year={year} />
        ) : view === 'busy' ? (
          <BusyTimes year={year} />
        ) : BY_SOURCE[view] ? (
          <SourceCompare data={sourceData} byWork={view === 'work'} year={year} />
        ) : view && !loading && items.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-10">
            {view === 'tour'
              ? 'No tours yet. Add one here or from the calendar (+ New → Tour), and everything you book during it is counted.'
              : `Nothing recorded for ${year} yet.`}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1 mb-3" role="group" aria-label="Compare by">
              {METRICS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMetric(m.id)}
                  aria-pressed={metric === m.id}
                  className={`px-3 py-1 rounded-full text-xs font-medium border ${
                    metric === m.id ? 'bg-sworkr-500/20 text-sworkr-600 border-sworkr-300' : 'text-gray-500 hover:text-gray-700 border-gray-200'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <CompareBars
              items={items}
              metric={metric}
              selected={openTour}
              onPick={view === 'tour' ? (item) => setOpenTour(item.id === openTour ? null : item.id) : null}
            />
            <CompareTable items={items} firstColumn={view === 'tour' ? 'Tour' : view === 'month' ? 'Month' : 'Week'} onPick={view === 'tour' ? (item) => setOpenTour(item.id) : null} />
          </>
        )}
      </div>

      {view === 'tour' && openTour && (
        <TourDetail
          key={openTour}
          tourId={openTour}
          version={version}
          onEdit={(tour) => setModal({ tour })}
          onAddTest={(tour, testType) => setModal({ test: { tour, testType } })}
          onOpenAppointment={(a) => setModal({ appointment: a })}
          onChanged={() => { load(); setVersion((v) => v + 1); }}
        />
      )}

      {modal && (modal.tour || modal.newTour) && (
        <Modal title={modal.tour ? 'Edit tour' : 'New tour'} onClose={() => setModal(null)}>
          <TourForm
            period={modal.tour}
            defaultKind="tour"
            onSaved={(saved) => { closeAndReload(); if (saved?.id) setOpenTour(saved.id); }}
            onDeleted={() => { setOpenTour(null); closeAndReload(); }}
          />
        </Modal>
      )}
      {modal && (modal.test || modal.appointment) && (
        <Modal title={modal.appointment ? 'Edit' : `New ${(TEST_TYPES[modal.test.testType] || 'health test').toLowerCase()}`} onClose={() => setModal(null)}>
          <AppointmentForm
            appointment={modal.appointment}
            defaultKind="test"
            defaultTestType={modal.test?.testType}
            defaultTourId={modal.test?.tour.id}
            defaultDate={modal.test ? testDefaultDate(modal.test.tour) : undefined}
            onSaved={closeAndReload}
            onDeleted={closeAndReload}
          />
        </Modal>
      )}
    </div>
  );
}

/** Income from each type of work (or each workplace or platform), with its share of the total. */
function SourceCompare({ data, byWork, year }) {
  if (!data) return null;
  if (data.rows.length === 0) {
    return <p className="text-sm text-gray-400 text-center py-10">No income recorded for {year} yet.</p>;
  }
  const top = Math.max(...data.rows.map((r) => Math.abs(r.net)), 0) || 1;
  const pending = data.rows.reduce((sum, r) => sum + r.pending, 0);
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        What you kept from each {byWork ? 'type of work' : 'workplace or platform'} in {year}, after the venue's or platform's fees.
        {byWork && ' Bookings on the calendar count as in-person work. Set the type of work for each workplace or platform on the Income & expenses tab.'}
      </p>
      <ul className="space-y-2">
        {data.rows.map((r) => (
          <li key={r.key} className="flex items-center gap-3">
            <span className="w-32 sm:w-48 shrink-0 text-sm font-medium text-gray-800 truncate" title={r.label}>{r.label}</span>
            <span className="relative flex-1 h-6 bg-gray-50 rounded">
              <span className="absolute inset-y-0 left-0 rounded" style={{ width: `${(Math.max(r.net, 0) / top) * 100}%`, background: r.net < 0 ? CHART.expenses : CHART.income }} />
            </span>
            <span className={`w-24 text-right text-sm font-semibold ${r.net < 0 ? 'text-red-600' : 'text-gray-800'}`}>
              {money(r.net)}
              {r.share != null && <span className="block text-[11px] font-normal text-gray-400">{Math.round(r.share * 100)}%</span>}
            </span>
          </li>
        ))}
      </ul>
      <div className="overflow-x-auto -mx-4 sm:mx-0 px-4 sm:px-0">
        <table className="w-full text-sm min-w-[560px]">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
              <th className="py-1.5 pr-2 font-medium">{byWork ? 'Type of work' : 'Place'}</th>
              <th className="py-1.5 px-1 font-medium text-right">Payments</th>
              <th className="py-1.5 px-1 font-medium text-right">Before fees</th>
              <th className="py-1.5 px-1 font-medium text-right">Fees</th>
              <th className="py-1.5 px-1 font-medium text-right">You kept</th>
              <th className="py-1.5 px-1 font-medium text-right">Per payment</th>
              <th className="py-1.5 px-1 font-medium text-right">Share</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.key} className="border-b border-gray-50">
                <td className="py-1.5 pr-2 text-gray-800">
                  {r.label}
                  {r.pending > 0 && <span className="block text-[11px] text-amber-700">+{money(r.pending)} pending</span>}
                </td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.entries}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{money(r.gross)}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.fees ? money(r.fees) : '—'}</td>
                <td className={`py-1.5 px-1 text-right font-semibold ${r.net < 0 ? 'text-red-600' : 'text-gray-800'}`}>{money(r.net)}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.per_entry == null ? '—' : money(r.per_entry)}</td>
                <td className="py-1.5 px-1 text-right text-gray-600">{r.share == null ? '—' : `${Math.round(r.share * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-gray-200 font-semibold text-gray-800">
              <td className="py-1.5 pr-2">Total</td>
              <td className="py-1.5 px-1 text-right">{data.rows.reduce((s, r) => s + r.entries, 0)}</td>
              <td className="py-1.5 px-1 text-right">{money(data.rows.reduce((s, r) => s + r.gross, 0))}</td>
              <td className="py-1.5 px-1 text-right">{money(data.rows.reduce((s, r) => s + r.fees, 0))}</td>
              <td className="py-1.5 px-1 text-right">{money(data.total)}</td>
              <td className="py-1.5 px-1" />
              <td className="py-1.5 px-1 text-right">100%</td>
            </tr>
          </tfoot>
        </table>
      </div>
      {pending > 0 && <p className="text-xs text-gray-500">{money(pending)} more is earned but not paid out yet, and isn't counted above.</p>}
    </div>
  );
}

/** A new test on a tour starts on today if today is in the tour, otherwise on its first day, at 10 am. */
function testDefaultDate(tour) {
  const todayKey = toDateInput(new Date());
  const day = tour.start_date <= todayKey && tour.end_date >= todayKey ? new Date() : fromDateInput(tour.start_date);
  day.setHours(10, 0, 0, 0);
  return day;
}

const metricValue = (figures, metric) => figures[metric] ?? 0;

/** One horizontal bar per tour (or month, or week). Losses go left of the line, in red. */
function CompareBars({ items, metric, selected, onPick }) {
  const values = items.map((i) => metricValue(i.figures, metric));
  const top = Math.max(...values.map(Math.abs), 0);
  const hasNegative = values.some((v) => v < 0);
  const best = values.length > 1 ? Math.max(...values) : null;
  const metricName = METRICS.find((m) => m.id === metric).label.toLowerCase();
  if (top === 0) return <p className="text-sm text-gray-400 py-4">No {metricName} to compare yet.</p>;
  return (
    <ul className="space-y-1.5 mb-5" aria-label={`${METRICS.find((m) => m.id === metric).label} compared. The table below has every number.`}>
      {items.map((item, i) => {
        const v = values[i];
        const width = `${(Math.abs(v) / top) * (hasNegative ? 50 : 100)}%`;
        const Row = onPick ? 'button' : 'div';
        return (
          <li key={item.id}>
            <Row
              {...(onPick ? { onClick: () => onPick(item), 'aria-pressed': selected === item.id } : {})}
              className={`w-full flex items-center gap-2 sm:gap-3 rounded-lg px-1.5 py-1 text-left ${onPick ? 'hover:bg-gray-50' : ''} ${selected === item.id ? 'bg-sworkr-50' : ''}`}
            >
              <span className="w-24 sm:w-40 shrink-0 min-w-0">
                <span className="block text-sm font-medium text-gray-800 truncate">{item.label}</span>
                <span className="block text-[11px] text-gray-400 truncate">{item.sub}</span>
              </span>
              <span className="relative flex-1 h-5">
                {hasNegative && <span className="absolute left-1/2 top-0 bottom-0 border-l border-gray-300" />}
                <span
                  className="absolute top-0.5 bottom-0.5 rounded"
                  style={{
                    width,
                    background: v < 0 ? CHART.expenses : CHART.income,
                    ...(hasNegative ? (v < 0 ? { right: '50%' } : { left: '50%' }) : { left: 0 }),
                  }}
                />
              </span>
              <span className={`w-20 sm:w-24 shrink-0 text-right text-sm font-semibold ${v < 0 ? 'text-red-600' : 'text-gray-800'}`}>
                {item.figures[metric] == null ? '—' : money(v)}
                {best !== null && v === best && v > 0 && <span className="ml-1" title="The best one">★</span>}
              </span>
            </Row>
          </li>
        );
      })}
    </ul>
  );
}

const COLUMNS = [
  { id: 'working_days', label: 'Working days', fmt: (f) => (f.days_off ? `${f.working_days} of ${f.days}` : f.days) },
  { id: 'appointments', label: 'Bookings', fmt: (f) => f.appointments },
  { id: 'income', label: 'Income', fmt: (f) => money(f.income) },
  { id: 'room_rent', label: 'Room & board', fmt: (f) => money(f.room_rent) },
  { id: 'tests', label: 'Tests', fmt: (f) => money(f.tests) },
  { id: 'other_expenses', label: 'Other costs', fmt: (f) => money(f.other_expenses) },
  { id: 'profit', label: 'Profit', fmt: (f) => money(f.profit), strong: true },
  { id: 'profit_per_day', label: 'Per working day', fmt: (f) => (f.profit_per_day == null ? '—' : money(f.profit_per_day)) },
];

function CompareTable({ items, firstColumn, onPick }) {
  const [sort, setSort] = useState(null); // { id, dir }
  const sorted = useMemo(() => {
    if (!sort) return items;
    return [...items].sort((a, b) => ((a.figures[sort.id] ?? -Infinity) - (b.figures[sort.id] ?? -Infinity)) * sort.dir);
  }, [items, sort]);
  const totals = useMemo(() => {
    const t = { income: 0, room_rent: 0, tests: 0, other_expenses: 0, profit: 0, appointments: 0, days: 0, days_off: 0, working_days: 0 };
    for (const i of items) for (const k of Object.keys(t)) t[k] += i.figures[k] || 0;
    t.profit_per_day = t.working_days ? t.profit / t.working_days : null;
    return t;
  }, [items]);
  const sortBy = (id) => setSort((s) => (s?.id === id ? (s.dir === -1 ? { id, dir: 1 } : null) : { id, dir: -1 }));

  return (
    <div className="overflow-x-auto -mx-4 sm:mx-0 px-4 sm:px-0">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
            <th className="py-1.5 pr-2 font-medium">{firstColumn}</th>
            {COLUMNS.map((c) => (
              <th key={c.id} className="py-1.5 px-1 font-medium text-right" aria-sort={sort?.id === c.id ? (sort.dir === -1 ? 'descending' : 'ascending') : 'none'}>
                <button onClick={() => sortBy(c.id)} className="hover:text-gray-800">
                  {c.label}{sort?.id === c.id ? (sort.dir === -1 ? ' ↓' : ' ↑') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((item) => (
            <tr key={item.id} className={`border-b border-gray-50 ${onPick ? 'cursor-pointer hover:bg-gray-50' : ''}`} onClick={onPick ? () => onPick(item) : undefined}>
              <td className="py-1.5 pr-2">
                <span className="text-gray-800 font-medium">{item.label}</span>
                <span className="block text-[11px] text-gray-400">{item.sub}</span>
              </td>
              {COLUMNS.map((c) => (
                <td key={c.id} className={`py-1.5 px-1 text-right ${c.strong ? `font-semibold ${item.figures.profit < 0 ? 'text-red-600' : 'text-gray-800'}` : 'text-gray-600'}`}>
                  {c.fmt(item.figures)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {items.length > 1 && (
          <tfoot>
            <tr className="border-t border-gray-200 font-semibold text-gray-800">
              <td className="py-1.5 pr-2">Total</td>
              {COLUMNS.map((c) => <td key={c.id} className="py-1.5 px-1 text-right">{c.fmt(totals)}</td>)}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

/**
 * A tour at one of your workplaces: what you earned there, the house's share, what it charged you, and so what
 * you should be paid. For checking against the house's own sheet.
 */
function StayStatement({ statement: s }) {
  const row = (label, value, opts = {}) => (
    <div key={opts.key || label} className={`flex justify-between gap-3 py-1 ${opts.strong ? 'font-semibold text-gray-900 border-t border-gray-200 mt-1 pt-2' : 'text-gray-700'}`}>
      <dt className={opts.indent ? 'pl-4 text-gray-500' : ''}>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
  return (
    <section className="rounded-xl border border-gray-100 bg-gray-50/60 p-4">
      <h3 className="font-semibold text-gray-800">Tour statement · {s.place.name}</h3>
      <p className="text-xs text-gray-500 mb-2">Income and bookings logged at this place during the tour, and the charges logged for it.</p>
      <dl className="text-sm max-w-md">
        {row('Earned', money(s.gross))}
        {row(`House share${s.place.fee_percent ? ` (${s.place.fee_percent}%)` : ''}`, `− ${money(s.house_share)}`)}
        {s.charges.map((c) => row(`${c.label}${c.count > 1 ? ` × ${c.count}` : ''}`, `− ${money(c.total)}`, { indent: true }))}
        {s.charges.length === 0 && row('Charges', money(0), { indent: true })}
        {row('You should get', money(s.take_home), { strong: true })}
        {s.received > 0 && row('Logged as received so far', money(s.received))}
      </dl>
    </section>
  );
}

function TourDetail({ tourId, version, onEdit, onAddTest, onOpenAppointment, onChanged }) {
  const { options: TEST_TYPES } = useTestKinds();
  const cats = useCategories();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      const { data: summary } = await axios.get(`/api/tours/${tourId}/summary`);
      setData(summary);
      setError('');
    } catch (err) {
      setError(errorMessage(err, "Couldn't load this tour."));
    }
  }, [tourId]);
  useEffect(() => { load(); }, [load, version]);

  const act = async (request) => {
    try { await request(); } catch (err) { console.error(err); }
    onChanged();
  };
  const actions = {
    open: onOpenAppointment,
    status: (a, status, extra = {}) => act(() => axios.put(`/api/appointments/${a.id}/status`, null, { params: { status, ...extra } })),
    paid: (a) => act(() => axios.post(`/api/appointments/${a.id}/mark-paid`)),
    checkIn: (a) => act(() => axios.post(`/api/appointments/${a.id}/check-in`)),
  };

  if (error) return <div className="bg-white rounded-2xl shadow-lg p-5 text-sm text-red-700">{error}</div>;
  if (!data) return <div className="bg-white rounded-2xl shadow-lg p-5 text-sm text-gray-400">Loading…</div>;
  const { tour, figures: f, appointments, expenses, income = [], statement } = data;

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold" style={{ color: TOUR_COLOR }}>✈ {tour.name}</h2>
          <p className="text-sm text-gray-500">
            {dateSpan(tour.start_date, tour.end_date)} · {f.days} day{f.days === 1 ? '' : 's'}
            {f.days_off > 0 && ` (${f.days_off} off)`}
            {tour.location && ` · ${tour.location}`}
            {tour.room_rent_per_day > 0 && ` · room & board ${money(tour.room_rent_per_day)}/day`}
          </p>
          {tour.notes && <p className="text-sm text-gray-500 mt-1 whitespace-pre-wrap">{tour.notes}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(TEST_TYPES).map(([type, label]) => (
            <button key={type} onClick={() => onAddTest(tour, type)} className={quietButtonClass}>+ {label}</button>
          ))}
          <button onClick={() => onEdit(tour)} className={buttonClass}>Edit tour</button>
        </div>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Tile label="Income" value={money(f.income)} hint={f.owed > 0 ? `${money(f.owed)} still owed` : `${f.appointments} booking${f.appointments === 1 ? '' : 's'}`} />
        <Tile label="Expenses" value={money(f.expenses)} hint={`Room & board ${moneyShort(f.room_rent)} · tests ${moneyShort(f.tests)} · other ${moneyShort(f.other_expenses)}`} />
        <Tile label="Profit" value={money(f.profit)} strong negative={f.profit < 0} />
        <Tile label="Per working day" value={f.profit_per_day == null ? '—' : money(f.profit_per_day)} hint={`${f.working_days} working day${f.working_days === 1 ? '' : 's'}`} />
      </dl>

      {statement && <StayStatement statement={statement} />}

      <TourPlanning tour={tour} version={version} />

      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="font-semibold text-gray-800 mb-2">Bookings and tests</h3>
          {appointments.length === 0 ? (
            <p className="text-sm text-gray-400">Nothing booked during this tour yet.</p>
          ) : (
            <ul className="space-y-2">
              {appointments.map((a) => <AppointmentItem key={a.id} appointment={a} actions={actions} showDate />)}
            </ul>
          )}
        </div>
        <div>
          <h3 className="font-semibold text-gray-800 mb-2">Expenses</h3>
          {expenses.length === 0 ? (
            <p className="text-sm text-gray-400">No expenses on this tour.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {expenses.map((e) => (
                <li key={e.id} className="flex items-center gap-3 py-2 text-sm">
                  <span className="text-gray-500 w-14 shrink-0">{dayLabel(new Date(e.date), { month: 'short', day: 'numeric' })}</span>
                  <span className="flex-1 min-w-0 truncate text-gray-800">{e.description}</span>
                  <span className="flex items-center gap-1.5 text-xs text-gray-500">
                    <span className="w-2 h-2 rounded-full" style={{ background: cats.color(e.category) }} />
                    {cats.label(e.category)}
                  </span>
                  <span className="w-20 text-right font-medium text-gray-800">{money(e.amount)}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-gray-400 mt-2">Expenses count here when they're put on this tour, or dated during it and on no other tour.</p>
          {income.length > 0 && (
            <>
              <h3 className="font-semibold text-gray-800 mt-5 mb-2">Other income</h3>
              <ul className="divide-y divide-gray-100">
                {income.map((r) => (
                  <li key={r.id} className="flex items-center gap-3 py-2 text-sm">
                    <span className="text-gray-500 w-14 shrink-0">{dayLabel(new Date(r.date), { month: 'short', day: 'numeric' })}</span>
                    <span className="flex-1 min-w-0 truncate text-gray-800">{r.description || INCOME_KINDS[r.kind]}{r.source_name && <span className="text-gray-400"> · {r.source_name}</span>}</span>
                    {r.status === 'pending' && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">Pending</span>}
                    <span className="w-20 text-right font-medium text-gray-800">{money(r.net, r.currency)}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-gray-400 mt-2">Pending payouts count once they're marked as paid out.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Tile({ label, value, hint, strong, negative }) {
  return (
    <div className={`rounded-xl border px-3 py-2.5 ${strong ? 'border-sworkr-200 bg-sworkr-50' : 'border-gray-100'}`}>
      <dt className="text-[11px] uppercase tracking-wide text-gray-500">{label}</dt>
      <dd className={`text-xl font-bold ${negative ? 'text-red-600' : 'text-gray-800'}`}>{value}</dd>
      {hint && <dd className="text-[11px] text-gray-400">{hint}</dd>}
    </div>
  );
}
