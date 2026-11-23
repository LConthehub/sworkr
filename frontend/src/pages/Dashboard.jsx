import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal from '../components/Modal';
import { TaskForm, TasksPanel } from '../components/Tasks';
import { RoutinesCard } from '../components/Routines';
import QuickNote from '../components/QuickNote';
import { AskCard } from '../components/Assistant';
import { WellnessCard } from '../components/Wellness';
import { ProgressCard, TourWrapUp } from '../components/Progress';
import Today from '../components/Today';
import { NoticeBanner } from '../components/Notices';
import { HouseGuide } from '../components/House';
import { SuppliesCard } from '../components/Everyday';
import { useFeatures } from '../features';

// Cards that only fit some kinds of work (see FEATURES in backend/finance.py).
const CARD_NEEDS = { deposits: 'bookings', inquiries: 'bookings', shoots: 'shoots', customs: 'customs', ads: 'ads', posts: 'content' };
import { EmailPanel } from '../components/Email';
import GoalsGlance from '../components/GoalsGlance';
import { CycleCard } from '../components/Cycle';
import { PostsDue } from './Content';
import { InquiriesWaiting } from './Inquiries';
import { AdsExpiring } from '../components/Listings';
import { CustomsDue } from '../components/Customs';
import { TestsDue } from '../components/TestKinds';
import { ShootsSoon } from '../components/Shoots';
import { DepositsDue } from './Rates';
import { fetchAll } from '../api';
import {
  addDays, apptColorFor, dayLabel, endOf, formatTime, money, periodLabel, periodsOn, sameDay, startOfDay, TOUR_COLOR,
} from '../colors';

const DAYS = 7;

function greeting(now) {
  const h = now.getHours();
  return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

// Every card the dashboard can show, in the usual order.
const CARDS = {
  week: 'This week', deposits: 'Deposits to collect', tests: 'Health tests due', inquiries: 'Inquiries to answer',
  shoots: 'Shoots coming up', customs: 'Customs to make', ads: 'Ads running out', posts: 'Posts & ads due', tasks: 'Tasks', routines: 'Routines', note: 'Notes', ask: 'Ask your numbers', wellness: "Today's check-in", supplies: 'Supplies', progress: 'Progress', wrapup: 'Tour wrap-up',
  email: 'Email', cycle: 'Period tracker', goals: 'Wallet',
};

/** The home page: what needs doing, in the order and with the cards this person chose. */
export default function Dashboard({ user }) {
  const [version, setVersion] = useState(0);
  const [taskModal, setTaskModal] = useState(null); // { task } (task null for a new one)
  const now = new Date();
  // Which cards to show and in what order: this person's own arrangement, saved with their account.
  const [order, setOrder] = useState(Object.keys(CARDS));
  const [hidden, setHidden] = useState([]);
  const [customizing, setCustomizing] = useState(false);
  useEffect(() => {
    axios.get('/api/dashboard-layout').then(({ data }) => {
      const known = data.order.filter((id) => CARDS[id]);
      setOrder([...known, ...Object.keys(CARDS).filter((id) => !known.includes(id))]);   // cards added since come last
      setHidden(data.hidden.filter((id) => CARDS[id]));
    }).catch(() => {});
  }, []);
  const move = (i, by) => setOrder((o) => { const next = [...o]; [next[i], next[i + by]] = [next[i + by], next[i]]; return next; });
  const saveLayout = async () => { await axios.put('/api/dashboard-layout', { order, hidden }).catch(() => {}); setCustomizing(false); };
  const bump = () => setVersion((v) => v + 1);
  const has = useFeatures();
  const fits = (id) => !CARD_NEEDS[id] || has(CARD_NEEDS[id]);
  const card = (id) => ({
    week: <WeekAhead version={version} />,
    deposits: <DepositsDue />,
    tests: <TestsDue />,
    inquiries: <InquiriesWaiting />,
    shoots: <ShootsSoon />,
    customs: <CustomsDue />,
    ads: <AdsExpiring />,
    posts: <PostsDue />,
    tasks: <TasksPanel version={version} onChanged={bump} onOpen={(task) => setTaskModal({ task })} />,
    routines: <RoutinesCard />,
    note: <QuickNote />,
    ask: <AskCard />,
    wellness: <WellnessCard />,
    supplies: <SuppliesCard />,
    progress: <ProgressCard />,
    wrapup: <TourWrapUp />,
    email: <EmailPanel />,
    cycle: <CycleCard onChanged={bump} />,
    goals: <GoalsGlance version={version} />,
  }[id]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">{greeting(now)}, {user.username}</h1>
          <p className="text-sm text-white/90">{dayLabel(now, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</p>
        </div>
        <button onClick={() => setCustomizing(!customizing)} className="text-sm text-white/90 hover:text-white underline">{customizing ? 'Close' : 'Customize'}</button>
      </div>
      {customizing && (
        <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
          <h2 className="font-semibold text-gray-800">Customize your dashboard</h2>
          <p className="text-xs text-gray-500 mb-2">Untick what you don't want, and move the rest into the order you like. Some cards only appear when there's something to show.</p>
          <ul className="divide-y divide-gray-100">
            {order.map((id, i) => (
              <li key={id} className="py-1.5 flex items-center gap-3">
                <label className="flex-1 flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={!hidden.includes(id)} onChange={(e) => setHidden(e.target.checked ? hidden.filter((x) => x !== id) : [...hidden, id])} />
                  {CARDS[id]}
                </label>
                <button onClick={() => move(i, -1)} disabled={i === 0} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600 disabled:opacity-30" aria-label={`Move ${CARDS[id]} up`}>↑</button>
                <button onClick={() => move(i, 1)} disabled={i === order.length - 1} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600 disabled:opacity-30" aria-label={`Move ${CARDS[id]} down`}>↓</button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2 mt-3">
            <button onClick={saveLayout} className="px-4 py-2 rounded-lg text-sm bg-sworkr-500 text-white hover:bg-sworkr-600">Save</button>
            <button onClick={() => { setOrder(Object.keys(CARDS)); setHidden([]); }} className="px-4 py-2 rounded-lg text-sm border border-gray-200 text-gray-600 hover:bg-gray-50">Back to the usual</button>
          </div>
        </div>
      )}
      <NoticeBanner />
      <Today onLogged={bump} />
      <HouseGuide />
      <div className="lg:columns-2 gap-4">
        {order.filter((id) => !hidden.includes(id) && fits(id)).map((id) => (
          <div key={id} className="mb-4 break-inside-avoid empty:hidden">{card(id)}</div>
        ))}
      </div>
      {taskModal && (
        <Modal title={taskModal.task ? 'Edit task' : 'New task'} onClose={() => setTaskModal(null)}>
          <TaskForm task={taskModal.task} defaultDate={taskModal.task ? undefined : now}
            onSaved={() => { setTaskModal(null); setVersion((v) => v + 1); }} />
        </Modal>
      )}
    </div>
  );
}

/** Bookings, tests, tours and time off for today and the next six days. */
function WeekAhead({ version }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const start = startOfDay(new Date());
  const end = addDays(start, DAYS);

  const load = useCallback(async () => {
    try {
      const [appointments, periods] = await Promise.all([
        fetchAll('/api/appointments', { start: start.toISOString(), end: end.toISOString() }, 500),
        axios.get('/api/tours', { params: { start: start.toISOString(), end: end.toISOString() } }).then((r) => r.data),
      ]);
      setData({ appointments: appointments.filter((a) => a.status !== 'cancelled'), periods });
      setError('');
    } catch (err) {
      if (err?.response?.status !== 401) setError("Couldn't load your week.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { load(); }, [load, version]);

  const days = [...Array(DAYS)].map((_, i) => addDays(start, i));
  const bookings = data ? data.appointments.filter((a) => a.kind !== 'test') : [];
  const booked = bookings.reduce((s, a) => s + (a.rate || 0), 0);

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-gray-800">This week</h2>
        <Link to="/calendar" className="text-sm text-sworkr-600 hover:text-sworkr-800">Open calendar →</Link>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {data && (
        <>
          <p className="text-xs text-gray-500 mb-3">
            {bookings.length} booking{bookings.length === 1 ? '' : 's'}
            {booked > 0 && ` · ${money(booked)} booked`}
          </p>
          <ul className="space-y-3">
            {days.map((day) => {
              const items = data.appointments.filter((a) => sameDay(new Date(a.scheduled_date), day));
              const on = periodsOn(data.periods, day);
              const isToday = sameDay(day, new Date());
              return (
                <li key={day.toISOString()}>
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className={`text-xs font-semibold uppercase tracking-wide ${isToday ? 'text-sworkr-600' : 'text-gray-500'}`}>
                      {isToday ? 'Today' : dayLabel(day, { weekday: 'short', month: 'short', day: 'numeric' })}
                    </span>
                    {on.map((p) => (
                      <span key={p.id} className={`text-[11px] px-2 py-0.5 rounded-full ${p.kind === 'tour' ? '' : 'bg-gray-100 text-gray-600'}`}
                        style={p.kind === 'tour' ? { background: TOUR_COLOR, color: 'white' } : undefined}>
                        {p.kind === 'tour' ? `✈ ${p.name}` : periodLabel(p)}
                      </span>
                    ))}
                  </div>
                  {items.length === 0 ? (
                    <p className="text-sm text-gray-300 pl-1">Nothing booked</p>
                  ) : (
                    <ul className="space-y-1">
                      {items.map((a) => (
                        <li key={a.id} className="flex items-center gap-2 text-sm">
                          <span className="w-1 self-stretch rounded-full" style={{ background: apptColorFor(a) }} />
                          <span className="w-28 shrink-0 text-gray-500">{formatTime(new Date(a.scheduled_date))}–{formatTime(endOf(a))}</span>
                          <span className="min-w-0 truncate text-gray-800">
                            {a.kind === 'test' ? `🩺 ${a.service_type}` : <>{a.client_do_not_see && '⚠ '}{a.client_name} <span className="text-gray-400">· {a.service_type}</span></>}
                          </span>
                          {a.payment_status === 'paid' && <span className="ml-auto text-[10px] px-1.5 rounded-full bg-emerald-100 text-emerald-700">Paid</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
