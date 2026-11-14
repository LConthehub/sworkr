import { useEffect, useRef } from 'react';
import axios from 'axios';
import { BACKGROUND } from '../api';
import { formatTime } from '../colors';

const KEY = 'sworkr.reminders';

/** Reminder settings live in this browser only: { enabled, minutes, discreet }. */
export function reminderSettings() {
  try {
    return { enabled: false, minutes: 30, discreet: true, posts: true, ...JSON.parse(localStorage.getItem(KEY) || '{}') };
  } catch {
    return { enabled: false, minutes: 30, discreet: true, posts: true };
  }
}

export function saveReminderSettings(settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(settings));
  } catch {
    /* private window: reminders just stay off */
  }
  window.dispatchEvent(new Event('sworkr:reminders-changed'));
}

export const notificationsSupported = () => typeof window !== 'undefined' && 'Notification' in window;

/**
 * Shows a browser notification a while before each appointment.
 * Works only while sworkr is open in a tab, and only in this browser.
 */
export default function Reminders() {
  const shown = useRef(new Set());

  useEffect(() => {
    let timer;
    const check = async () => {
      const settings = reminderSettings();
      if (!settings.enabled || !notificationsSupported() || Notification.permission !== 'granted') return;
      try {
        const now = new Date();
        const { data } = await axios.get('/api/appointments', {
          ...BACKGROUND,
          params: { status: 'scheduled', start: now.toISOString(), end: new Date(now.getTime() + 24 * 3600 * 1000).toISOString(), limit: 50 },
        });
        for (const a of data) {
          const start = new Date(a.scheduled_date);
          const minutesAway = (start - now) / 60000;
          const key = `${a.id}:${a.scheduled_date}`;
          if (minutesAway <= settings.minutes && minutesAway > -1 && !shown.current.has(key)) {
            shown.current.add(key);
            const body = settings.discreet ? `At ${formatTime(start)}` : `${a.client_name || 'Client'} · ${a.service_type} at ${formatTime(start)}`;
            // eslint-disable-next-line no-new
            new Notification(settings.discreet ? 'Appointment soon' : 'sworkr: appointment soon', { body, tag: key });
          }
        }
        if (settings.posts) {
          const { data: posts } = await axios.get('/api/posts', {
            ...BACKGROUND,
            params: { status: 'open', start: new Date(now.getTime() - 60000).toISOString(), end: new Date(now.getTime() + 24 * 3600 * 1000).toISOString() },
          });
          for (const p of posts) {
            if (!p.scheduled_at) continue;
            const due = new Date(p.scheduled_at);
            const key = `post:${p.id}:${p.scheduled_at}`;
            if ((due - now) / 60000 <= Math.min(settings.minutes, 15) && !shown.current.has(key)) {
              shown.current.add(key);
              // eslint-disable-next-line no-new
              new Notification(settings.discreet ? 'Reminder' : `sworkr: ${p.platform} post due`,
                { body: settings.discreet ? `At ${formatTime(due)}` : `${p.platform}${p.account ? ` (${p.account})` : ''} at ${formatTime(due)}`, tag: key });
            }
          }
        }
      } catch {
        /* not logged in, or offline: try again next round */
      }
    };
    check();
    timer = setInterval(check, 60000);
    window.addEventListener('sworkr:reminders-changed', check);
    return () => {
      clearInterval(timer);
      window.removeEventListener('sworkr:reminders-changed', check);
    };
  }, []);

  return null;
}
