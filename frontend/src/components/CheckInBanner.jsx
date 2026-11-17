import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { BACKGROUND } from '../api';
import { formatTime } from '../colors';

/**
 * Shown on every page while an appointment with safety check-in is under way or has ended
 * without a check-in. One tap says "I'm safe" and stops the alert to the trusted contact.
 */
export default function CheckInBanner() {
  const [waiting, setWaiting] = useState([]);
  const [now, setNow] = useState(() => new Date());

  const load = useCallback(async (background = true) => {
    try {
      const { data } = await axios.get('/api/safety/watch', background ? BACKGROUND : undefined);
      setWaiting(data);
      setNow(new Date());
    } catch {
      /* the next round will try again */
    }
  }, []);

  useEffect(() => {
    load(false);
    const id = setInterval(load, 60000);
    const onChange = () => load(false);
    window.addEventListener('sworkr:appointments-changed', onChange);
    return () => {
      clearInterval(id);
      window.removeEventListener('sworkr:appointments-changed', onChange);
    };
  }, [load]);

  const checkIn = async (a) => {
    try {
      await axios.post(`/api/appointments/${a.id}/check-in`);
    } catch (err) {
      console.error(err);
    }
    load(false);
    window.dispatchEvent(new Event('sworkr:appointments-changed'));
  };

  if (waiting.length === 0) return null;

  return (
    <div className="space-y-2 mb-4">
      {waiting.map((a) => {
        const ended = new Date(a.ends_at) <= now;
        const alertAt = new Date(a.alert_at);
        const overdue = alertAt <= now;
        return (
          <div
            key={a.id}
            role="alert"
            className={`rounded-2xl shadow-lg px-4 py-3 flex flex-wrap items-center gap-3 ${overdue ? 'bg-red-600 text-white' : ended ? 'bg-amber-400 text-gray-900' : 'bg-white text-gray-800'}`}
          >
            <div className="flex-1 min-w-52">
              <p className="font-semibold">
                {overdue ? 'Check-in overdue' : ended ? 'Time to check in' : 'Check-in is on for this appointment'}
              </p>
              <p className="text-sm opacity-90">
                {a.client_name || 'Appointment'} · ends {formatTime(new Date(a.ends_at))}
                {a.alert_sent_at
                  ? ' · your trusted contact has been emailed'
                  : a.alert_error
                    ? " · the alert email couldn't be sent"
                    : ` · alert at ${formatTime(alertAt)}`}
              </p>
            </div>
            <button
              onClick={() => checkIn(a)}
              className={`px-4 py-2 rounded-lg font-semibold text-sm ${overdue ? 'bg-white text-red-700 hover:bg-red-50' : 'bg-emerald-600 text-white hover:bg-emerald-700'}`}
            >
              ✓ I'm safe
            </button>
          </div>
        );
      })}
    </div>
  );
}
