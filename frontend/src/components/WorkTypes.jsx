import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import Modal, { errorMessage, buttonClass, quietButtonClass } from './Modal';
import { reloadCategories } from '../api';
import { reloadFeatures } from '../features';

/** The kinds of work as checkboxes. Saving adds each kind's starter categories and workplaces and platforms. */
export function WorkTypesPicker({ onSaved, onSkip, saveLabel = 'Save' }) {
  const [profile, setProfile] = useState(null);
  const [chosen, setChosen] = useState([]);
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    axios.get('/api/work-profile').then(({ data }) => {
      setProfile(data);
      setChosen(data.work_types || []);
    }).catch(() => {});
  }, []);

  const toggle = (key) => setChosen((c) => (c.includes(key) ? c.filter((k) => k !== key) : [...c, key]));
  const save = async (types) => {
    setSaving(true);
    setMessage(null);
    try {
      const { data } = await axios.put('/api/work-profile', { work_types: types });
      reloadCategories().catch(() => {});
      reloadFeatures();
      const added = [...data.added.categories, ...data.added.sources];
      setMessage({ ok: added.length ? `Added: ${added.join(', ')}.` : 'Saved.' });
      onSaved?.(data);
    } catch (err) {
      setMessage({ error: errorMessage(err, 'Could not save') });
    } finally {
      setSaving(false);
    }
  };

  if (!profile) return null;
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {profile.options.map((o) => (
          <label key={o.key} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer ${chosen.includes(o.key) ? 'border-sworkr-300 bg-sworkr-50' : 'border-gray-200'}`}>
            <input type="checkbox" checked={chosen.includes(o.key)} onChange={() => toggle(o.key)} />
            {o.label}
          </label>
        ))}
      </div>
      <p className="text-xs text-gray-500">
        Each one adds starter expense categories and workplaces and platforms, which you can rename, change or hide on the
        Money page. Nothing is removed if you untick one later.
      </p>
      {message && (
        <p className={`text-sm rounded-lg px-3 py-2 ${message.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>{message.ok || message.error}</p>
      )}
      <div className="flex justify-end gap-2">
        {onSkip && <button type="button" onClick={() => save([]).then(onSkip)} className={quietButtonClass}>Skip for now</button>}
        <button type="button" disabled={saving} onClick={() => save(chosen)} className={buttonClass}>{saving ? 'Saving…' : saveLabel}</button>
      </div>
    </div>
  );
}

/**
 * Asked once, after the first login, until the person answers or skips.
 * In the demo it's shown once each time someone opens it in a browser tab, so the first-run can be tried.
 */
export function WorkTypesFirstRun({ demo = false }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (demo) {
      let seen = false;
      try { seen = sessionStorage.getItem('sworkr-demo-first-run') === '1'; sessionStorage.setItem('sworkr-demo-first-run', '1'); } catch { /* private window */ }
      setOpen(!seen);
      return;
    }
    axios.get('/api/work-profile').then(({ data }) => setOpen(data.work_types === null)).catch(() => {});
  }, [demo]);
  const [step, setStep] = useState('work');   // 'work', then 'connect'
  if (!open) return null;
  if (step === 'connect') return <ConnectStep onClose={() => setOpen(false)} />;
  return (
    <Modal title="How do you work?" onClose={() => setOpen(false)}>
      {demo && <p className="text-xs rounded-lg bg-amber-50 border border-amber-200 text-amber-900 px-3 py-2 mb-3">This is what a new person sees the first time they log in. In the demo it's already answered; change it if you like, it resets overnight.</p>}
      <p className="text-sm text-gray-600 mb-3">Tick everything that applies. sworkr sets itself up to match, and you can change it any time on the Account page.</p>
      <WorkTypesPicker saveLabel="Set up sworkr" onSaved={() => setTimeout(() => setStep('connect'), 900)} onSkip={() => setStep('connect')} />
    </Modal>
  );
}

const CONNECTIONS = [
  ['Email', 'Read and send mail from your work address inside sworkr; needed for safety check-in alerts.', '/account/connections'],
  ['Calendar sync', 'Your bookings and tasks in your phone’s calendar (Nextcloud, iCloud or any CalDAV).', '/account/connections'],
  ['Content library', 'The folder with your photos and videos, for planning posts.', '/account/connections'],
  ['Phone notifications', 'A message on your phone before a booking, and a morning summary (ntfy).', '/account/notifications'],
  ['On your phone', 'Use sworkr from your phone, privately, like an app.', '/account/connections'],
];
const HEALTH = [
  ['Period tracker', '/account/health'],
  ['Birth control & regular meds', '/account/health'],
  ['Health tests', '/account/health'],
];

/** First run, step two: offer the connections and health tracking. Every part is optional. */
function ConnectStep({ onClose }) {
  const [wellness, setWellness] = useState(false);
  const toggleWellness = async (e) => {
    const { data } = await axios.put('/api/wellness/settings', { enabled: e.target.checked }).catch(() => ({ data: { enabled: false } }));
    setWellness(data.enabled);
  };
  return (
    <Modal title="Connect what you use" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-gray-600">Set up any of these now or later, all under Settings. Everything stays on your own computer and accounts.</p>
        <ul className="divide-y divide-gray-100">
          {CONNECTIONS.map(([name, what, to]) => (
            <li key={name} className="py-2 flex items-center gap-3">
              <span className="flex-1">
                <span className="block text-sm font-medium text-gray-800">{name}</span>
                <span className="block text-xs text-gray-500">{what}</span>
              </span>
              <Link to={to} onClick={onClose} className={quietButtonClass}>Set up</Link>
            </li>
          ))}
        </ul>
        <div className="border-t border-gray-100 pt-3 space-y-2">
          <p className="text-sm font-medium text-gray-800">Health tracking (optional)</p>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={wellness} onChange={toggleWellness} /> A daily check-in: sleep, water, food, energy
          </label>
          <div className="flex flex-wrap gap-2">
            {HEALTH.map(([name, to]) => <Link key={name} to={to} onClick={onClose} className={quietButtonClass}>{name}</Link>)}
          </div>
        </div>
        <div className="flex justify-end"><button type="button" onClick={onClose} className={buttonClass}>Done</button></div>
      </div>
    </Modal>
  );
}
