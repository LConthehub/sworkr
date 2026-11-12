import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import Modal from '../components/Modal';
import AppointmentForm from '../components/AppointmentForm';
import { colorFor, formatDuration, formatTime, monthGrid, sameDay, STATUS_STYLES } from '../colors';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export default function AppointmentCalendar() {
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCancelled, setShowCancelled] = useState(false);
  const [selectedDay, setSelectedDay] = useState(() => new Date());
  const [modal, setModal] = useState(null); // { appointment } or { defaultDate }

  const days = useMemo(() => monthGrid(month), [month]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get('/api/appointments', {
        params: {
          start: days[0].toISOString(),
          end: new Date(days[41].getFullYear(), days[41].getMonth(), days[41].getDate() + 1).toISOString(),
          limit: 1000,
        },
      });
      setAppointments(data);
    } catch (err) {
      console.error('Error loading appointments:', err);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const visible = appointments.filter((a) => showCancelled || a.status !== 'cancelled');
  const onDay = (day) => visible.filter((a) => sameDay(new Date(a.scheduled_date), day));
  const today = new Date();
  const selectedItems = onDay(selectedDay);

  const changeMonth = (delta) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + delta, 1));
  const goToday = () => {
    setMonth(new Date(today.getFullYear(), today.getMonth(), 1));
    setSelectedDay(today);
  };

  const openNew = (day) => {
    const d = new Date(day);
    d.setHours(19, 0, 0, 0);
    setModal({ defaultDate: d });
  };
  const closeAndReload = () => { setModal(null); load(); };

  const quickStatus = async (appt, status) => {
    await axios.put(`/api/appointments/${appt.id}/status`, null, { params: { status } });
    load();
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      {/* Month grid */}
      <div className="bg-white rounded-2xl shadow-lg p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <button onClick={() => changeMonth(-1)} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600" aria-label="Previous month">←</button>
            <h1 className="text-xl font-bold text-gray-800 min-w-44 text-center">
              {month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
            </h1>
            <button onClick={() => changeMonth(1)} className="w-8 h-8 rounded-lg hover:bg-gray-100 text-gray-600" aria-label="Next month">→</button>
            <button onClick={goToday} className="ml-2 px-3 py-1 rounded-lg border border-gray-200 text-sm text-gray-600 hover:bg-gray-50">Today</button>
            {loading && <span className="w-4 h-4 animate-spin border-2 rounded-full border-sworkr-500/20 border-t-sworkr-500" />}
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-gray-500">
              <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />
              Show cancelled
            </label>
            <button
              onClick={() => openNew(selectedDay)}
              className="px-4 py-1.5 rounded-full text-sm font-medium bg-sworkr-500 text-white hover:bg-sworkr-600"
            >
              + New appointment
            </button>
          </div>
        </div>

        <div className="grid grid-cols-7 text-xs font-medium text-gray-400 mb-1">
          {WEEKDAYS.map((d) => <div key={d} className="px-2 py-1">{d}</div>)}
        </div>
        <div className="grid grid-cols-7 gap-px bg-gray-100 border border-gray-100 rounded-xl overflow-hidden">
          {days.map((day) => {
            const items = onDay(day);
            const inMonth = day.getMonth() === month.getMonth();
            const isToday = sameDay(day, today);
            const isSelected = sameDay(day, selectedDay);
            return (
              <div
                key={day.toISOString()}
                onClick={() => setSelectedDay(day)}
                onDoubleClick={() => openNew(day)}
                className={`min-h-24 sm:min-h-28 p-1.5 cursor-pointer transition-colors ${
                  inMonth ? 'bg-white' : 'bg-gray-50'
                } ${isSelected ? 'ring-2 ring-inset ring-sworkr-300' : 'hover:bg-sworkr-50/50'}`}
              >
                <div className="flex justify-between items-center mb-1">
                  <span
                    className={`text-xs w-6 h-6 flex items-center justify-center rounded-full ${
                      isToday ? 'bg-sworkr-500 text-white font-bold' : inMonth ? 'text-gray-700' : 'text-gray-300'
                    }`}
                  >
                    {day.getDate()}
                  </span>
                </div>
                <div className="space-y-0.5">
                  {items.slice(0, 3).map((a) => (
                    <button
                      key={a.id}
                      onClick={(e) => { e.stopPropagation(); setModal({ appointment: a }); }}
                      className={`block w-full text-left text-white rounded px-1.5 py-0.5 text-[11px] truncate hover:opacity-90 ${
                        a.status === 'cancelled' ? 'opacity-50 line-through' : ''
                      }`}
                      style={{ background: a.status === 'completed' ? '#6b7280' : colorFor(a.service_type) }}
                      title={`${formatTime(new Date(a.scheduled_date))} · ${a.client_name} · ${a.service_type}`}
                    >
                      {formatTime(new Date(a.scheduled_date))} {a.client_name}
                    </button>
                  ))}
                  {items.length > 3 && <p className="text-[11px] text-gray-400 px-1">+{items.length - 3} more</p>}
                </div>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-gray-400 mt-2">Click a day to see it · double-click to add an appointment · click an appointment to edit it</p>
      </div>

      {/* Selected day */}
      <div className="bg-white rounded-2xl shadow-lg p-5 h-fit">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-800">
            {selectedDay.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}
          </h2>
          <button onClick={() => openNew(selectedDay)} className="text-sm text-sworkr-600 hover:text-sworkr-800">+ Add</button>
        </div>
        {selectedItems.length === 0 ? (
          <p className="text-sm text-gray-400 py-6 text-center">Nothing booked</p>
        ) : (
          <ul className="space-y-2">
            {selectedItems.map((a) => {
              const startAt = new Date(a.scheduled_date);
              const endAt = new Date(startAt.getTime() + a.duration_minutes * 60000);
              return (
                <li key={a.id} className="rounded-xl border border-gray-100 p-3 hover:shadow-sm">
                  <button onClick={() => setModal({ appointment: a })} className="block w-full text-left">
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: colorFor(a.service_type) }} />
                      <span className="text-sm font-medium text-gray-800">{a.client_name || 'Unknown client'}</span>
                      <span className={`ml-auto px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_STYLES[a.status].badge}`}>
                        {STATUS_STYLES[a.status].label}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {formatTime(startAt)}–{formatTime(endAt)} · {formatDuration(a.duration_minutes)} · {a.service_type}
                    </p>
                    {a.notes && <p className="text-xs text-gray-400 mt-1 line-clamp-2">{a.notes}</p>}
                  </button>
                  {a.status === 'scheduled' && (
                    <div className="flex gap-2 mt-2">
                      <button onClick={() => quickStatus(a, 'completed')} className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100">✓ Done</button>
                      <button onClick={() => quickStatus(a, 'cancelled')} className="text-xs px-2 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100">✕ Cancel</button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {modal && (
        <Modal title={modal.appointment ? 'Edit appointment' : 'New appointment'} onClose={() => setModal(null)}>
          <AppointmentForm
            appointment={modal.appointment}
            defaultDate={modal.defaultDate}
            onSaved={closeAndReload}
            onDeleted={closeAndReload}
          />
        </Modal>
      )}
    </div>
  );
}
