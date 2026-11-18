import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ReceiptMaker } from '../components/Receipts';
import { BookingReview } from '../components/ClientProfile';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import Modal from '../components/Modal';
import AppointmentForm from '../components/AppointmentForm';
import TourForm from '../components/TourForm';
import { TaskForm, TaskItem, TasksPanel } from '../components/Tasks';
import { fetchAll } from '../api';
import { PostForm, PostRow } from './Content';
import { ShootForm } from '../components/Shoots';
import { CalendarSwitch, LayerToggles, PlannedChip, PlannedRow, useLayers, usePlanned } from '../components/PlannedItems';
import { CYCLE_LABELS, CycleDot, useCycleDays } from '../components/Cycle';
import {
  addDays, colorFor, dayLabel, endOf, formatDuration, formatTime, LOCATION_LABELS, money, monthGrid,
  PAYMENT_STYLES, periodLabel, periodsOn, sameDay, startOfDay, startOfWeek, STATUS_STYLES, TEST_COLOR, TOUR_COLOR,
} from '../colors';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const VIEWS = [
  { id: 'month', label: 'Month' },
  { id: 'week', label: 'Week' },
  { id: 'day', label: 'Day' },
  { id: 'list', label: 'List' },
];
const HOUR = 48; // pixels per hour in the week and day views
const toKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const LIST_DAYS = 30;

function useNarrowScreen() {
  const query = '(max-width: 639px)';
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const onChange = () => setNarrow(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return narrow;
}

function savedView() {
  try {
    return localStorage.getItem('sworkr.calendarView');
  } catch {
    return null;
  }
}

const apptColor = (a) => (a.status === 'completed' ? '#6b7280' : a.kind === 'test' ? TEST_COLOR : colorFor(a.service_type));
const apptTitle = (a) => (a.kind === 'test' ? `🩺 ${a.service_type}` : a.client_name);
// Grey diagonal stripes for days off and vacations.
const TIME_OFF_BACKGROUND = 'repeating-linear-gradient(135deg, rgba(107, 93, 112, 0.1) 0 6px, rgba(107, 93, 112, 0.22) 6px 8px)'; // see-through: works light and dark

/** The tour on a day (at most one) and any time off. */
function dayPeriods(periods, day) {
  const on = periodsOn(periods, day);
  return { tour: on.find((p) => p.kind === 'tour'), off: on.find((p) => p.kind === 'time_off') };
}

export default function AppointmentCalendar() {
  const narrow = useNarrowScreen();
  const [view, setViewState] = useState(() => {
    const saved = savedView();
    if (VIEWS.some((v) => v.id === saved)) return saved;
    return window.matchMedia?.('(max-width: 639px)').matches ? 'list' : 'month';
  });
  const [cursor, setCursor] = useState(() => startOfDay(new Date())); // the day the view is built around
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [showCancelled, setShowCancelled] = useState(false);
  const [modal, setModal] = useState(null); // { appointment } | { defaultDate, kind } | { period } | { newPeriod, defaultDate }
  const [periods, setPeriods] = useState([]); // tours and time off on screen
  const [workStyle, setWorkStyle] = useState('both');
  const [menuOpen, setMenuOpen] = useState(false);
  const [tourFigures, setTourFigures] = useState(null);
  const [tasks, setTasks] = useState([]);            // tasks due on the days on screen
  const [taskVersion, setTaskVersion] = useState(0); // bumped when tasks change, so the task list reloads

  useEffect(() => {
    axios.get('/api/account/settings').then(({ data }) => setWorkStyle(data.work_style || 'both')).catch(() => {});
  }, []);

  // A week of seven columns doesn't fit a phone: show the day instead.
  const shownView = narrow && view === 'week' ? 'day' : view;
  const setView = (v) => {
    setViewState(v);
    try { localStorage.setItem('sworkr.calendarView', v); } catch { /* private window */ }
  };

  // The days on screen.
  const days = useMemo(() => {
    if (shownView === 'month') return monthGrid(new Date(cursor.getFullYear(), cursor.getMonth(), 1));
    if (shownView === 'week') return [...Array(7)].map((_, i) => addDays(startOfWeek(cursor), i));
    if (shownView === 'list') return [...Array(LIST_DAYS)].map((_, i) => addDays(cursor, i));
    return [cursor];
  }, [shownView, cursor]);
  const rangeStart = days[0].getTime();
  const rangeEnd = addDays(days[days.length - 1], 1).getTime();

  // Planning on the same days: posts to put up, shoots, the day an ad runs out. Each kind can be switched off.
  const navigate = useNavigate();
  const [layers, toggleLayer] = useLayers();
  const [planVersion, setPlanVersion] = useState(0);
  const planned = usePlanned(rangeStart, rangeEnd, layers, planVersion);
  const plannedChanged = () => setPlanVersion((v) => v + 1);
  const openPlanned = (item) => {
    if (item.type === 'post') setModal({ post: item.raw });
    else if (item.type === 'shoot') navigate(`/calendar/shoots?shoot=${item.raw.id}`);
    else navigate('/content/campaigns');
  };
  const openNewPost = (when) => {
    const d = new Date(when);
    d.setHours(19, 0, 0, 0);
    setModal({ post: { scheduled_at: d.toISOString() } });
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Two days early, so a long booking that began before the first day still shows.
      const [data, tours, due] = await Promise.all([
        fetchAll('/api/appointments', {
          start: addDays(new Date(rangeStart), -2).toISOString(),
          end: new Date(rangeEnd).toISOString(),
        }, 1000),
        axios.get('/api/tours', { params: { start: new Date(rangeStart).toISOString(), end: new Date(rangeEnd).toISOString() } }),
        axios.get('/api/tasks', { params: { status: 'all', start: toKey(new Date(rangeStart)), end: toKey(new Date(rangeEnd)) } }),
      ]);
      setAppointments(data);
      setPeriods(tours.data);
      setTasks(due.data);
      setLoadError('');
    } catch (err) {
      if (err?.response?.status !== 401) setLoadError("Couldn't load appointments. Check that sworkr is running.");
    } finally {
      setLoading(false);
    }
  }, [rangeStart, rangeEnd]);

  useEffect(() => { load(); }, [load]);

  const visible = useMemo(
    () => appointments.filter((a) => showCancelled || a.status !== 'cancelled'),
    [appointments, showCancelled],
  );
  /** Appointments that are under way at some point on this day (so an overnight shows on both days). */
  const onDay = useCallback((day) => {
    const from = startOfDay(day).getTime();
    const to = addDays(startOfDay(day), 1).getTime();
    return visible.filter((a) => new Date(a.scheduled_date).getTime() < to && endOf(a).getTime() > from);
  }, [visible]);
  const startingOn = (day) => visible.filter((a) => sameDay(new Date(a.scheduled_date), day));

  const today = new Date();
  const step = (dir) => {
    if (shownView === 'month') setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + dir, 1));
    else if (shownView === 'week') setCursor(addDays(cursor, 7 * dir));
    else if (shownView === 'list') setCursor(addDays(cursor, LIST_DAYS * dir));
    else setCursor(addDays(cursor, dir));
  };
  const title = shownView === 'month'
    ? cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    : shownView === 'day'
      ? dayLabel(cursor, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
      : `${dayLabel(days[0], { month: 'short', day: 'numeric' })} – ${dayLabel(days[days.length - 1], { month: 'short', day: 'numeric', year: 'numeric' })}`;

  /** `exact` keeps the time given (a slot clicked in the time grid); otherwise a day gets the usual 7 pm (tests: 10 am). */
  const openNew = (when, exact = false, kind = 'client') => {
    const d = new Date(when);
    if (!exact) d.setHours(kind === 'test' ? 10 : 19, 0, 0, 0);
    setModal({ defaultDate: d, kind });
  };
  const openNewPeriod = (kind, when) => setModal({ newPeriod: kind, defaultDate: startOfDay(when) });
  const openPeriod = (period) => setModal({ period });
  const newMenuDay = shownView === 'list' || shownView === 'week' ? today : cursor;

  // The running money for the tour the chosen day is in.
  const cursorTour = dayPeriods(periods, cursor).tour;
  const cursorTourId = cursorTour?.id;
  useEffect(() => {
    setTourFigures(null);
    if (!cursorTourId) return;
    axios.get(`/api/tours/${cursorTourId}/summary`).then(({ data }) => setTourFigures(data.figures)).catch(() => {});
  }, [cursorTourId, appointments]);
  const cycle = useCycleDays(toKey(new Date(rangeStart)), toKey(new Date(rangeEnd)));
  const tasksOn = useCallback((day) => tasks.filter((t) => t.due_date === toKey(day)), [tasks]);
  // Dates that mark a day: a document running out, a renewal, the next shot or refill, an allowance or tax due.
  const [markers, setMarkers] = useState([]);
  const markerStart = toKey(new Date(rangeStart));
  const markerEnd = toKey(new Date(rangeEnd));
  useEffect(() => {
    axios.get('/api/calendar/dates', { params: { start: markerStart, end: markerEnd } })
      .then(({ data }) => setMarkers(data)).catch(() => setMarkers([]));
  }, [markerStart, markerEnd, taskVersion]);
  const markersOn = useCallback((day) => markers.filter((m) => m.date === toKey(day)), [markers]);
  const tasksChanged = () => { load(); setTaskVersion((v) => v + 1); };
  const toggleTask = async (task) => {
    await axios.post(`/api/tasks/${task.id}/done`, { done: !task.done }).catch(() => {});
    tasksChanged();
  };
  const openTask = (task, day) => setModal({ task, taskDay: day });
  const closeAndReload = () => {
    setModal(null);
    setTaskVersion((v) => v + 1);
    load();
    window.dispatchEvent(new Event('sworkr:appointments-changed')); // lets the check-in banner update at once
  };

  const act = async (request) => {
    try {
      await request();
    } catch (err) {
      console.error('Error updating appointment:', err);
    }
    load();
    window.dispatchEvent(new Event('sworkr:appointments-changed'));
  };
  const actions = {
    open: (a) => setModal({ appointment: a }),
    status: (a, status, extra = {}) => act(() => axios.put(`/api/appointments/${a.id}/status`, null, { params: { status, ...extra } })),
    paid: (a) => act(() => axios.post(`/api/appointments/${a.id}/mark-paid`)),
    checkIn: (a) => act(() => axios.post(`/api/appointments/${a.id}/check-in`)),
  };

  // Money at a glance for what's on screen (cancelled bookings only count what was actually paid).
  const totals = useMemo(() => {
    const inRange = appointments.filter((a) => {
      const t = new Date(a.scheduled_date).getTime();
      return t >= rangeStart && t < rangeEnd;
    });
    const live = inRange.filter((a) => a.status !== 'cancelled' && a.kind !== 'test');
    return {
      count: live.length,
      booked: live.reduce((sum, a) => sum + (a.rate || 0), 0),
      paid: inRange.reduce((sum, a) => sum + (a.amount_paid || 0), 0),
    };
  }, [appointments, rangeStart, rangeEnd]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Calendar</h1>
        <CalendarSwitch current="calendar" />
      </div>
      <div className="bg-white rounded-2xl shadow-lg p-3 sm:p-5">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-1 sm:gap-2">
            <button onClick={() => step(-1)} className="w-9 h-9 rounded-lg hover:bg-gray-100 text-gray-600" aria-label="Earlier">←</button>
            <h2 className="text-base sm:text-xl font-bold text-gray-800 sm:min-w-52 text-center">{title}</h2>
            <button onClick={() => step(1)} className="w-9 h-9 rounded-lg hover:bg-gray-100 text-gray-600" aria-label="Later">→</button>
            <button onClick={() => setCursor(startOfDay(today))} className="ml-1 px-3 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-600 hover:bg-gray-50">Today</button>
            {loading && <span className="w-4 h-4 animate-spin border-2 rounded-full border-sworkr-500/20 border-t-sworkr-500" role="status" aria-label="Loading" />}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden" role="group" aria-label="Calendar view">
              {VIEWS.filter((v) => !(narrow && v.id === 'week')).map((v) => (
                <button
                  key={v.id}
                  onClick={() => setView(v.id)}
                  aria-pressed={shownView === v.id}
                  className={`px-3 py-1.5 text-sm ${shownView === v.id ? 'bg-sworkr-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                >
                  {v.label}
                </button>
              ))}
            </div>
            <div className="relative">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                className="px-4 py-1.5 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600"
              >
                + New ▾
              </button>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-20" onClick={() => setMenuOpen(false)} aria-hidden="true" />
                  <div role="menu" className="absolute right-0 mt-1 z-30 w-48 rounded-xl bg-white shadow-lg border border-gray-100 py-1 text-sm">
                    {[
                      ['Appointment', () => openNew(newMenuDay)],
                      ['🩺 Health test', () => openNew(newMenuDay, false, 'test')],
                      ...(workStyle === 'full_time' ? [] : [['✈ Tour', () => openNewPeriod('tour', newMenuDay)]]),
                      ['Time off', () => openNewPeriod('time_off', newMenuDay)],
                      ['☐ Task', () => openTask(null, newMenuDay)],
                      ['📣 Post', () => openNewPost(newMenuDay)],
                      ['📷 Shoot', () => setModal({ shoot: { shoot_date: toKey(newMenuDay) } })],
                    ].map(([label, go]) => (
                      <button key={label} role="menuitem" onClick={() => { setMenuOpen(false); go(); }} className="block w-full text-left px-4 py-2 text-gray-700 hover:bg-gray-50">
                        {label}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {loadError && <p className="mb-3 text-sm rounded-lg px-3 py-2 bg-red-50 text-red-700">{loadError}</p>}

        {shownView === 'month' && (
          <MonthView
            days={days} cursor={cursor} today={today} narrow={narrow} onDay={onDay} periods={periods}
            onSelect={setCursor} onNew={openNew} onOpen={actions.open} tasksOn={tasksOn} cycle={cycle} markersOn={markersOn}
            plannedOn={planned.onDay} onOpenPlanned={openPlanned}
          />
        )}
        {(shownView === 'week' || shownView === 'day') && (
          <TimeGrid days={days} today={today} onDay={onDay} periods={periods} cycle={cycle} onNew={openNew} onOpen={actions.open} onOpenPeriod={openPeriod} onPickDay={(d) => { setCursor(d); setView('day'); }} plannedOn={planned.onDay} onOpenPlanned={openPlanned} />
        )}
        {shownView === 'list' && (
          <ListView days={days} today={today} startingOn={startingOn} periods={periods} cycle={cycle} actions={actions} onNew={openNew} onOpenPeriod={openPeriod}
            plannedOn={planned.onDay} onEditPost={(p) => setModal({ post: p })} onPlannedChanged={plannedChanged} />
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-xs text-gray-500">
          <span>
            {totals.count} appointment{totals.count === 1 ? '' : 's'}
            {totals.booked > 0 && <> · {money(totals.booked)} booked · {money(totals.paid)} received</>}
          </span>
          <LayerToggles layers={layers} onToggle={toggleLayer} />
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />
            Show cancelled
          </label>
        </div>
      </div>

      <div className={`grid gap-4 items-start ${shownView === 'month' || shownView === 'day' ? 'lg:grid-cols-[1fr_340px]' : ''}`}>
      {/* The chosen day, in full (month and day views) */}
      {(shownView === 'month' || shownView === 'day') && (
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="flex items-center gap-2 font-semibold text-gray-800">{dayLabel(cursor)}
              {cycle[toKey(cursor)] && <span className="flex items-center gap-1 text-xs font-normal text-gray-500"><CycleDot kind={cycle[toKey(cursor)]} />{CYCLE_LABELS[cycle[toKey(cursor)]]}</span>}
            </h2>
            <span className="flex gap-3">
              <button onClick={() => openTask(null, cursor)} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Task</button>
              <button onClick={() => openNewPost(cursor)} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Post</button>
              <button onClick={() => openNew(cursor)} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Add</button>
            </span>
          </div>
          {markersOn(cursor).length > 0 && (
            <ul className="mb-3 space-y-1">
              {markersOn(cursor).map((m, i) => (
                <li key={i} className="flex items-center gap-2 text-sm text-gray-700">
                  <span className="w-2 h-2 rotate-45 shrink-0" style={{ background: MARKER_COLORS[m.kind] || '#6b7280' }} />
                  {m.label}
                </li>
              ))}
            </ul>
          )}
          {periodsOn(periods, cursor).map((p) => (
            <button
              key={p.id}
              onClick={() => openPeriod(p)}
              className="w-full mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2 text-left text-sm hover:opacity-90"
              style={p.kind === 'tour' ? { background: '#f5f3ff', color: TOUR_COLOR } : { background: TIME_OFF_BACKGROUND, color: '#4b5563' }}
            >
              <span className="font-semibold">{p.kind === 'tour' ? `✈ ${p.name}` : periodLabel(p)}</span>
              <span className="text-xs opacity-80">{p.start_date === p.end_date ? p.start_date : `${p.start_date} – ${p.end_date}`}</span>
              {p.kind === 'tour' && tourFigures && p.id === cursorTourId && (
                <span className="text-xs ml-auto">
                  {money(tourFigures.income)} in · {money(tourFigures.expenses)} out · <strong>{money(tourFigures.profit)} profit</strong> so far
                </span>
              )}
              <span className="text-xs opacity-70 sm:ml-0">Edit</span>
            </button>
          ))}
          {onDay(cursor).length === 0 ? (
            <p className="text-sm text-gray-400 py-4 text-center">Nothing booked</p>
          ) : (
            <ul className="grid gap-2 md:grid-cols-2">
              {onDay(cursor).map((a) => <AppointmentItem key={a.id} appointment={a} actions={actions} />)}
            </ul>
          )}
          {planned.onDay(cursor).length > 0 && (
            <div className="mt-4">
              <h3 className="text-xs font-medium uppercase tracking-wide text-gray-400 mb-1">Planned</h3>
              <ul className="divide-y divide-gray-100">
                {planned.onDay(cursor).map((p) => (p.type === 'post'
                  ? <PostRow key={p.key} post={p.raw} onEdit={(x) => setModal({ post: x })} onChanged={plannedChanged} />
                  : <PlannedRow key={p.key} item={p} />))}
              </ul>
            </div>
          )}
          {tasksOn(cursor).length > 0 && (
            <div className="mt-4">
              <h3 className="text-xs font-medium uppercase tracking-wide text-gray-400 mb-1">Tasks due</h3>
              <ul className="divide-y divide-gray-100">
                {tasksOn(cursor).map((t) => <TaskItem key={t.id} task={t} onToggle={toggleTask} onOpen={(x) => openTask(x)} />)}
              </ul>
            </div>
          )}
        </div>
      )}
      <TasksPanel version={taskVersion} onChanged={tasksChanged} onOpen={(t) => openTask(t, t ? undefined : cursor)} />
      </div>

      {modal && 'task' in modal && (
        <Modal title={modal.task ? 'Edit task' : 'New task'} onClose={() => setModal(null)}>
          <TaskForm task={modal.task} defaultDate={modal.taskDay} onSaved={closeAndReload} />
        </Modal>
      )}

      {modal && (modal.period || modal.newPeriod) && (
        <Modal
          title={modal.period ? `Edit ${modal.period.kind === 'tour' ? 'tour' : 'time off'}` : modal.newPeriod === 'tour' ? 'New tour' : 'New time off'}
          onClose={() => setModal(null)}
        >
          <TourForm
            period={modal.period}
            defaultKind={modal.newPeriod}
            defaultDate={modal.defaultDate}
            onSaved={closeAndReload}
            onDeleted={closeAndReload}
          />
        </Modal>
      )}
      {modal?.post && (
        <Modal title={modal.post.id ? 'Edit post' : 'Plan a post'} onClose={() => setModal(null)} wide>
          <PostForm post={modal.post} onDone={() => { setModal(null); plannedChanged(); }} />
        </Modal>
      )}
      {modal?.shoot && (
        <Modal title="Plan a shoot" onClose={() => setModal(null)} wide>
          <ShootForm shoot={modal.shoot} onDone={(saved) => { setModal(null); plannedChanged(); if (saved?.id) navigate(`/calendar/shoots?shoot=${saved.id}`); }} />
        </Modal>
      )}
      {modal && !modal.period && !modal.newPeriod && !modal.post && !modal.shoot && !('task' in modal) && (
        <Modal
          title={modal.appointment
            ? (modal.appointment.kind === 'test' ? 'Edit health test' : 'Edit appointment')
            : modal.kind === 'test' ? 'New health test' : 'New appointment'}
          onClose={() => setModal(null)}
        >
          <AppointmentForm
            appointment={modal.appointment}
            defaultDate={modal.defaultDate}
            defaultKind={modal.kind}
            onSaved={closeAndReload}
            onDeleted={closeAndReload}
          />
        </Modal>
      )}
    </div>
  );
}

// ==================== MONTH ====================

const MARKER_COLORS = { document: '#b45309', health: '#0f9488', money: '#059669', holiday: '#7c3aed' };

/** A small diamond per important date (hover or the day panel shows what it is). */
function MarkerDots({ markers }) {
  if (!markers?.length) return null;
  return (
    <span className="flex gap-0.5 shrink-0" title={markers.map((m) => m.label).join(' · ')} aria-label={markers.map((m) => m.label).join(', ')}>
      {markers.slice(0, 3).map((m, i) => (
        <span key={i} className="w-1.5 h-1.5 rotate-45" style={{ background: MARKER_COLORS[m.kind] || '#6b7280' }} />
      ))}
    </span>
  );
}

function MonthView({ days, cursor, today, narrow, onDay, periods, onSelect, onNew, onOpen, tasksOn, cycle, markersOn = () => [], plannedOn = () => [], onOpenPlanned }) {
  return (
    <>
      <div className="grid grid-cols-7 text-xs font-medium text-gray-400 mb-1">
        {WEEKDAYS.map((d) => <div key={d} className="px-1 sm:px-2 py-1">{narrow ? d[0] : d}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-px bg-gray-100 border border-gray-100 rounded-xl overflow-hidden">
        {days.map((day) => {
          const items = onDay(day);
          const inMonth = day.getMonth() === cursor.getMonth();
          const isToday = sameDay(day, today);
          const isSelected = sameDay(day, cursor);
          const { tour, off } = dayPeriods(periods, day);
          const due = tasksOn(day);
          const openDue = due.filter((t) => !t.done).length;
          // The tour's name on its first day and at the start of each week row; a plain strip on the other days.
          const tourLabel = tour && (tour.start_date === toKey(day) || day.getDay() === 0);
          return (
            <div
              key={day.toISOString()}
              onClick={() => onSelect(day)}
              onDoubleClick={() => onNew(day)}
              className={`min-h-14 sm:min-h-28 p-1 sm:p-1.5 cursor-pointer transition-colors ${inMonth ? 'bg-white' : 'bg-gray-50'} ${
                isSelected ? 'ring-2 ring-inset ring-sworkr-300' : 'hover:bg-sworkr-50/50'
              }`}
              style={off ? { backgroundImage: TIME_OFF_BACKGROUND } : undefined}
              title={[tour && `Tour: ${tour.name}`, off && periodLabel(off), CYCLE_LABELS[cycle[toKey(day)]]].filter(Boolean).join(' · ') || undefined}
            >
              {tour && (
                <div
                  className="-mx-1 sm:-mx-1.5 -mt-1 sm:-mt-1.5 mb-0.5 h-1.5 sm:h-4 px-1.5 text-[10px] leading-4 text-white truncate"
                  style={{ background: TOUR_COLOR }}
                >
                  <span className="hidden sm:inline">{tourLabel ? `✈ ${tour.name}` : ''}</span>
                </div>
              )}
              <span className="flex items-center gap-1 min-w-0">
                <span
                  className={`shrink-0 text-xs w-6 h-6 flex items-center justify-center rounded-full ${
                    isToday ? 'bg-sworkr-500 text-white font-bold' : inMonth ? 'text-gray-700' : 'text-gray-300'
                  }`}
                >
                  {day.getDate()}
                </span>
                <CycleDot kind={cycle[toKey(day)]} />
                <MarkerDots markers={markersOn(day)} />
                {off && !narrow && <span className="text-[10px] text-gray-500 truncate">{periodLabel(off)}</span>}
              </span>
              {narrow ? (
                // On a phone there's no room for text: one dot per appointment, details below the grid.
                <div className="flex flex-wrap gap-0.5 mt-1 px-0.5" aria-label={`${items.length} appointments`}>
                  {items.slice(0, 4).map((a) => (
                    <span key={a.id} className="w-1.5 h-1.5 rounded-full" style={{ background: apptColor(a), opacity: a.status === 'cancelled' ? 0.4 : 1 }} />
                  ))}
                  {items.length > 4 && <span className="text-[9px] leading-none text-gray-400">+</span>}
                  {plannedOn(day).slice(0, 4).map((p) => <span key={p.key} className="w-1.5 h-1.5 rounded-sm" style={{ background: p.color }} />)}
                </div>
              ) : (
                <div className="space-y-0.5 mt-1">
                  {items.slice(0, 3).map((a) => (
                    <button
                      key={a.id}
                      onClick={(e) => { e.stopPropagation(); onOpen(a); }}
                      className={`block w-full text-left text-white rounded px-1.5 py-0.5 text-[11px] truncate hover:opacity-90 ${
                        a.status === 'cancelled' ? 'opacity-50 line-through' : ''
                      }`}
                      style={{ background: apptColor(a) }}
                      title={`${formatTime(new Date(a.scheduled_date))} · ${a.kind === 'test' ? a.service_type : `${a.client_name} · ${a.service_type}`}`}
                    >
                      {a.client_do_not_see ? '⚠ ' : ''}{sameDay(new Date(a.scheduled_date), day) ? formatTime(new Date(a.scheduled_date)) : '↳'} {apptTitle(a)}
                    </button>
                  ))}
                  {items.length > 3 && <p className="text-[11px] text-gray-400 px-1">+{items.length - 3} more</p>}
                  {plannedOn(day).slice(0, 2).map((p) => <PlannedChip key={p.key} item={p} onOpen={onOpenPlanned} />)}
                  {plannedOn(day).length > 2 && <p className="text-[11px] text-gray-400 px-1">+{plannedOn(day).length - 2} planned</p>}
                  {due.length > 0 && (
                    <p className={`text-[11px] px-1 truncate ${openDue ? 'text-gray-600' : 'text-gray-300 line-through'}`} title={due.map((t) => t.title).join(', ')}>
                      ☐ {due.length === 1 ? due[0].title : `${due.length} tasks`}
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {!narrow && <p className="text-xs text-gray-400 mt-2">Click a day to see it below · double-click to add an appointment · click an appointment to edit it · purple strip = tour, grey stripes = time off{Object.keys(cycle).length > 0 && ' · pink dot = period (outlined = predicted)'}</p>}
    </>
  );
}

// ==================== WEEK / DAY (time grid) ====================

/** Side-by-side columns for blocks that overlap in time. Each block gets { lane, lanes }. */
function layout(blocks) {
  const sorted = [...blocks].sort((a, b) => a.from - b.from || b.to - a.to);
  let cluster = [];
  let clusterEnd = -1;
  const flush = () => {
    const lanes = Math.max(0, ...cluster.map((b) => b.lane)) + 1;
    cluster.forEach((b) => { b.lanes = lanes; });
    cluster = [];
  };
  for (const block of sorted) {
    if (cluster.length && block.from >= clusterEnd) flush();
    const taken = new Set(cluster.filter((b) => b.to > block.from).map((b) => b.lane));
    let lane = 0;
    while (taken.has(lane)) lane += 1;
    block.lane = lane;
    cluster.push(block);
    clusterEnd = Math.max(clusterEnd, block.to);
  }
  if (cluster.length) flush();
  return sorted;
}

function TimeGrid({ days, today, onDay, periods, cycle, onNew, onOpen, onOpenPeriod, onPickDay, plannedOn = () => [], onOpenPlanned }) {
  const scroller = useRef(null);
  const [now, setNow] = useState(() => new Date());

  useLayoutEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 8 * HOUR - 12; // start the view just before 8 am
  }, [days.length]);
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(id);
  }, []);

  const clickSlot = (day, e) => {
    const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
    const minutes = Math.max(0, Math.min(23.5 * 60, Math.floor(y / HOUR * 2) * 30)); // to the half hour
    const when = new Date(day);
    when.setHours(0, minutes, 0, 0);
    onNew(when, true);
  };

  return (
    <div className="border border-gray-100 rounded-xl overflow-hidden">
      {/* Day headers */}
      <div className="flex border-b border-gray-100 bg-gray-50">
        <div className="w-12 shrink-0" />
        {days.map((day) => (
          <button
            key={day.toISOString()}
            onClick={() => onPickDay(day)}
            className="flex-1 min-w-0 py-2 text-center hover:bg-gray-100"
            title="Open this day"
          >
            <span className="flex items-center justify-center gap-1 text-[11px] text-gray-400">{WEEKDAYS[day.getDay()]}<CycleDot kind={cycle[toKey(day)]} /></span>
            <span className={`inline-flex w-7 h-7 items-center justify-center rounded-full text-sm ${
              sameDay(day, today) ? 'bg-sworkr-500 text-white font-bold' : 'text-gray-700'
            }`}>{day.getDate()}</span>
          </button>
        ))}
      </div>
      {days.some((d) => plannedOn(d).length) && (
        <div className="flex border-b border-gray-100">
          <div className="w-12 shrink-0 px-1 py-1 text-[10px] text-gray-400">Plans</div>
          {days.map((day) => (
            <div key={day.toISOString()} className="flex-1 min-w-0 px-0.5 py-0.5 space-y-0.5">
              {plannedOn(day).map((p) => <PlannedChip key={p.key} item={p} onOpen={onOpenPlanned} />)}
            </div>
          ))}
        </div>
      )}
      {periods.some((p) => days.some((d) => periodsOn([p], d).length)) && (
        <div className="flex border-b border-gray-100">
          <div className="w-12 shrink-0" />
          {days.map((day) => {
            const { tour, off } = dayPeriods(periods, day);
            return (
              <div key={day.toISOString()} className="flex-1 min-w-0 px-0.5 py-0.5 space-y-0.5">
                {tour && (
                  <button onClick={() => onOpenPeriod(tour)} className="block w-full truncate rounded px-1.5 text-[10px] leading-4 text-white text-left" style={{ background: TOUR_COLOR }}>
                    ✈ {tour.name}
                  </button>
                )}
                {off && (
                  <button onClick={() => onOpenPeriod(off)} className="block w-full truncate rounded px-1.5 text-[10px] leading-4 text-gray-600 text-left" style={{ background: TIME_OFF_BACKGROUND }}>
                    {periodLabel(off)}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div ref={scroller} className="overflow-y-auto" style={{ maxHeight: '62vh' }}>
        <div className="flex relative" style={{ height: 24 * HOUR }}>
          {/* Hour labels */}
          <div className="w-12 shrink-0 relative">
            {[...Array(24)].map((_, h) => (
              <span key={h} className="absolute right-1.5 text-[10px] text-gray-400 -translate-y-1/2" style={{ top: h * HOUR }}>
                {h === 0 ? '' : new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: 'numeric' })}
              </span>
            ))}
          </div>

          {days.map((day) => {
            const dayStart = startOfDay(day).getTime();
            const blocks = layout(onDay(day).map((a) => {
              const from = Math.max(0, (new Date(a.scheduled_date).getTime() - dayStart) / 60000);
              const to = Math.min(24 * 60, (endOf(a).getTime() - dayStart) / 60000);
              return { a, from, to: Math.max(to, from + 20), continues: new Date(a.scheduled_date).getTime() < dayStart };
            }));
            return (
              <div
                key={day.toISOString()}
                onClick={(e) => clickSlot(day, e)}
                className="flex-1 min-w-0 relative border-l border-gray-100 cursor-pointer"
                style={{
                  backgroundImage: 'linear-gradient(to bottom, #f3f4f6 1px, transparent 1px)',
                  backgroundSize: `100% ${HOUR}px`,
                  backgroundColor: dayPeriods(periods, day).off ? '#f3f4f6' : undefined,
                }}
              >
                {blocks.map(({ a, from, to, lane, lanes, continues }) => (
                  <button
                    key={a.id}
                    onClick={(e) => { e.stopPropagation(); onOpen(a); }}
                    className={`absolute rounded-md px-1.5 py-0.5 text-left text-white text-[11px] leading-tight overflow-hidden ring-1 ring-white hover:opacity-90 ${
                      a.status === 'cancelled' ? 'opacity-50 line-through' : ''
                    }`}
                    style={{
                      top: from / 60 * HOUR,
                      height: Math.max((to - from) / 60 * HOUR, 18),
                      left: `calc(${(lane / lanes) * 100}% + 1px)`,
                      width: `calc(${100 / lanes}% - 2px)`,
                      background: apptColor(a),
                    }}
                    title={`${formatTime(new Date(a.scheduled_date))}–${formatTime(endOf(a))} · ${a.kind === 'test' ? a.service_type : `${a.client_name} · ${a.service_type}`}`}
                  >
                    <span className="font-semibold">{a.client_do_not_see ? '⚠ ' : ''}{continues ? '↳ ' : `${formatTime(new Date(a.scheduled_date))} `}</span>
                    {apptTitle(a)}
                    {a.kind !== 'test' && <span className="block opacity-90 truncate">{a.service_type}</span>}
                  </button>
                ))}
                {sameDay(day, now) && (
                  <div className="absolute left-0 right-0 border-t-2 border-red-500 pointer-events-none" style={{ top: (now.getHours() * 60 + now.getMinutes()) / 60 * HOUR }} aria-hidden="true">
                    <span className="absolute -left-1 -top-1.5 w-2.5 h-2.5 rounded-full bg-red-500" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <p className="text-xs text-gray-400 px-3 py-2 border-t border-gray-100">Click an empty time to add an appointment there.</p>
    </div>
  );
}

// ==================== LIST ====================

function ListView({ days, today, startingOn, periods, cycle, actions, onNew, onOpenPeriod, plannedOn = () => [], onEditPost, onPlannedChanged }) {
  const withItems = days
    .map((day) => ({ day, items: startingOn(day), plans: plannedOn(day), ...dayPeriods(periods, day) }))
    .filter((d) => d.items.length || d.plans.length || sameDay(d.day, today) || d.tour?.start_date === toKey(d.day) || d.off?.start_date === toKey(d.day));
  if (!withItems.some((d) => d.items.length || d.plans.length)) {
    return (
      <div className="text-center py-10">
        <p className="text-gray-400 text-sm">Nothing booked in these {days.length} days.</p>
        <button onClick={() => onNew(today)} className="mt-3 text-sm text-sworkr-600 hover:text-sworkr-800">+ Add an appointment</button>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {withItems.map(({ day, items, plans, tour, off }) => (
        <section key={day.toISOString()}>
          <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-gray-700 mb-2">
            {sameDay(day, today) && <span className="px-2 py-0.5 rounded-full bg-sworkr-500 text-white text-[11px]">Today</span>}
            {dayLabel(day)}
            {cycle[toKey(day)] && <span className="flex items-center gap-1 text-[11px] font-normal text-gray-500"><CycleDot kind={cycle[toKey(day)]} />{CYCLE_LABELS[cycle[toKey(day)]]}</span>}
            {tour && (
              <button onClick={() => onOpenPeriod(tour)} className="px-2 py-0.5 rounded-full text-white text-[11px] font-medium" style={{ background: TOUR_COLOR }}>
                ✈ {tour.name}
              </button>
            )}
            {off && (
              <button onClick={() => onOpenPeriod(off)} className="px-2 py-0.5 rounded-full text-gray-600 text-[11px] font-medium" style={{ background: TIME_OFF_BACKGROUND }}>
                {periodLabel(off)}
              </button>
            )}
          </h2>
          {items.length === 0 ? (
            !plans.length && <p className="text-sm text-gray-400">Nothing booked</p>
          ) : (
            <ul className="grid gap-2 md:grid-cols-2">
              {items.map((a) => <AppointmentItem key={a.id} appointment={a} actions={actions} />)}
            </ul>
          )}
          {plans.length > 0 && (
            <ul className="divide-y divide-gray-100 mt-1">
              {plans.map((p) => (p.type === 'post'
                ? <PostRow key={p.key} post={p.raw} onEdit={onEditPost} onChanged={onPlannedChanged} />
                : <PlannedRow key={p.key} item={p} />))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

// ==================== ONE APPOINTMENT ====================

const CANCEL_REASONS = { client: 'Client cancelled', late: 'Cancelled late', no_show: "Didn't turn up", me: 'I cancelled' };

/** Cancelling: who cancelled, and for a late cancellation or no-show, the fee (sworkr suggests one from your policy). */
function CancelChooser({ appointment: a, onCancel, onClose }) {
  const [policy, setPolicy] = useState(null);
  const [reason, setReason] = useState('');
  const [fee, setFee] = useState('');
  useEffect(() => { axios.get('/api/booking-policy').then(({ data }) => setPolicy(data)).catch(() => setPolicy({})); }, []);
  const late = policy && (new Date(a.scheduled_date) - new Date()) < (policy.late_cancel_hours || 0) * 3600000;
  const pick = (r) => {
    setReason(r);
    const effective = r === 'client' && late ? 'late' : r;
    const pct = effective === 'no_show' ? policy?.no_show_fee_percent : effective === 'late' ? policy?.late_cancel_fee_percent : 0;
    setFee(a.rate && pct ? String(Math.round(a.rate * pct) / 100) : '');
  };
  const charged = reason === 'no_show' || (reason === 'client' && late);
  return (
    <div className="w-full rounded-lg border border-red-100 bg-red-50/50 p-2 space-y-2">
      <div className="flex flex-wrap gap-1">
        {['client', 'no_show', 'me'].map((r) => (
          <button key={r} type="button" onClick={() => pick(r)} aria-pressed={reason === r}
            className={`text-xs px-2.5 py-1.5 rounded-lg border ${reason === r ? 'bg-red-600 text-white border-red-600' : 'bg-white text-gray-700 border-gray-200'}`}>
            {r === 'client' && late ? 'Client cancelled (late)' : CANCEL_REASONS[r]}
          </button>
        ))}
      </div>
      {charged && (
        <label className="flex items-center gap-2 text-xs text-gray-700">
          Cancellation fee $
          <input type="number" min="0" step="0.01" value={fee} onChange={(e) => setFee(e.target.value)} className="w-24 border border-gray-200 rounded px-1.5 py-1" />
          {a.amount_paid > 0 && <span className="text-gray-500">({money(a.amount_paid)} deposit already paid counts towards it)</span>}
        </label>
      )}
      <div className="flex gap-2">
        <button type="button" disabled={!reason} onClick={() => onCancel({ cancel_reason: reason, ...(charged ? { cancellation_fee: fee === '' ? 0 : Number(fee) } : {}) })}
          className="text-xs px-2.5 py-1.5 rounded-lg bg-red-600 text-white disabled:opacity-40">Cancel booking</button>
        <button type="button" onClick={onClose} className="text-xs px-2.5 py-1.5 rounded-lg text-gray-600 hover:bg-white">Keep it</button>
      </div>
    </div>
  );
}

export function AppointmentItem({ appointment: a, actions, showDate = false, showClient = true }) {
  const [cancelling, setCancelling] = useState(false);
  const [receipt, setReceipt] = useState(false);
  const [review, setReview] = useState(false);
  const startAt = new Date(a.scheduled_date);
  const endAt = endOf(a);
  const pay = PAYMENT_STYLES[a.payment_status];
  const isTest = a.kind === 'test';
  const needsCheckIn = a.safety_checkin && !a.checked_in_at && a.status !== 'cancelled' && startAt <= new Date();
  const where = [LOCATION_LABELS[a.location_type], a.location].filter(Boolean).join(' · ');
  const small = 'text-xs px-2.5 py-1.5 rounded-lg';

  return (
    <li className={`rounded-xl border p-3 hover:shadow-sm ${a.client_do_not_see ? 'border-red-300' : 'border-gray-100'}`}>
      <button onClick={() => actions.open(a)} className="block w-full text-left">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: apptColor(a) }} />
          <span className="text-sm font-medium text-gray-800">
            {isTest ? `🩺 ${a.service_type}` : showClient ? a.client_name || 'Unknown client' : a.service_type}
          </span>
          {a.client_do_not_see && <span className="px-2 py-0.5 rounded-full bg-red-600 text-white text-[10px] font-semibold">Do not see</span>}
          <span className={`ml-auto px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_STYLES[a.status].badge}`}>
            {STATUS_STYLES[a.status].label}
          </span>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          {showDate && `${dayLabel(startAt, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })} · `}
          {formatTime(startAt)}–{formatTime(endAt)}{!sameDay(startAt, endAt) && ' (next day)'} · {formatDuration(a.duration_minutes)}
          {showClient && !isTest && ` · ${a.service_type}`}
        </p>
        {where && <p className="text-xs text-gray-500 mt-0.5">{where}</p>}
        {a.partner_names && (
          <p className="text-xs mt-1 text-sworkr-600">
            With {a.partner_names}{a.amount_paid > 0 && a.my_amount_paid != null && <span className="text-gray-500"> · yours {money(a.my_amount_paid)}</span>}
          </p>
        )}
        {isTest && a.cost != null && (
          <p className="text-xs mt-1 text-gray-600">Cost <span className="font-semibold text-gray-700">{money(a.cost)}</span> · in expenses</p>
        )}
        {(a.rate != null || a.amount_paid > 0) && (
          <p className="text-xs mt-1 flex items-center gap-2">
            <span className="font-semibold text-gray-700">{a.rate != null ? money(a.rate) : money(a.amount_paid)}</span>
            {pay && <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${pay.badge}`}>{pay.label}</span>}
            {a.payment_status === 'partial' && <span className="text-gray-500">{money(a.amount_paid)} received</span>}
          </p>
        )}
        {a.status === 'cancelled' && a.cancel_reason && (
          <p className="text-xs mt-1 text-red-700">
            {CANCEL_REASONS[a.cancel_reason]}
            {a.cancellation_fee > 0 && ` · fee ${money(a.cancellation_fee)}`}
            {a.cancellation_fee > (a.amount_paid || 0) && `, ${money(a.cancellation_fee - (a.amount_paid || 0))} still owed`}
          </p>
        )}
        {a.notes && <p className="text-xs text-gray-400 mt-1 line-clamp-2">{a.notes}</p>}
      </button>

      <div className="flex flex-wrap items-center gap-2 mt-2">
        {needsCheckIn && (
          <button onClick={() => actions.checkIn(a)} className={`${small} bg-emerald-600 text-white hover:bg-emerald-700 font-medium`}>
            ✓ I'm safe (check in)
          </button>
        )}
        {a.safety_checkin && a.checked_in_at && <span className="text-[11px] text-emerald-700">✓ Checked in</span>}
        {a.safety_checkin && !a.checked_in_at && !needsCheckIn && a.status === 'scheduled' && (
          <span className="text-[11px] text-gray-500">Check-in on</span>
        )}
        {!isTest && a.amount_paid > 0 && (
          <button onClick={() => setReceipt(true)} className={`${small} border border-gray-200 text-gray-600 hover:bg-gray-50`}>Receipt</button>
        )}
        {receipt && <ReceiptMaker appointment={a} onClose={() => setReceipt(false)} />}
        {!isTest && a.status === 'completed' && (
          <button onClick={() => setReview(true)} className={`${small} border border-gray-200 text-gray-600 hover:bg-gray-50`}>How did it go?</button>
        )}
        {review && <BookingReview appointment={a} onClose={() => setReview(false)} />}
        {a.status === 'scheduled' && (
          <>
            <button onClick={() => actions.status(a, 'completed')} className={`${small} bg-emerald-50 text-emerald-700 hover:bg-emerald-100`}>✓ Done</button>
            {isTest
              ? <button onClick={() => actions.status(a, 'cancelled')} className={`${small} bg-red-50 text-red-600 hover:bg-red-100`}>✕ Cancel</button>
              : !cancelling && <button onClick={() => setCancelling(true)} className={`${small} bg-red-50 text-red-600 hover:bg-red-100`}>✕ Cancel</button>}
          </>
        )}
        {cancelling && a.status === 'scheduled' && (
          <CancelChooser appointment={a} onClose={() => setCancelling(false)}
            onCancel={(extra) => { setCancelling(false); actions.status(a, 'cancelled', extra); }} />
        )}
        {a.status === 'cancelled' && a.cancellation_fee > (a.amount_paid || 0) && (
          <button onClick={() => actions.paid(a)} className={`${small} bg-amber-50 text-amber-800 hover:bg-amber-100`}>$ Fee paid</button>
        )}
        {a.status !== 'cancelled' && (a.payment_status === 'unpaid' || a.payment_status === 'partial') && (
          <button onClick={() => actions.paid(a)} className={`${small} bg-amber-50 text-amber-800 hover:bg-amber-100`}>$ Mark paid</button>
        )}
        {showClient && a.client_id && (
          <Link to={`/contacts/${a.client_id}`} className="ml-auto text-[11px] text-sworkr-600 hover:text-sworkr-800">Contact page →</Link>
        )}
      </div>
    </li>
  );
}
