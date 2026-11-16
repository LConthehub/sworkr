import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal from '../components/Modal';
import { TaskForm, TasksPanel } from '../components/Tasks';
import { EmailPanel } from '../components/Email';
import GoalsGlance from '../components/GoalsGlance';
import { CycleCard } from '../components/Cycle';
import { PostsDue } from './Content';
import { InquiriesWaiting } from './Inquiries';
import { AdsExpiring } from '../components/Listings';
import { CustomsDue } from '../components/Customs';
import { TestsDue } from '../components/TestKinds';
import { ShootsSoon } from '../components/Shoots';
import { fetchAll } from '../api';
import {
  addDays, apptColorFor, dayLabel, endOf, formatTime, money, periodLabel, periodsOn, sameDay, startOfDay, TOUR_COLOR,
} from '../colors';

const DAYS = 7;

function greeting(now) {
  const h = now.getHours();
  return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

/** The home page: the week ahead, tasks, and unread and important email. */
export default function Dashboard({ user }) {
  const [version, setVersion] = useState(0);
  const [taskModal, setTaskModal] = useState(null); // { task } (task null for a new one)
  const now = new Date();
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white">{greeting(now)}, {user.username}</h1>
        <p className="text-sm text-white/90">{dayLabel(now, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</p>
      </div>
      <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 items-start">
        <div className="space-y-4">
          <WeekAhead version={version} />
          <TestsDue />
          <InquiriesWaiting />
          <ShootsSoon />
          <CustomsDue />
          <AdsExpiring />
          <PostsDue />
          <TasksPanel version={version} onChanged={() => setVersion((v) => v + 1)} onOpen={(task) => setTaskModal({ task })} />
        </div>
        <div className="space-y-4">
          <EmailPanel />
          <CycleCard onChanged={() => setVersion((v) => v + 1)} />
          <GoalsGlance version={version} />
        </div>
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
                      <span key={p.id} className="text-[11px] px-2 py-0.5 rounded-full"
                        style={p.kind === 'tour' ? { background: TOUR_COLOR, color: 'white' } : { background: '#f3f4f6', color: '#4b5563' }}>
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
