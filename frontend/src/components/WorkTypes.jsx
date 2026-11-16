import { useEffect, useState } from 'react';
import axios from 'axios';
import Modal, { errorMessage, buttonClass, quietButtonClass } from './Modal';
import { reloadCategories } from '../api';

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
  if (!open) return null;
  return (
    <Modal title="How do you work?" onClose={() => setOpen(false)}>
      {demo && <p className="text-xs rounded-lg bg-amber-50 border border-amber-200 text-amber-900 px-3 py-2 mb-3">This is what a new person sees the first time they log in. In the demo it's already answered; change it if you like, it resets overnight.</p>}
      <p className="text-sm text-gray-600 mb-3">Tick everything that applies. sworkr sets itself up to match, and you can change it any time on the Account page.</p>
      <WorkTypesPicker saveLabel="Set up sworkr" onSaved={() => setTimeout(() => setOpen(false), 1200)} onSkip={() => setOpen(false)} />
    </Modal>
  );
}
